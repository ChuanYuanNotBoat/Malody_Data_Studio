import json
import os
import sys
import threading
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Literal, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.core.services.crawler_task_service import crawler_task_service

router = APIRouter(
    prefix="/crawler",
    tags=["crawler"],
    dependencies=[Depends(require_api_key)],
)

MAX_SAFE_PLAYER_WORKERS = 8
MAX_SAFE_RPM = 120
SOURCE_HEALTH_TTL_SECONDS = 60

_source_health_cache: Dict[str, Any] = {
    "checked_at": None,
    "data": None,
}
_source_health_lock = threading.Lock()
_source_health_refreshing = False


def _safe_read_json(path: str) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return {}, str(e)


def _file_meta(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"exists": False}
    stat = os.stat(path)
    return {
        "exists": True,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def _ping_url(url: str, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    req = Request(url, method="GET", headers={"User-Agent": "malody-api-health-check"})
    started_at = datetime.now()
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            code = getattr(resp, "status", 200)
            ok = 200 <= code < 400
            return {
                "ok": ok,
                "status_code": code,
                "latency_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                "error": None,
            }
    except HTTPError as e:
        return {
            "ok": False,
            "status_code": e.code,
            "latency_ms": int((datetime.now() - started_at).total_seconds() * 1000),
            "error": f"http_error:{e.code}",
        }
    except URLError as e:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((datetime.now() - started_at).total_seconds() * 1000),
            "error": f"network_error:{e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((datetime.now() - started_at).total_seconds() * 1000),
            "error": f"unknown_error:{e}",
        }


def _extract_failure_category(lines: list[str]) -> str:
    haystack = "\n".join(lines).lower()
    if any(key in haystack for key in ["401", "403", "unauthorized", "forbidden", "cookie", "auth"]):
        return "auth"
    if any(
        key in haystack
        for key in ["timeout", "connection", "dns", "socket", "ssl", "reset by peer", "network", "urlopen"]
    ):
        return "network"
    if any(
        key in haystack
        for key in ["parse", "selector", "xpath", "missing", "not found", "schema", "unexpected structure", "json decode"]
    ):
        return "structure"
    return "unknown"


def _build_failure_stats() -> Dict[str, Any]:
    failed_tasks = crawler_task_service.list_tasks(status="failed", limit=50)
    counts = Counter()
    samples: Dict[str, Dict[str, Any]] = {}
    for task in failed_tasks:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        log_data = crawler_task_service.read_task_log(task_id, tail=30)
        lines = log_data.get("lines") or []
        category = _extract_failure_category(lines)
        counts[category] += 1
        if category not in samples:
            samples[category] = {
                "task_id": task_id,
                "crawler_type": task.get("crawler_type"),
            }
    return {
        "counts": {
            "network": counts.get("network", 0),
            "structure": counts.get("structure", 0),
            "auth": counts.get("auth", 0),
            "unknown": counts.get("unknown", 0),
        },
        "sample_tasks": samples,
    }


def _collect_data_source_health(now: datetime) -> Dict[str, Any]:
    checks = {
        "home": _ping_url("https://m.mugzone.net/"),
        "latest": _ping_url("https://m.mugzone.net/charts/latest"),
        "api": _ping_url("https://m.mugzone.net/api"),
    }
    failure_stats = _build_failure_stats()
    healthy_count = sum(1 for item in checks.values() if item.get("ok"))
    overall = "healthy" if healthy_count == len(checks) else "degraded" if healthy_count > 0 else "unavailable"

    data = {
        "overall": overall,
        "checked_at": now.isoformat(),
        "ttl_seconds": SOURCE_HEALTH_TTL_SECONDS,
        "sources": checks,
        "failure_categories": failure_stats,
    }


def _refresh_source_health_cache_background() -> None:
    global _source_health_refreshing
    try:
        now = datetime.now()
        data = _collect_data_source_health(now)
        with _source_health_lock:
            _source_health_cache["checked_at"] = now.timestamp()
            _source_health_cache["data"] = data
    finally:
        with _source_health_lock:
            _source_health_refreshing = False


def _build_data_source_health(force_refresh: bool = False) -> Dict[str, Any]:
    global _source_health_refreshing
    now = datetime.now()
    now_ts = now.timestamp()
    with _source_health_lock:
        checked_at = _source_health_cache.get("checked_at")
        cached_data = _source_health_cache.get("data")
        refreshing = _source_health_refreshing
        if (
            not force_refresh
            and isinstance(checked_at, (int, float))
            and cached_data is not None
            and now_ts - checked_at < SOURCE_HEALTH_TTL_SECONDS
        ):
            return cached_data

        if not force_refresh and cached_data is not None:
            if not refreshing:
                _source_health_refreshing = True
                thread = threading.Thread(target=_refresh_source_health_cache_background, daemon=True)
                thread.start()
            stale_view = dict(cached_data)
            stale_view["refresh_in_progress"] = True
            stale_view["stale_seconds"] = int(max(0, now_ts - checked_at)) if isinstance(checked_at, (int, float)) else None
            return stale_view

    data = _collect_data_source_health(now)
    with _source_health_lock:
        _source_health_cache["checked_at"] = now_ts
        _source_health_cache["data"] = data
        _source_health_refreshing = False

    return data


@router.post("/run", response_model=APIResponse)
async def run_crawler(
    background_tasks: BackgroundTasks,
    crawler_type: Literal["leaderboard", "player", "stb"] = Query("leaderboard"),
    once: bool = Query(True),
    limit: Optional[int] = Query(None),
    rpm: Optional[int] = Query(None),
    uid: Optional[str] = Query(None),
    uid_range: Optional[str] = Query(None),
    from_db: bool = Query(False),
    max_workers: Optional[int] = Query(None),
    days_since_update: Optional[int] = Query(None),
    source: Optional[str] = Query(None),
    cid_crawl: bool = Query(False),
    sid_crawl: bool = Query(False),
    retry_failed: bool = Query(False),
    start: Optional[int] = Query(None),
    end: Optional[int] = Query(None),
    resume: bool = Query(True),
):
    del background_tasks  # kept for backward compatibility with old route signature

    script_map = {
        "leaderboard": os.path.join("crawlers", "rankings.py"),
        "player": os.path.join("crawlers", "player_profile.py"),
        "stb": os.path.join("crawlers", "stb.py"),
    }
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base_dir, script_map[crawler_type])
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail=f"crawler script not found: {script}")

    cmd = [sys.executable, script]

    if crawler_type == "leaderboard":
        if once:
            cmd.append("--once")
        if source:
            if source not in {"page", "newapi"}:
                raise HTTPException(status_code=400, detail="leaderboard source must be one of: page/newapi")
            cmd.extend(["--ranking-source", source])
        if limit is not None:
            if limit <= 0:
                raise HTTPException(status_code=400, detail="limit must be > 0")
            cmd.extend(["--ranking-limit", str(limit)])
        if any(
            [
                uid,
                uid_range,
                from_db,
                max_workers,
                days_since_update,
                cid_crawl,
                sid_crawl,
                retry_failed,
                start is not None,
                end is not None,
                resume is not True,
            ]
        ):
            raise HTTPException(status_code=400, detail="leaderboard does not support player/stb-only parameters")

    elif crawler_type == "player":
        if uid:
            cmd.extend(["--uid", uid])
        if uid_range:
            cmd.extend(["--uid-range", uid_range])
        if from_db:
            cmd.append("--from-db")
        if limit is not None:
            cmd.extend(["--limit", str(limit)])
        if max_workers is not None:
            if max_workers <= 0:
                raise HTTPException(status_code=400, detail="max_workers must be > 0")
            if max_workers > MAX_SAFE_PLAYER_WORKERS:
                raise HTTPException(status_code=400, detail=f"max_workers must be <= {MAX_SAFE_PLAYER_WORKERS}")
            cmd.extend(["--max-workers", str(max_workers)])
        if days_since_update is not None:
            if days_since_update <= 0:
                raise HTTPException(status_code=400, detail="days_since_update must be > 0")
            cmd.extend(["--days-since-update", str(days_since_update)])
        if rpm is not None:
            if rpm <= 0:
                raise HTTPException(status_code=400, detail="rpm must be > 0")
            if rpm > MAX_SAFE_RPM:
                raise HTTPException(status_code=400, detail=f"rpm must be <= {MAX_SAFE_RPM}")
            cmd.extend(["--rpm", str(rpm)])
        if any([source, cid_crawl, sid_crawl, retry_failed, start is not None, end is not None, resume is not True]):
            raise HTTPException(status_code=400, detail="player does not support stb parameters")

    else:
        if once:
            cmd.append("--once")
        if limit is not None:
            cmd.extend(["--max-charts", str(limit)])
        if rpm is not None:
            if rpm <= 0:
                raise HTTPException(status_code=400, detail="rpm must be > 0")
            if rpm > MAX_SAFE_RPM:
                raise HTTPException(status_code=400, detail=f"rpm must be <= {MAX_SAFE_RPM}")
            cmd.extend(["--rpm", str(rpm)])
        if source:
            if source not in {"all", "home", "latest", "api", "newapi"}:
                raise HTTPException(status_code=400, detail="source must be one of: all/home/latest/api/newapi")
            cmd.extend(["--source", source])
        if cid_crawl:
            cmd.append("--cid-crawl")
        if sid_crawl:
            cmd.append("--sid-crawl")
        if retry_failed:
            cmd.append("--retry-failed")
        if start is not None:
            if start <= 0:
                raise HTTPException(status_code=400, detail="start must be > 0")
            if cid_crawl or (not sid_crawl):
                cmd.extend(["--start-cid", str(start)])
            if sid_crawl:
                cmd.extend(["--start-sid", str(start)])
        if end is not None:
            if end <= 0:
                raise HTTPException(status_code=400, detail="end must be > 0")
            if cid_crawl or (not sid_crawl):
                cmd.extend(["--end-cid", str(end)])
            if sid_crawl:
                cmd.extend(["--end-sid", str(end)])
        if not resume:
            cmd.append("--no-resume")
        if any([uid, uid_range, from_db, max_workers, days_since_update]):
            raise HTTPException(status_code=400, detail="stb does not support player parameters")

    task = crawler_task_service.create_task(cmd, crawler_type)
    return APIResponse(
        success=True,
        data={"command": cmd, "task": task},
        message=f"crawler {crawler_type} started",
        timestamp=datetime.now(),
    )


