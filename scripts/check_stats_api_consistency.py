#!/usr/bin/env python3
"""
检查关键统计指标在“数据库基准计算”和“API返回”之间的一致性，并输出差异报告。

使用示例:
  python scripts/check_stats_api_consistency.py --base-url http://localhost:8000 --mode 0
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests


def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def calc_summary_baseline(conn: sqlite3.Connection, mode: int) -> Dict[str, Any]:
    cur = conn.cursor()
    where = "1=1"
    params: List[Any] = []
    if mode != -1:
        where = "mode = ?"
        params.append(mode)

    cur.execute(f"SELECT COUNT(*) AS v FROM charts WHERE {where}", params)
    total_charts = cur.fetchone()["v"]
    cur.execute(f"SELECT COUNT(DISTINCT sid) AS v FROM charts WHERE {where}", params)
    unique_songs = cur.fetchone()["v"]
    cur.execute(f"SELECT COUNT(DISTINCT creator_name) AS v FROM charts WHERE {where} AND creator_name IS NOT NULL", params)
    unique_creators = cur.fetchone()["v"]
    return {
        "total_charts": total_charts,
        "unique_songs": unique_songs,
        "unique_creators": unique_creators,
    }


def calc_quality_baseline(conn: sqlite3.Connection, mode: int) -> Dict[str, Any]:
    cur = conn.cursor()
    where = "1=1"
    params: List[Any] = []
    if mode != -1:
        where = "c.mode = ?"
        params.append(mode)

    cur.execute(f"SELECT COUNT(*) AS v FROM charts c WHERE {where}", params)
    total = cur.fetchone()["v"]

    checks = {
        "missing_creator_name": f"SELECT COUNT(*) AS v FROM charts c WHERE {where} AND c.creator_name IS NULL",
        "missing_level": f"SELECT COUNT(*) AS v FROM charts c WHERE {where} AND c.level IS NULL",
        "missing_last_updated": f"SELECT COUNT(*) AS v FROM charts c WHERE {where} AND c.last_updated IS NULL",
        "orphan_charts_without_song": f"SELECT COUNT(*) AS v FROM charts c LEFT JOIN songs s ON c.sid = s.sid WHERE {where} AND s.sid IS NULL",
        "negative_heat": f"SELECT COUNT(*) AS v FROM charts c WHERE {where} AND c.heat < 0",
        "negative_donate_count": f"SELECT COUNT(*) AS v FROM charts c WHERE {where} AND c.donate_count < 0",
    }

    issues = {}
    for k, q in checks.items():
        cur.execute(q, params)
        issues[k] = cur.fetchone()["v"]

    return {"total_charts_checked": total, "issues": issues}


def calc_top_stabilizers_baseline(conn: sqlite3.Connection, mode: int, limit: int) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    where = ["stabled_by_name IS NOT NULL", "status = 2"]
    params: List[Any] = []
    if mode != -1:
        where.append("mode = ?")
        params.append(mode)
    params.append(limit)
    q = f"""
    SELECT stabled_by_name, COUNT(*) AS stable_count
    FROM charts
    WHERE {' AND '.join(where)}
    GROUP BY stabled_by_name
    ORDER BY stable_count DESC
    LIMIT ?
    """
    cur.execute(q, params)
    return [{"stabilizer_name": r["stabled_by_name"], "stable_count": r["stable_count"]} for r in cur.fetchall()]


def api_get(base_url: str, path: str, params: Dict[str, Any]) -> Any:
    r = requests.get(f"{base_url.rstrip('/')}{path}", params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"API returned error for {path}: {payload.get('error')}")
    return payload.get("data")


def _calc_delta(baseline: Any, api_value: Any) -> Any:
    if isinstance(baseline, (int, float)) and isinstance(api_value, (int, float)):
        return api_value - baseline
    return None


def _rule_threshold(check_name: str, default_threshold: float, rules: Dict[str, float]) -> float:
    if check_name in rules:
        return rules[check_name]
    best_prefix = ""
    best_threshold = default_threshold
    for prefix, threshold in rules.items():
        if check_name.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_threshold = threshold
    return best_threshold


def _is_blocking_check(check_name: str, block_on_prefixes: Sequence[str]) -> bool:
    if not block_on_prefixes:
        return False
    if "*" in block_on_prefixes:
        return True
    return any(check_name.startswith(prefix) for prefix in block_on_prefixes)


def compare_values(
    name: str,
    baseline: Any,
    api_value: Any,
    default_threshold: float,
    threshold_rules: Dict[str, float],
    block_on_prefixes: Sequence[str],
) -> Dict[str, Any]:
    equal = baseline == api_value
    delta = _calc_delta(baseline, api_value)
    threshold = _rule_threshold(name, default_threshold, threshold_rules)
    exceeded = (abs(delta) > threshold) if delta is not None else (not equal)
    blocking = exceeded and _is_blocking_check(name, block_on_prefixes)
    return {
        "name": name,
        "baseline": baseline,
        "api": api_value,
        "equal": equal,
        "delta": delta,
        "threshold": threshold,
        "threshold_exceeded": exceeded,
        "blocking": blocking,
    }


def parse_csv_ints(raw: str) -> List[int]:
    if not raw.strip():
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def run_consistency_case(
    conn: sqlite3.Connection,
    base_url: str,
    mode: int,
    limit: int,
    *,
    default_threshold: float = 0,
    threshold_rules: Optional[Dict[str, float]] = None,
    block_on_prefixes: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    threshold_rules = threshold_rules or {}
    block_on_prefixes = block_on_prefixes or ["*"]
    summary_base = calc_summary_baseline(conn, mode)
    quality_base = calc_quality_baseline(conn, mode)
    top_base = calc_top_stabilizers_baseline(conn, mode, limit)

    summary_api = api_get(base_url, "/charts/summary", {"mode": mode})
    quality_api = api_get(base_url, "/charts/quality", {"mode": mode})
    top_api = api_get(base_url, "/charts/stabilizers/top", {"mode": mode, "limit": limit})

    checks: List[Dict[str, Any]] = []
    checks.append(
        compare_values(
            "summary.total_charts",
            summary_base["total_charts"],
            summary_api.get("total_charts"),
            default_threshold,
            threshold_rules,
            block_on_prefixes,
        )
    )
    checks.append(
        compare_values(
            "summary.unique_songs",
            summary_base["unique_songs"],
            summary_api.get("unique_songs"),
            default_threshold,
            threshold_rules,
            block_on_prefixes,
        )
    )
    checks.append(
        compare_values(
            "summary.unique_creators",
            summary_base["unique_creators"],
            summary_api.get("unique_creators"),
            default_threshold,
            threshold_rules,
            block_on_prefixes,
        )
    )
    checks.append(
        compare_values(
            "quality.total_charts_checked",
            quality_base["total_charts_checked"],
            quality_api.get("total_charts_checked"),
            default_threshold,
            threshold_rules,
            block_on_prefixes,
        )
    )
    for key, val in quality_base["issues"].items():
        api_count = (quality_api.get("issues", {}).get(key) or {}).get("count")
        checks.append(
            compare_values(
                f"quality.issues.{key}.count",
                val,
                api_count,
                default_threshold,
                threshold_rules,
                block_on_prefixes,
            )
        )

    baseline_top_pairs = [(x["stabilizer_name"], x["stable_count"]) for x in top_base]
    api_top_pairs = [(x.get("stabilizer_name"), x.get("stable_count")) for x in top_api]
    checks.append(
        compare_values(
            "top_stabilizers.rank_pairs",
            baseline_top_pairs,
            api_top_pairs,
            default_threshold,
            threshold_rules,
            block_on_prefixes,
        )
    )

    failed = [x for x in checks if not x["equal"]]
    blocked = [x for x in checks if x["blocking"]]
    exceeded = [x for x in checks if x["threshold_exceeded"]]
    return {
        "mode": mode,
        "limit": limit,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "failed_checks": len(failed),
            "threshold_exceeded_checks": len(exceeded),
            "blocking_checks": len(blocked),
        },
        "failed_items": [x["name"] for x in failed],
        "blocking_items": [x["name"] for x in blocked],
    }


def _parse_threshold_rules(raw: str) -> Dict[str, float]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("@"):
        payload = Path(text[1:]).read_text(encoding="utf-8")
        data = json.loads(payload)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("threshold rules must be a JSON object")
    parsed: Dict[str, float] = {}
    for key, val in data.items():
        parsed[str(key)] = float(val)
    return parsed


def _parse_prefixes(raw: str) -> List[str]:
    text = raw.strip()
    if not text:
        return ["*"]
    return [item.strip() for item in text.split(",") if item.strip()]


def main():
    parser = argparse.ArgumentParser(description="Compare DB baseline stats with API responses.")
    parser.add_argument("--db-path", default="data/malody_rankings.db")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--mode", type=int, default=-1)
    parser.add_argument("--modes", default="", help="Comma-separated mode list. If set, overrides --mode.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--limits", default="", help="Comma-separated limit list. If set, overrides --limit.")
    parser.add_argument(
        "--default-threshold",
        type=float,
        default=0,
        help="Default allowed absolute delta for numeric checks.",
    )
    parser.add_argument(
        "--threshold-rules",
        default="",
        help="JSON object or @file path mapping check name/prefix to threshold, e.g. '{\"quality.issues.\":2}'.",
    )
    parser.add_argument(
        "--block-on",
        default="*",
        help="Comma-separated check name prefixes that should block when threshold exceeded. '*' means all checks.",
    )
    parser.add_argument(
        "--fail-threshold",
        type=int,
        default=0,
        help="Exit with code 1 when a case has failed_checks greater than this threshold.",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    conn = db_connect(args.db_path)
    try:
        modes: Sequence[int] = parse_csv_ints(args.modes) if args.modes.strip() else [args.mode]
        limits: Sequence[int] = parse_csv_ints(args.limits) if args.limits.strip() else [args.limit]
        if not modes:
            raise ValueError("No mode provided. Set --mode or --modes.")
        if not limits:
            raise ValueError("No limit provided. Set --limit or --limits.")
        threshold_rules = _parse_threshold_rules(args.threshold_rules)
        block_on_prefixes = _parse_prefixes(args.block_on)

        cases: List[Dict[str, Any]] = []
        for mode in modes:
            for limit in limits:
                cases.append(
                    run_consistency_case(
                        conn,
                        args.base_url,
                        mode=mode,
                        limit=limit,
                        default_threshold=args.default_threshold,
                        threshold_rules=threshold_rules,
                        block_on_prefixes=block_on_prefixes,
                    )
                )

        report = {
            "generated_at": datetime.now().isoformat(),
            "params": {
                "mode": args.mode,
                "modes": list(modes),
                "limit": args.limit,
                "limits": list(limits),
                "base_url": args.base_url,
                "db_path": args.db_path,
                "fail_threshold": args.fail_threshold,
                "default_threshold": args.default_threshold,
                "threshold_rules": threshold_rules,
                "block_on": block_on_prefixes,
            },
            "cases": cases,
            "summary": {
                "total_cases": len(cases),
                "failed_cases": sum(1 for case in cases if case["summary"]["failed_checks"] > 0),
                "max_failed_checks": max((case["summary"]["failed_checks"] for case in cases), default=0),
                "threshold_exceeded_cases": sum(1 for case in cases if case["summary"]["threshold_exceeded_checks"] > 0),
                "blocking_cases": sum(1 for case in cases if case["summary"]["blocking_checks"] > 0),
            },
        }

        output_path = args.output.strip()
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"stats_api_consistency_report_{ts}.json"

        out = Path(output_path)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written: {out.resolve()}")
        print(
            "Cases: "
            f"{report['summary']['total_cases']}, "
            f"failed cases: {report['summary']['failed_cases']}, "
            f"max failed checks: {report['summary']['max_failed_checks']}, "
            f"blocking cases: {report['summary']['blocking_cases']}"
        )
        for case in cases:
            if case["summary"]["failed_checks"] > 0:
                print(f"[mode={case['mode']} limit={case['limit']}] failed: {case['summary']['failed_checks']}")
                for item in case["failed_items"]:
                    print(f"- {item}")

        if report["summary"]["max_failed_checks"] > args.fail_threshold:
            print(
                f"Consistency gate failed: max_failed_checks={report['summary']['max_failed_checks']} "
                f"> threshold={args.fail_threshold}"
            )
            sys.exit(1)
        if report["summary"]["blocking_cases"] > 0:
            print(f"Consistency gate failed: blocking_cases={report['summary']['blocking_cases']} > 0")
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

