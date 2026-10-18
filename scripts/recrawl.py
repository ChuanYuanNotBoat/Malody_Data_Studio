"""Manual-only isolated recrawl. Import, help and status never start requests."""

import argparse
import csv
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
import signal
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawlers.ingestion import TaskStore, atomic, atomic_json, now, save_record


def open_db(path, mode="rw"):
    return sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=" + mode, uri=True, timeout=30
    )


def known_ids(conn, kind):
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if kind == "player":
        queries = [
            f"SELECT uid FROM {table} WHERE uid IS NOT NULL AND uid!=''"
            for table in (
                "player_profiles",
                "player_identity",
                "player_profile_crawl_status",
                "player_rankings",
                "player_rankings_mm",
                "player_mmr_samples",
            )
            if table in tables
        ]
        if "player_config" in tables:
            queries.append(
                "SELECT player_identifier FROM player_config WHERE is_active=1"
            )
        return conn.execute(" UNION ".join(queries)) if queries else iter(())
    table, column = ("songs", "sid") if kind == "song" else ("charts", "cid")
    return (
        conn.execute(f"SELECT {column} FROM {table}") if table in tables else iter(())
    )


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def prepare(
    source, directory, *, uid_max=None, sid_max=None, cid_max=None, known_only=False
):
    source, directory = Path(source).resolve(), Path(directory).resolve()
    if directory.exists():
        raise ValueError("Batch directory already exists; resume it with run")
    if not known_only and any(
        not isinstance(value, int) or value <= 0
        for value in (uid_max, sid_max, cid_max)
    ):
        raise ValueError(
            "Supply verified --uid-max, --sid-max and --cid-max, or explicitly choose --known-only"
        )
    # Validate bounds before creating any directory or snapshot.
    with closing(open_db(source, "ro")) as conn:
        for kind, maximum in (
            ("player", uid_max),
            ("song", sid_max),
            ("chart", cid_max),
        ):
            highest = max(
                (int(row[0]) for row in known_ids(conn, kind) if str(row[0]).isdigit()),
                default=0,
            )
            if maximum is not None and maximum < highest:
                raise ValueError(
                    f"{kind} upper bound {maximum} is below known ID {highest}"
                )
        directory.mkdir(parents=True)
        with closing(sqlite3.connect(directory / "baseline.db")) as baseline:
            conn.backup(baseline, pages=4096)
    baseline_hash = digest(directory / "baseline.db")
    with closing(open_db(directory / "baseline.db", "ro")) as original, closing(
        sqlite3.connect(directory / "data.db")
    ) as conn:
        original.backup(conn)
        store = TaskStore(conn, "recrawl")
        with atomic(conn):
            # Previous daily queue generations never certify this new batch.
            conn.execute("DELETE FROM crawl_tasks")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS recrawl_ranges(kind TEXT PRIMARY KEY,next_id INTEGER,end_id INTEGER)"
            )
            for kind, maximum in (
                ("player", uid_max),
                ("song", sid_max),
                ("chart", cid_max),
            ):
                if maximum is not None:
                    conn.execute(
                        "INSERT INTO recrawl_ranges VALUES(?,1,?)", (kind, maximum)
                    )
                else:
                    for row in known_ids(original, kind):
                        if str(row[0]).isdigit():
                            store.add(kind, int(row[0]))
            for mode in range(10):
                for ranking in ("exp", "mm"):
                    store.add("ranking", f"{ranking}:{mode}", {"offset": 0})
    manifest = {
        "batch_id": uuid.uuid4().hex,
        "created_at": now(),
        "source": str(source),
        "baseline_hash": baseline_hash,
        "coverage": "known_only" if known_only else "operator_verified_bounds",
        "bounds": {"uid_max": uid_max, "sid_max": sid_max, "cid_max": cid_max},
        "status": "prepared",
        "manual_start_required": True,
    }
    atomic_json(directory / "manifest.json", manifest)
    return manifest