@router.get("/status", response_model=APIResponse)
async def get_crawler_status():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cid_path = os.path.join(base_dir, "cid_progress.json")
    sid_path = os.path.join(base_dir, "sid_progress.json")
    sid_back_path = os.path.join(base_dir, "sid_backwards_progress.json")
    global_path = os.path.join(base_dir, "global_progress.bin")

    status = {
        "cid": _file_meta(cid_path),
        "sid": _file_meta(sid_path),
        "sid_backwards": _file_meta(sid_back_path),
        "global": _file_meta(global_path),
    }

    if status["cid"]["exists"]:
        cid_data, cid_err = _safe_read_json(cid_path)
        if cid_err:
            status["cid"]["error"] = f"failed to parse progress file: {cid_err}"
        else:
            status["cid"]["progress"] = {
                "current": cid_data.get("current_cid"),
                "success": cid_data.get("total_success", 0),
                "errors": cid_data.get("total_errors", 0),
                "retry_queue_size": len(cid_data.get("retry_queue", []) or []),
            }

    if status["sid"]["exists"]:
        sid_data, sid_err = _safe_read_json(sid_path)
        if sid_err:
            status["sid"]["error"] = f"failed to parse progress file: {sid_err}"
        else:
            status["sid"]["progress"] = {
                "current": sid_data.get("current_sid"),
                "songs": sid_data.get("total_songs", 0),
                "charts": sid_data.get("total_charts", 0),
                "empty_songs_size": len(sid_data.get("empty_songs", []) or []),
                "failed_sids_size": len(sid_data.get("failed_sids", []) or []),
            }

    if status["sid_backwards"]["exists"]:
        sb_data, sb_err = _safe_read_json(sid_back_path)
        if sb_err:
            status["sid_backwards"]["error"] = f"failed to parse progress file: {sb_err}"
        else:
            status["sid_backwards"]["progress"] = {
                "current": sb_data.get("current_sid"),
                "last_valid_sid": sb_data.get("last_valid_sid"),
                "songs": sb_data.get("total_songs", 0),
                "charts": sb_data.get("total_charts", 0),
                "failed_sids_size": len(sb_data.get("failed_sids", []) or []),
            }

    status["tasks"] = crawler_task_service.summarize()
    status["data_source_health"] = _build_data_source_health()
    return APIResponse(success=True, data=status, timestamp=datetime.now())


@router.get("/tasks", response_model=APIResponse)
async def list_crawler_tasks(
    status: Optional[str] = Query(None, description="Task status filter"),
    limit: int = Query(50, ge=1, le=500, description="Max tasks to return"),
):
    tasks = crawler_task_service.list_tasks(status=status, limit=limit)
    return APIResponse(
        success=True,
        data={"tasks": tasks, "count": len(tasks)},
        timestamp=datetime.now(),
    )


@router.get("/tasks/{task_id}", response_model=APIResponse)
async def get_crawler_task(task_id: str):
    task = crawler_task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return APIResponse(success=True, data=task, timestamp=datetime.now())


@router.get("/tasks/{task_id}/log", response_model=APIResponse)
async def get_crawler_task_log(
    task_id: str,
    tail: int = Query(200, ge=1, le=2000, description="Tail line count"),
):
    data = crawler_task_service.read_task_log(task_id, tail=tail)
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="task not found")
    return APIResponse(success=True, data=data, timestamp=datetime.now())
