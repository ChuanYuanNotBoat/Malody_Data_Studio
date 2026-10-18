"""Repair optional counters for a small batch of locally ranked charts."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawlers.chart_metrics import parse_chart_metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.getenv("MALODY_DB_PATH", str(ROOT / "data/malody_rankings.db")))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cid", type=int, action="append", help="Refresh a specific chart; can be repeated")
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--apply", action="store_true", help="Save verified values; otherwise preview only")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100 or args.interval < 1:
        parser.error("limit must be 1-100; interval must be at least 1 second")
    if args.cid and (len(args.cid) > 100 or any(cid <= 0 for cid in args.cid)):
        parser.error("provide at most 100 positive chart IDs")

    db_path = Path(args.db_path).resolve()
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if args.cid:
            placeholders = ",".join("?" for _ in args.cid)
            rows = conn.execute(f"""
                SELECT cid, heat, donate_count, play_count, data_hash FROM charts
                WHERE cid IN ({placeholders}) ORDER BY cid
            """, args.cid).fetchall()
        else:
            rows = conn.execute("""
                SELECT cid, heat, donate_count, play_count, data_hash FROM charts
                WHERE server_exists = 1
                ORDER BY COALESCE(recommend_count, 0) DESC, cid ASC LIMIT ?
            """, (args.limit,)).fetchall()
    updates = []
    failures = 0
    with requests.Session() as session:
        session.headers["User-Agent"] = "MalodyDataStudio/metrics-repair"
        for index, row in enumerate(rows):
            if index:
                time.sleep(args.interval)
            try:
                response = session.get(f"https://m.mugzone.net/chart/{row['cid']}", timeout=20)
                response.raise_for_status()
                metrics = parse_chart_metrics(response.text)
                if "donate_count" not in metrics:
                    raise ValueError("Donation counter not available; keeping stored values")
                # Older crawler versions never populated play_count, but wrote 0.
                # Keep an explicit observed zero, and preserve prior positive data.
                play = metrics.get("play_count", row["play_count"] or None)
                new = (metrics.get("heat", row["heat"]), metrics["donate_count"], play)
                updates.append((dict(row), new))
                print(f"CID {row['cid']}: donation {row['donate_count']} -> {new[1]}, play {row['play_count']} -> {play}", flush=True)
            except (requests.RequestException, ValueError) as exc:
                failures += 1
                print(f"CID {row['cid']}: skipped ({exc})", flush=True)

    if args.apply and updates:
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"chart_metrics_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        backup.write_text(json.dumps({
            "database": str(db_path), "fetched_at": datetime.now().isoformat(),
            "before": [row for row, new in updates],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        saved = 0
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=rw", uri=True)) as conn:
            with conn:
                for row, new in updates:
                    saved += conn.execute("""
                        UPDATE charts SET heat = ?, donate_count = ?, play_count = ?, data_hash = NULL
                        WHERE cid = ? AND heat IS ? AND donate_count IS ? AND play_count IS ? AND data_hash IS ?
                    """, (*new, row["cid"], row["heat"], row["donate_count"], row["play_count"], row["data_hash"])).rowcount
        print(f"Saved {saved}/{len(updates)} charts. Backup: {backup}")
        if saved != len(updates):
            print("Some charts changed during refresh and were skipped; rerun to refresh them.")
            return 1
    else:
        print(f"Preview: {len(updates)} charts; use --apply to save.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