def feed_ranges(conn, count=500):
    store = TaskStore(conn, "recrawl")
    with atomic(conn):
        outstanding = conn.execute(
            "SELECT COUNT(*) FROM crawl_tasks WHERE scope='recrawl' AND state IN ('pending','running','retry')"
        ).fetchone()[0]
        if outstanding >= count:
            return
        for kind, start, end in conn.execute(
            "SELECT kind,next_id,end_id FROM recrawl_ranges WHERE next_id<=end_id"
        ).fetchall():
            stop = min(end + 1, start + count)
            for object_id in range(start, stop):
                store.add(kind, object_id)
            conn.execute(
                "UPDATE recrawl_ranges SET next_id=? WHERE kind=?", (stop, kind)
            )


def status(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    with closing(open_db(directory / "data.db", "ro")) as conn:
        counts = dict(
            conn.execute(
                "SELECT state,COUNT(*) FROM crawl_tasks WHERE scope='recrawl' GROUP BY state"
            )
        )
        ranges = [
            dict(zip(("kind", "next_id", "end_id"), row))
            for row in conn.execute("SELECT kind,next_id,end_id FROM recrawl_ranges")
        ]
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM crawl_observations WHERE entity IN ('charts','player_profiles') AND section IN ('comments','ranks') AND complete=0 AND observed_at>=?",
            (manifest["created_at"],),
        ).fetchone()[0]
    return {
        "batch_id": manifest["batch_id"],
        "coverage": manifest["coverage"],
        "tasks": counts,
        "ranges": ranges,
        "incomplete_sections": incomplete,
        "complete": not any(
            value for key, value in counts.items() if key not in ("done", "not_found")
        )
        and all(row["next_id"] > row["end_id"] for row in ranges)
        and incomplete == 0,
    }


