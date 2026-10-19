"""Backfill explicit negative vote events and selected official dislike totals."""

import argparse
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawlers.chart_votes import classify_chart_vote, nonnegative_count


def plan_backfill(conn):
    """Only an explicit message prefix is evidence of vote direction."""
    conn.row_factory = sqlite3.Row
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chart_comments)")}
    negative_column = "is_not_recommend" if "is_not_recommend" in columns else "0 AS is_not_recommend"
    rows = conn.execute(f"SELECT tid, cid, content, is_recommend, {negative_column} FROM chart_comments").fetchall()
    changes = []
    for row in rows:
        direction = classify_chart_vote(dict(row))
        if direction is None:
            continue
        flags = (int(direction == "recommend"), int(direction == "not_recommend"))
        if flags != (row["is_recommend"], row["is_not_recommend"]):
            changes.append((dict(row), flags))
    return changes


def apply_backfill(conn, changes, totals):
    """Call inside a transaction, after writing a backup of the previous flags."""
    chart_columns = {row[1] for row in conn.execute("PRAGMA table_info(charts)")}
    comment_columns = {row[1] for row in conn.execute("PRAGMA table_info(chart_comments)")}
    if "not_recommend_count" not in chart_columns:
        conn.execute("ALTER TABLE charts ADD COLUMN not_recommend_count INTEGER DEFAULT NULL")
    if "is_not_recommend" not in comment_columns:
        conn.execute("ALTER TABLE chart_comments ADD COLUMN is_not_recommend INTEGER NOT NULL DEFAULT 0")
    saved_events = 0
    affected_cids = set()
    for row, flags in changes:
        result = conn.execute("""
            UPDATE chart_comments SET is_recommend=?,is_not_recommend=?
            WHERE tid=? AND content IS ? AND is_recommend IS ? AND is_not_recommend IS ?
        """, (*flags, row["tid"], row["content"], row["is_recommend"], row["is_not_recommend"]))
        saved_events += result.rowcount
        if result.rowcount:
            affected_cids.add(row["cid"])
    saved_totals = 0
    for cid, count in totals.items():
        count = nonnegative_count(count)
        if count is not None:
            saved_totals += conn.execute(
                "UPDATE charts SET not_recommend_count=?,data_hash=NULL WHERE cid=?",
                (count, cid),
            ).rowcount
    # Direction corrections change future event-based aggregates; force a fresh
    # comparison without guessing which legacy total came from API versus talk.
    for cid in affected_cids:
        conn.execute("UPDATE charts SET data_hash=NULL WHERE cid=?", (cid,))
    return saved_events, saved_totals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.getenv("MALODY_DB_PATH", str(ROOT / "data/malody_rankings.db")))
    parser.add_argument("--cids", type=int, nargs="*", default=[])
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.interval < 1 or len(args.cids) > 100 or any(cid <= 0 for cid in args.cids):
        parser.error("Use at most 100 positive CIDs and an interval of at least 1 second")
    path = Path(args.db_path).resolve()
    totals = {}
    if args.cids:
        import requests
        from crawlers.rankings import _new_api_get
        with requests.Session() as session:
            for index, cid in enumerate(dict.fromkeys(args.cids)):
                if index:
                    time.sleep(args.interval)
                payload = _new_api_get(session, "/community/chart/info", {"cid": cid})
                count = nonnegative_count(payload.get("dislike"))
                if payload.get("code") != 0 or payload.get("cid") != cid or count is None:
                    raise RuntimeError(f"CID {cid}: no authoritative dislike count; nothing saved")
                totals[cid] = count
                print(f"CID {cid}: official not_recommend_count={count}", flush=True)

    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        changes = plan_backfill(conn)
        chart_columns = [row[1] for row in conn.execute("PRAGMA table_info(charts)")]
        comment_columns = [row[1] for row in conn.execute("PRAGMA table_info(chart_comments)")]
        before_totals = []
        for cid in totals:
            column = "not_recommend_count" if "not_recommend_count" in chart_columns else "NULL AS not_recommend_count"
            before_totals.extend(dict(row) for row in conn.execute(
                f"SELECT cid, data_hash, {column} FROM charts WHERE cid=?", (cid,)))
    print(f"Direction corrections: {len(changes)}; official totals: {len(totals)}")
    if not args.apply:
        print("Preview only; use --apply to save.")
        return 0

    backup_dir = ROOT / "logs/not_recommend_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"before_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    backup.write_text(json.dumps({
        "database": str(path), "chart_columns": chart_columns, "comment_columns": comment_columns,
        "comments": [{k: row[k] for k in ("tid", "cid", "is_recommend", "is_not_recommend")} for row, _ in changes],
        "charts": before_totals,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            saved_events, saved_totals = apply_backfill(conn, changes, totals)
    print(f"Saved {saved_events} event corrections and {saved_totals} official totals. Backup: {backup}")
    return 0 if saved_events == len(changes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
