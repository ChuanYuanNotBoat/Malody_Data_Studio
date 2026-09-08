import queue
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

import malody_api.crawlers.rankings as rankings  # noqa: E402


class TestMalodyRankingsEdges(TestCase):
    def test_source_has_no_percent_logger_without_args(self):
        source = Path(rankings.__file__).read_text(encoding="utf-8")
        bad_calls = re.findall(r'logger\.(?:info|warning|error|exception)\(\".*%.*\"\)$', source, flags=re.MULTILINE)
        self.assertEqual(
            bad_calls,
            [],
            f"Found logger calls with % placeholders but no args: {bad_calls}",
        )

    def test_load_player_config_logs_count_with_format_args(self):
        with TemporaryDirectory() as tmpdir:
            players_file = Path(tmpdir) / "players.txt"
            players_file.write_text("# comment\n1001\n\n1002\n", encoding="utf-8")

            with patch.object(rankings, "PLAYER_CONFIG_FILE", str(players_file)), patch.object(
                rankings.logger, "info"
            ) as mock_info:
                players = rankings.load_player_config()

        self.assertEqual(players, ["1001", "1002"])
        mock_info.assert_called_once()
        self.assertEqual(mock_info.call_args.args[0], "Loaded %d players from config file.")
        self.assertEqual(mock_info.call_args.args[1], 2)

    def test_add_players_to_queue_deduplicates_and_logs_count_with_format_args(self):
        test_queue: queue.Queue[str] = queue.Queue()
        test_set: set[str] = set()
        with patch.object(rankings, "player_queue", test_queue), patch.object(rankings, "_player_set", test_set), patch.object(
            rankings.logger, "info"
        ) as mock_info:
            rankings.add_players_to_queue(["1001", "1001", "1002"])

        queued = []
        while True:
            try:
                queued.append(test_queue.get_nowait())
            except queue.Empty:
                break

        self.assertEqual(queued, ["1001", "1002"])
        mock_info.assert_called_once()
        self.assertEqual(mock_info.call_args.args[0], "Added %d new players into crawl queue.")
        self.assertEqual(mock_info.call_args.args[1], 2)

    def test_parse_player_list_item_top_pc_is_prefix_agnostic(self):
        html = """
        <div class="item-top">
          <i class="label top-1"></i>
          <span class="name"><a href="/accounts/user/1001">Alice</a></span>
          <span class="lv">Lv.20-12345</span>
          <span class="acc">Acc:99.52%</span>
          <span class="combo">Combo:456</span>
          <span class="pc">游玩次数: 1,234</span>
        </div>
        <div class="item-top">
          <i class="label top-2"></i>
          <span class="name"><a href="/accounts/user/1002">Bob</a></span>
          <span class="lv">Lv.18-9999</span>
          <span class="acc">Acc:98.00%</span>
          <span class="combo">Combo:123</span>
          <span class="pc">PC=2,048</span>
        </div>
        """

        rows = rankings.parse_player_list(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["pc"], 1234)
        self.assertEqual(rows[1]["pc"], 2048)

    def test_optimize_database_handles_large_duplicate_runs(self):
        with TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "malody_rankings.db"
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE player_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    uid TEXT,
                    mode INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    lv INTEGER,
                    exp INTEGER,
                    acc REAL,
                    combo INTEGER,
                    pc INTEGER,
                    crawl_time TEXT NOT NULL
                )
                """
            )

            rows = []
            for i in range(1205):
                rows.append(
                    (
                        1,
                        None,
                        0,
                        10,
                        "Alice",
                        20,
                        100000,
                        99.5,
                        1234,
                        5678,
                        f"2026-01-01T00:00:{i:02d}",
                    )
                )
            cursor.executemany(
                """
                INSERT INTO player_rankings
                (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            conn.close()

            with patch.object(rankings, "DB_FILE", str(db_file)), patch.object(rankings, "HAS_TQDM", False):
                rankings.DatabaseManager().close_connection()
                deleted = rankings.optimize_database()
                rankings.DatabaseManager().close_connection()

            check = sqlite3.connect(str(db_file))
            cur = check.cursor()
            cur.execute("SELECT COUNT(*) FROM player_rankings")
            remaining = cur.fetchone()[0]
            check.close()

        self.assertEqual(deleted, 1203)
        self.assertEqual(remaining, 2)

    def test_optimize_database_uses_same_core_as_save_logic_excluding_lv(self):
        with TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "malody_rankings.db"
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE player_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    uid TEXT,
                    mode INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    lv INTEGER,
                    exp INTEGER,
                    acc REAL,
                    combo INTEGER,
                    pc INTEGER,
                    crawl_time TEXT NOT NULL
                )
                """
            )

            # Same save-core payload (rank/name/exp/acc/combo/pc), only lv changes.
            cursor.executemany(
                """
                INSERT INTO player_rankings
                (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "1001", 0, 10, "Alice", 0, 100000, 99.5, 1234, 5678, "2026-01-01T00:00:01"),
                    (1, "1001", 0, 10, "Alice", 20, 100000, 99.5, 1234, 5678, "2026-01-01T00:00:02"),
                    (1, "1001", 0, 10, "Alice", 0, 100000, 99.5, 1234, 5678, "2026-01-01T00:00:03"),
                ],
            )
            conn.commit()
            conn.close()

            with patch.object(rankings, "DB_FILE", str(db_file)), patch.object(rankings, "HAS_TQDM", False):
                rankings.DatabaseManager().close_connection()
                deleted = rankings.optimize_database()
                rankings.DatabaseManager().close_connection()

            check = sqlite3.connect(str(db_file))
            cur = check.cursor()
            cur.execute("SELECT lv, crawl_time FROM player_rankings ORDER BY crawl_time ASC")
            rows = cur.fetchall()
            check.close()

        self.assertEqual(deleted, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], 20)
        self.assertEqual(rows[1][0], 20)

    def test_save_player_ranking_record_prevents_lv_zero_regression(self):
        with TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "malody_rankings.db"
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE player_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    uid TEXT,
                    mode INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    lv INTEGER,
                    exp INTEGER,
                    acc REAL,
                    combo INTEGER,
                    pc INTEGER,
                    crawl_time TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()

            with patch.object(rankings, "DB_FILE", str(db_file)):
                rankings.DatabaseManager().close_connection()

                op1 = rankings.save_player_ranking_record(
                    player_id=1,
                    uid="1001",
                    mode=0,
                    rank=10,
                    name="Alice",
                    lv=20,
                    exp=100000,
                    acc=99.5,
                    combo=1234,
                    pc=5678,
                    crawl_time=datetime.fromisoformat("2026-01-01T00:00:01"),
                    source="test",
                )
                op2 = rankings.save_player_ranking_record(
                    player_id=1,
                    uid="1001",
                    mode=0,
                    rank=10,
                    name="Alice",
                    lv=0,  # buggy regression value
                    exp=100000,
                    acc=99.5,
                    combo=1234,
                    pc=5678,
                    crawl_time=datetime.fromisoformat("2026-01-01T00:00:02"),
                    source="test",
                )
                op3 = rankings.save_player_ranking_record(
                    player_id=1,
                    uid="1001",
                    mode=0,
                    rank=10,
                    name="Alice",
                    lv=0,  # still buggy value
                    exp=100000,
                    acc=99.5,
                    combo=1234,
                    pc=5678,
                    crawl_time=datetime.fromisoformat("2026-01-01T00:00:03"),
                    source="test",
                )
                rankings.DatabaseManager().close_connection()

            check = sqlite3.connect(str(db_file))
            cur = check.cursor()
            cur.execute("SELECT lv FROM player_rankings ORDER BY crawl_time ASC")
            lvs = [r[0] for r in cur.fetchall()]
            check.close()

        self.assertEqual(op1, "new")
        self.assertEqual(op2, "same_insert")
        self.assertEqual(op3, "update")
        self.assertEqual(lvs, [20, 20])