def report(directory):
    """Write coverage, row differences and the complete outstanding task list."""
    directory = Path(directory).resolve()
    result = status(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    with closing(open_db(directory / "data.db", "ro")) as conn, closing(
        open_db(directory / "baseline.db", "ro")
    ) as baseline:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        old_tables = {
            row[0]
            for row in baseline.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        result["rows"] = {}
        result["null_or_empty_fields"] = {}
        monitored = {
            "charts": (
                "chart_length",
                "recommend_count",
                "not_recommend_count",
                "play_count",
                "checksum",
            ),
            "songs": ("title_org", "artist_org", "last_updated"),
            "player_profiles": ("join_date", "last_play_date"),
        }
        for table, fields in monitored.items():
            if table not in tables:
                continue
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            old_columns = {
                row[1] for row in baseline.execute(f"PRAGMA table_info({table})")
            }
            for field in fields:
                if field not in columns:
                    continue
                result["null_or_empty_fields"][table + "." + field] = {
                    "before": (
                        baseline.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL OR CAST({field} AS TEXT)='' "
                        ).fetchone()[0]
                        if field in old_columns
                        else None
                    ),
                    "after": conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL OR CAST({field} AS TEXT)='' "
                    ).fetchone()[0],
                }
        for table in (
            "player_profiles",
            "player_identity",
            "player_rankings",
            "player_rankings_mm",
            "player_mmr_samples",
            "songs",
            "charts",
            "chart_comments",
        ):
            if table in tables:
                result["rows"][table] = {
                    "before": (
                        baseline.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        if table in old_tables
                        else 0
                    ),
                    "after": conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[
                        0
                    ],
                }
        result["changed_entities"] = dict(
            conn.execute(
                "SELECT entity,COUNT(DISTINCT object_id) FROM crawl_changes WHERE observed_at>=? GROUP BY entity",
                (manifest["created_at"],),
            )
        )
        with (directory / "exceptions.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ("kind", "object_id", "state", "attempts", "next_attempt", "last_error")
            )
            writer.writerows(
                conn.execute(
                    "SELECT kind,object_id,state,attempts,next_attempt,last_error FROM crawl_tasks WHERE scope='recrawl' AND state!='done' ORDER BY kind,object_id"
                )
            )
    atomic_json(directory / "report.json", result)
    return result


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _schema(conn, database="main"):
    return conn.execute(
        f"SELECT type,name,tbl_name,sql FROM {database}.sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()


def publish(directory):
    """Explicit operator action. Abort if the source changed since preparation."""
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] == "published":
        raise ValueError("This batch was already published")
    if not status(directory)["complete"]:
        raise ValueError("Batch still has unfinished tasks or incomplete sections")
    if digest(directory / "baseline.db") != manifest["baseline_hash"]:
        raise ValueError("Baseline snapshot checksum mismatch")
    with closing(open_db(directory / "data.db", "ro")) as stage:
        if (
            stage.execute("PRAGMA quick_check").fetchone()[0] != "ok"
            or stage.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise ValueError("Staging database integrity check failed")
    with closing(open_db(manifest["source"])) as conn:
        conn.execute("ATTACH DATABASE ? AS baseline", (str(directory / "baseline.db"),))
        conn.execute("ATTACH DATABASE ? AS stage", (str(directory / "data.db"),))
        with atomic(conn):
            # BEGIN IMMEDIATE keeps other writers out throughout comparison and publication.
            if _schema(conn) != _schema(conn, "baseline"):
                raise ValueError(
                    "Source schema changed; reconcile against a new baseline before publishing"
                )
            tables = [row[1] for row in _schema(conn, "baseline") if row[0] == "table"]
            for table in tables:
                quoted = _quote(table)
                if (
                    conn.execute(f"SELECT COUNT(*) FROM main.{quoted}").fetchone()
                    != conn.execute(
                        f"SELECT COUNT(*) FROM baseline.{quoted}"
                    ).fetchone()
                ):
                    raise ValueError(
                        f"Source data changed in {table}; refusing to overwrite concurrent updates"
                    )
                for left, right in (("main", "baseline"), ("baseline", "main")):
                    if conn.execute(
                        f"SELECT * FROM {left}.{quoted} EXCEPT SELECT * FROM {right}.{quoted} LIMIT 1"
                    ).fetchone():
                        raise ValueError(
                            f"Source data changed in {table}; refusing to overwrite concurrent updates"
                        )
            conn.execute("PRAGMA defer_foreign_keys=ON")
            stage_schema = _schema(conn, "stage")
            for kind, name, _, sql in stage_schema:
                if kind != "table":
                    continue
                quoted = _quote(name)
                if name not in tables:
                    conn.execute(sql)
                else:
                    existing = {
                        row[1]
                        for row in conn.execute(f"PRAGMA main.table_info({quoted})")
                    }
                    for _, column, column_type, required, default, pk in conn.execute(
                        f"PRAGMA stage.table_info({quoted})"
                    ):
                        if column in existing:
                            continue
                        if pk:
                            raise ValueError("Unsupported primary-key migration")
                        declaration = (
                            column_type
                            + (" NOT NULL" if required else "")
                            + (f" DEFAULT {default}" if default is not None else "")
                        )
                        conn.execute(
                            f"ALTER TABLE {quoted} ADD COLUMN {_quote(column)} {declaration}"
                        )
                columns = ",".join(
                    _quote(row[1])
                    for row in conn.execute(f"PRAGMA stage.table_info({quoted})")
                )
                conn.execute(f"DELETE FROM main.{quoted}")
                conn.execute(
                    f"INSERT INTO main.{quoted}({columns}) SELECT {columns} FROM stage.{quoted}"
                )
            existing_names = {row[1] for row in _schema(conn)}
            for kind, name, _, sql in stage_schema:
                if kind == "index" and name not in existing_names:
                    conn.execute(sql)
            if conn.execute(
                "SELECT 1 FROM stage.sqlite_master WHERE name='sqlite_sequence'"
            ).fetchone():
                for table, sequence in conn.execute(
                    "SELECT name,seq FROM stage.sqlite_sequence"
                ).fetchall():
                    current = conn.execute(
                        "SELECT seq FROM main.sqlite_sequence WHERE name=?", (table,)
                    ).fetchone()
                    if current:
                        conn.execute(
                            "UPDATE main.sqlite_sequence SET seq=MAX(seq,?) WHERE name=?",
                            (sequence, table),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO main.sqlite_sequence(name,seq) VALUES(?,?)",
                            (table, sequence),
                        )
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Publication failed foreign-key validation")
    manifest.update(status="published", published_at=now())
    atomic_json(directory / "manifest.json", manifest)
    return {
        "published": True,
        "source": manifest["source"],
        "rollback_snapshot": str(directory / "baseline.db"),
    }


def run(directory, *, max_tasks=1000, rpm=15):
    """This function is only reached through the explicit run subcommand."""
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] == "published":
        raise ValueError("Published batches cannot be resumed")
    os.environ["MALODY_DB_PATH"] = str(directory / "data.db")
    os.environ["MALODY_COOKIES_FILE"] = str(ROOT / "data/cookies.local.json")
    # Defer crawler imports and all network activity until manual run.
    import requests
    from crawlers import rankings
    from crawlers.player_profile import PlayerProfileCrawler
    from crawlers.stb import STBCrawler
    from crawlers.ingestion import limit_session

    previous_signals = {
        sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    signal.signal(
        signal.SIGINT, lambda sig, frame: rankings.signal_handler(signal.SIGTERM, frame)
    )
    signal.signal(signal.SIGTERM, rankings.signal_handler)

    rankings.DatabaseManager().close_connection()
    rankings.DB_FILE = str(directory / "data.db")
    rankings.init_database()
    session = limit_session(requests.Session(), rpm)
    session.headers.update(rankings.HEADERS)
    session.cookies.update(rankings.COOKIES)
    charts = STBCrawler(session=session)
    charts.set_api_rate_limit(rpm)
    profiles = PlayerProfileCrawler(session=session)
    conn = charts.db_manager.get_connection()
    store = TaskStore(conn, "recrawl")
    manifest.update(status="running", started_at=now())
    atomic_json(directory / "manifest.json", manifest)
    processed = 0
    try:
        while (
            not max_tasks or processed < max_tasks
        ) and not rankings.is_stop_requested():
            feed_ranges(conn)
            claimed = store.claim(1)
            if not claimed:
                break
            kind, object_id, payload = claimed[0]
            try:
                state = "done"
                if kind == "player":
                    if not profiles.crawl_player_profile(object_id):
                        if getattr(profiles, "last_fetch_state", None) == "not_found":
                            state = "not_found"
                        else:
                            raise ValueError(
                                "Player incomplete; credentials or structure need checking"
                            )
                    else:
                        with atomic(conn):
                            store.add("mmr", object_id)
                elif kind == "song":
                    ids = charts.get_charts_from_song_page(int(object_id))
                    if not ids.complete:
                        raise ValueError(ids.error)
                    if ids.error == "not_found":
                        state = "not_found"
                    else:
                        info = charts._new_api_get(
                            "/community/song/info", {"sid": int(object_id)}
                        )
                        if (
                            info.get("code") != 0
                            or int(info.get("sid", 0)) != int(object_id)
                            or not info.get("title")
                        ):
                            raise ValueError("Song metadata incomplete")
                        song = {
                            "sid": int(object_id),
                            "title": info["title"],
                            "artist": info.get("artist"),
                            "title_org": info.get("titleOrg"),
                            "artist_org": info.get("artistOrg"),
                            "length": info.get("length"),
                            "bpm": info.get("bpm"),
                            "cover_url": info.get("cover"),
                            "last_updated": getattr(ids, "song_last_updated", None),
                            "crawl_time": now(),
                            "_source": "newapi",
                            "_complete": True,
                        }
                        song["_present"] = [
                            key for key, value in song.items() if value is not None
                        ]
                        song["_source_time"] = song["last_updated"]
                        with atomic(conn):
                            save_record(
                                conn,
                                "songs",
                                "sid",
                                int(object_id),
                                song,
                                {
                                    r[1]
                                    for r in conn.execute("PRAGMA table_info(songs)")
                                },
                                metadata_fields=(
                                    "title",
                                    "artist",
                                    "length",
                                    "bpm",
                                    "last_updated",
                                ),
                            )
                            for cid in ids:
                                store.add("chart", cid)
                elif kind == "chart":
                    charts.processed_charts.discard(int(object_id))
                    result = charts.crawl_chart_detail(int(object_id))
                    if charts.last_fetch_state == "not_found":
                        state = "not_found"
                    elif not result or charts.last_fetch_state == "partial":
                        raise ValueError("Chart metadata incomplete")
                    else:
                        with atomic(conn):
                            store.add("comments", object_id)
                            linked = conn.execute(
                                "SELECT sid FROM charts WHERE cid=?", (object_id,)
                            ).fetchone()
                            if linked:
                                store.add("song", linked[0])
                elif kind == "comments":
                    _, _, items = charts._build_chart_social_data(int(object_id))
                    with atomic(conn):
                        charts._save_chart_comments(
                            conn.cursor(), int(object_id), items, now()
                        )
                        if items.complete:
                            count = conn.execute(
                                "SELECT COUNT(*) FROM chart_comments WHERE cid=? AND is_current=1 AND is_recommend=0 AND is_not_recommend=0 AND (talk_type IS NULL OR talk_type!=1)",
                                (object_id,),
                            ).fetchone()[0]
                            conn.execute(
                                "UPDATE charts SET comment_count=? WHERE cid=?",
                                (count, object_id),
                            )
                    if not items.complete:
                        raise ValueError(items.error or "Partial comments")
                elif kind == "mmr":
                    rows = rankings.fetch_player_mmr_from_api(session, object_id)
                    if not getattr(rows, "complete", True):
                        raise ValueError("Partial MMR list")
                    for row in rows:
                        player_id = rankings.get_player_id_by_uid(object_id)
                        rankings.save_player_mmr_sample(
                            player_id,
                            object_id,
                            row["mode"],
                            row["mmr"],
                            row["mm_rank"],
                            row.get("name"),
                            datetime.now(),
                            "ranking_player_all",
                        )
                        if player_id is not None and row.get("rank"):
                            name = conn.execute(
                                "SELECT current_name FROM player_identity WHERE player_id=?",
                                (player_id,),
                            ).fetchone()[0]
                            rankings.save_player_ranking_record(
                                player_id,
                                object_id,
                                row["mode"],
                                row["rank"],
                                name,
                                row.get("lv"),
                                None,
                                row.get("acc"),
                                row.get("combo"),
                                row.get("pc"),
                                datetime.now(),
                                "newapi_ranking_player_all",
                            )
                elif kind == "ranking":
                    ranking, mode = object_id.split(":")
                    response = rankings._new_api_get(
                        session,
                        "/ranking/global",
                        {
                            "mode": int(mode),
                            "mm": int(ranking == "mm"),
                            "from": payload.get("offset", 0),
                        },
                    )
                    if (
                        response.get("code") != 0
                        or not isinstance(response.get("data"), list)
                        or "hasMore" not in response
                    ):
                        raise ValueError("Ranking page incomplete")
                    rows = response["data"]
                    if ranking == "mm":
                        result = rankings.save_mm_ranking_rows(
                            int(mode), rows, datetime.now(), "manual_recrawl"
                        )
                        if result["saved_rows"] != len(rows):
                            raise ValueError("Ranking page rejected rows")
                    else:
                        for row in rows:
                            pid = rankings.resolve_player_identity(
                                row["username"], datetime.now(), str(row["uid"])
                            )
                            if pid is None:
                                raise ValueError("Ranking identity conflict")
                            rankings.save_player_ranking_record(
                                pid,
                                str(row["uid"]),
                                int(mode),
                                row["rank"],
                                row["username"],
                                row.get("level"),
                                row.get("value"),
                                row.get("acc"),
                                row.get("combo"),
                                row.get("playcount"),
                                datetime.now(),
                                "newapi_ranking_global",
                            )
                    with atomic(conn):
                        for row in rows:
                            store.add("player", row["uid"])
                            store.add("mmr", row["uid"])
                    if response.get("hasMore"):
                        following = response.get("next")
                        if (
                            not rows
                            or not isinstance(following, int)
                            or following <= payload.get("offset", 0)
                        ):
                            raise ValueError("Ranking cursor stalled")
                        store.finish(
                            kind,
                            object_id,
                            state="pending",
                            payload={"offset": following},
                        )
                        processed += 1
                        continue
                else:
                    raise ValueError("Unknown task kind")
                store.finish(kind, object_id, state=state)
            except KeyboardInterrupt:
                store.finish(
                    kind, object_id, state="pending", error="operator interruption"
                )
                break
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                RuntimeError,
                sqlite3.Error,
            ) as exc:
                store.finish(kind, object_id, state="retry", error=str(exc))
                print(f"{kind} {object_id}: retry ({exc})", flush=True)
                if getattr(profiles, "auth_required_detected", False) or getattr(
                    charts, "auth_required_detected", False
                ):
                    manifest["status"] = "needs_credentials"
                    break
            processed += 1
    finally:
        if manifest["status"] != "needs_credentials":
            manifest["status"] = "ready" if status(directory)["complete"] else "pending"
        manifest["updated_at"] = now()
        atomic_json(directory / "manifest.json", manifest)
        session.close()
        rankings.DatabaseManager().close_connection()
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
    return status(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser(
        "prepare", help="Create an isolated batch; no network requests"
    )
    prepare_parser.add_argument(
        "--source-db", default=str(ROOT / "data/malody_rankings.db")
    )
    prepare_parser.add_argument("--directory", required=True)
    for name in ("uid", "sid", "cid"):
        prepare_parser.add_argument(f"--{name}-max", type=int)
    prepare_parser.add_argument(
        "--known-only",
        action="store_true",
        help="Explicitly limit discovery coverage to known IDs",
    )
    run_parser = sub.add_parser(
        "run", help="Explicitly start/resume requests against the isolated batch"
    )
    run_parser.add_argument("--directory", required=True)
    run_parser.add_argument(
        "--max-tasks",
        type=int,
        default=1000,
        help="0 means keep running until no ready work remains",
    )
    run_parser.add_argument("--rpm", type=int, default=15)
    status_parser = sub.add_parser(
        "status", help="Read progress without starting any requests"
    )
    status_parser.add_argument("--directory", required=True)
    for command in ("report", "publish"):
        item = sub.add_parser(
            command,
            help=(
                "Write coverage report"
                if command == "report"
                else "Manually publish a complete batch; rejects changed source data"
            ),
        )
        item.add_argument("--directory", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare(
            args.source_db,
            args.directory,
            uid_max=args.uid_max,
            sid_max=args.sid_max,
            cid_max=args.cid_max,
            known_only=args.known_only,
        )
    elif args.command == "run":
        if not 1 <= args.rpm <= 30 or args.max_tasks < 0:
            parser.error("rpm must be 1-30 and max-tasks nonnegative")
        result = run(args.directory, max_tasks=args.max_tasks, rpm=args.rpm)
    elif args.command == "report":
        result = report(args.directory)
    elif args.command == "publish":
        result = publish(args.directory)
    else:
        result = status(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
