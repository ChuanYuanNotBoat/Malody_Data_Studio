#!/usr/bin/env python3
"""
Read-only analysis for MM ranking + MMR trend data quality and coverage.

This script never writes to the database.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ModeGapSummary:
    mode: int
    players: int
    expected_days: int
    present_days: int
    missing_days: int
    max_missing_days_for_one_player: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze MM/MMR data in read-only mode.")
    parser.add_argument("--db-path", default="data/malody_rankings.db", help="SQLite DB path")
    parser.add_argument("--players-file", default="players.txt", help="Manual tracked players file")
    parser.add_argument("--mm-limit", type=int, default=200, help="Top N MM players per mode for tracked set")
    parser.add_argument("--json", action="store_true", help="Output JSON-like blocks for easier parsing")
    return parser.parse_args()


def to_uri_path(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def connect_read_only(db_path: str) -> sqlite3.Connection:
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"database not found: {db}")
    conn = sqlite3.connect(to_uri_path(db), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def scalar(conn: sqlite3.Connection, sql: str, params: Tuple = ()) -> Optional[object]:
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def rows(conn: sqlite3.Connection, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def load_manual_players(players_file: str) -> Set[str]:
    path = Path(players_file)
    out: Set[str] = set()
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.isdigit():
            out.add(line)
    return out


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def print_kv(label: str, value: object):
    print(f"{label}: {value}")


def analyze_counts_and_freshness(conn: sqlite3.Connection):
    print("\n== Counts & Freshness ==")
    for table in [
        "player_rankings",
        "player_rankings_mm",
        "player_mmr_samples",
        "player_mmr_daily",
        "mm_crawl_status",
    ]:
        if table_exists(conn, table):
            cnt = scalar(conn, f"SELECT COUNT(*) FROM {table}")
            print_kv(f"{table}.count", cnt)

    if table_exists(conn, "player_rankings"):
        print_kv(
            "player_rankings.max_crawl_time",
            scalar(conn, "SELECT MAX(crawl_time) FROM player_rankings"),
        )
    if table_exists(conn, "player_rankings_mm"):
        print_kv(
            "player_rankings_mm.max_crawl_time",
            scalar(conn, "SELECT MAX(crawl_time) FROM player_rankings_mm"),
        )
    if table_exists(conn, "player_mmr_samples"):
        print_kv(
            "player_mmr_samples.max_crawl_time",
            scalar(conn, "SELECT MAX(crawl_time) FROM player_mmr_samples"),
        )
    if table_exists(conn, "player_mmr_daily"):
        print_kv(
            "player_mmr_daily.day_range",
            (
                scalar(conn, "SELECT MIN(day) FROM player_mmr_daily"),
                scalar(conn, "SELECT MAX(day) FROM player_mmr_daily"),
            ),
        )

    print_kv("analysis_time", iso_now())


def get_latest_mm_top_uids(conn: sqlite3.Connection, mm_limit: int) -> Set[str]:
    if not table_exists(conn, "player_rankings_mm"):
        return set()
    sql = """
    WITH latest AS (
        SELECT mode, MAX(crawl_time) AS ct
        FROM player_rankings_mm
        GROUP BY mode
    )
    SELECT DISTINCT r.uid
    FROM player_rankings_mm r
    JOIN latest l ON l.mode = r.mode AND l.ct = r.crawl_time
    WHERE r.rank <= ?
      AND r.uid IS NOT NULL
      AND r.uid != ''
    """
    result = rows(conn, sql, (mm_limit,))
    return {str(r[0]) for r in result}


def analyze_default_player_scope(conn: sqlite3.Connection, players_file: str, mm_limit: int):
    print("\n== Default Player Scope ==")
    manual = load_manual_players(players_file)
    top_mm = get_latest_mm_top_uids(conn, mm_limit=mm_limit)
    union_uids = manual | top_mm

    print_kv("manual_players_count", len(manual))
    print_kv("mm_top_players_count", len(top_mm))
    print_kv("union_players_count", len(union_uids))
    print_kv("manual_only_count", len(manual - top_mm))
    print_kv("mm_top_only_count", len(top_mm - manual))
    print_kv("overlap_count", len(manual & top_mm))
    if manual:
        print_kv("manual_players", ",".join(sorted(manual)))


def analyze_snapshot_integrity(conn: sqlite3.Connection, table: str, value_col: str):
    if not table_exists(conn, table):
        return
    print(f"\n== Latest Snapshot Integrity: {table} ==")
    base_sql = f"""
    WITH latest AS (
        SELECT mode, MAX(crawl_time) AS ct
        FROM {table}
        GROUP BY mode
    )
    SELECT r.mode,
           r.crawl_time,
           COUNT(*) AS rows_count,
           COUNT(DISTINCT r.uid) AS uid_distinct,
           COUNT(DISTINCT r.rank) AS rank_distinct,
           MIN(r.rank) AS min_rank,
           MAX(r.rank) AS max_rank,
           SUM(CASE WHEN r.rank <= 0 THEN 1 ELSE 0 END) AS invalid_rank_rows
    FROM {table} r
    JOIN latest l ON l.mode = r.mode AND l.ct = r.crawl_time
    GROUP BY r.mode, r.crawl_time
    ORDER BY r.mode
    """
    for r in rows(conn, base_sql):
        dup_rank = int(r["rows_count"]) - int(r["rank_distinct"])
        dup_uid = int(r["rows_count"]) - int(r["uid_distinct"])
        print(
            f"mode={r['mode']} time={r['crawl_time']} rows={r['rows_count']} "
            f"dup_rank={dup_rank} dup_uid={dup_uid} rank_range=[{r['min_rank']},{r['max_rank']}] "
            f"invalid_rank_rows={r['invalid_rank_rows']}"
        )

    # Optional value sanity
    if value_col:
        value_sql = f"""
        SELECT mode, MIN({value_col}) AS min_v, MAX({value_col}) AS max_v
        FROM {table}
        GROUP BY mode
        ORDER BY mode
        """
        for r in rows(conn, value_sql):
            print(f"value_range mode={r['mode']} min={r['min_v']} max={r['max_v']}")


def analyze_mmr_daily_gaps(conn: sqlite3.Connection) -> List[ModeGapSummary]:
    if not table_exists(conn, "player_mmr_daily"):
        return []
    sql = """
    SELECT mode, uid, COUNT(*) AS present_days, MIN(day) AS min_day, MAX(day) AS max_day
    FROM player_mmr_daily
    GROUP BY mode, uid
    """
    by_mode: Dict[int, Dict[str, int]] = {}
    for r in rows(conn, sql):
        mode = int(r["mode"])
        present = int(r["present_days"])
        min_day = datetime.strptime(r["min_day"], "%Y-%m-%d").date()
        max_day = datetime.strptime(r["max_day"], "%Y-%m-%d").date()
        expected = (max_day - min_day).days + 1
        missing = max(expected - present, 0)

        agg = by_mode.setdefault(
            mode,
            {
                "players": 0,
                "expected_days": 0,
                "present_days": 0,
                "missing_days": 0,
                "max_missing_days_for_one_player": 0,
            },
        )
        agg["players"] += 1
        agg["expected_days"] += expected
        agg["present_days"] += present
        agg["missing_days"] += missing
        if missing > agg["max_missing_days_for_one_player"]:
            agg["max_missing_days_for_one_player"] = missing

    out: List[ModeGapSummary] = []
    for mode in sorted(by_mode):
        agg = by_mode[mode]
        out.append(
            ModeGapSummary(
                mode=mode,
                players=agg["players"],
                expected_days=agg["expected_days"],
                present_days=agg["present_days"],
                missing_days=agg["missing_days"],
                max_missing_days_for_one_player=agg["max_missing_days_for_one_player"],
            )
        )
    return out


def analyze_mmr_daily(conn: sqlite3.Connection):
    if not table_exists(conn, "player_mmr_daily"):
        return
    print("\n== MMR Daily Coverage ==")
    sql = """
    SELECT mode,
           COUNT(*) AS rows_count,
           COUNT(DISTINCT uid) AS uid_count,
           MIN(day) AS min_day,
           MAX(day) AS max_day
    FROM player_mmr_daily
    GROUP BY mode
    ORDER BY mode
    """
    for r in rows(conn, sql):
        print(
            f"mode={r['mode']} rows={r['rows_count']} players={r['uid_count']} "
            f"day_range=[{r['min_day']},{r['max_day']}]"
        )

    gap_summary = analyze_mmr_daily_gaps(conn)
    print("\nMMR daily continuity (per-mode aggregated):")
    for s in gap_summary:
        ratio = (s.present_days / s.expected_days * 100.0) if s.expected_days else 0.0
        print(
            f"mode={s.mode} players={s.players} expected_days={s.expected_days} "
            f"present_days={s.present_days} missing_days={s.missing_days} "
            f"coverage={ratio:.2f}% max_missing_for_one_player={s.max_missing_days_for_one_player}"
        )


def analyze_mmr_samples(conn: sqlite3.Connection):
    if not table_exists(conn, "player_mmr_samples"):
        return
    print("\n== MMR Samples Quality ==")
    sql = """
    SELECT mode,
           COUNT(*) AS rows_count,
           COUNT(DISTINCT uid) AS uid_count,
           MIN(mmr) AS min_mmr,
           MAX(mmr) AS max_mmr,
           SUM(CASE WHEN mmr < 0 THEN 1 ELSE 0 END) AS invalid_mmr_rows
    FROM player_mmr_samples
    GROUP BY mode
    ORDER BY mode
    """
    for r in rows(conn, sql):
        print(
            f"mode={r['mode']} rows={r['rows_count']} players={r['uid_count']} "
            f"mmr_range=[{r['min_mmr']},{r['max_mmr']}] invalid_mmr_rows={r['invalid_mmr_rows']}"
        )

    dup_sql = """
    SELECT COUNT(*)
    FROM (
        SELECT uid, mode, crawl_time, COUNT(*) AS c
        FROM player_mmr_samples
        GROUP BY uid, mode, crawl_time
        HAVING c > 1
    ) x
    """
    print_kv("duplicate_(uid,mode,crawl_time)_groups", scalar(conn, dup_sql) or 0)


def analyze_crawl_status(conn: sqlite3.Connection):
    if not table_exists(conn, "mm_crawl_status"):
        return
    print("\n== MM Crawl Status ==")
    sql = """
    SELECT task, last_crawled, last_success, crawl_count, success_count, last_error
    FROM mm_crawl_status
    ORDER BY task
    """
    for r in rows(conn, sql):
        fail_count = int(r["crawl_count"] or 0) - int(r["success_count"] or 0)
        print(
            f"task={r['task']} crawled={r['last_crawled']} success={r['last_success']} "
            f"crawl_count={r['crawl_count']} fail_count={fail_count} last_error={r['last_error']}"
        )


def analyze_json_snapshot(conn: sqlite3.Connection, players_file: str, mm_limit: int):
    # Lightweight machine-readable block.
    manual = load_manual_players(players_file)
    top_mm = get_latest_mm_top_uids(conn, mm_limit=mm_limit)
    payload = {
        "manual_players_count": len(manual),
        "mm_top_players_count": len(top_mm),
        "union_players_count": len(manual | top_mm),
        "player_rankings_mm_count": scalar(conn, "SELECT COUNT(*) FROM player_rankings_mm")
        if table_exists(conn, "player_rankings_mm")
        else None,
        "player_mmr_samples_count": scalar(conn, "SELECT COUNT(*) FROM player_mmr_samples")
        if table_exists(conn, "player_mmr_samples")
        else None,
        "player_mmr_daily_count": scalar(conn, "SELECT COUNT(*) FROM player_mmr_daily")
        if table_exists(conn, "player_mmr_daily")
        else None,
        "analysis_time": iso_now(),
    }
    print("\n== JSON Snapshot ==")
    print(payload)


def main():
    args = parse_args()
    conn = connect_read_only(args.db_path)
    try:
        analyze_counts_and_freshness(conn)
        analyze_default_player_scope(conn, players_file=args.players_file, mm_limit=args.mm_limit)
        analyze_snapshot_integrity(conn, table="player_rankings", value_col="exp")
        analyze_snapshot_integrity(conn, table="player_rankings_mm", value_col="mm_value")
        analyze_mmr_samples(conn)
        analyze_mmr_daily(conn)
        analyze_crawl_status(conn)
        if args.json:
            analyze_json_snapshot(conn, players_file=args.players_file, mm_limit=args.mm_limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
