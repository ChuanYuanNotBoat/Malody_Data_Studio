import io
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli.plugins import history_plugin, player_plugin, profile_plugin, search_plugin  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return str(text)


def _separator() -> str:
    return "----"


def _db_safe_operation(func):
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    wrapper.__doc__ = getattr(func, "__doc__", None)
    return wrapper


class _SelectorStub:
    def __init__(self):
        self.current_mode = -1
        self.filters = {"players": [], "difficulties": [], "time_range": None, "modes": [], "statuses": []}

    def build_player_sql_where(self, alias):
        clauses = ["1=1"]
        params = []
        if self.filters["time_range"]:
            clauses.append(f"{alias}.crawl_time BETWEEN ? AND ?")
            params.extend([self.filters["time_range"]["start"], self.filters["time_range"]["end"]])
        if self.filters["modes"]:
            placeholders = ",".join("?" for _ in self.filters["modes"])
            clauses.append(f"{alias}.mode IN ({placeholders})")
            params.extend(self.filters["modes"])
        elif self.current_mode != -1:
            clauses.append(f"{alias}.mode = ?")
            params.append(self.current_mode)
        return " AND ".join(clauses), params

    def build_chart_sql_where(self, alias):
        clauses = ["1=1"]
        params = []
        if self.filters["modes"]:
            placeholders = ",".join("?" for _ in self.filters["modes"])
            clauses.append(f"{alias}.mode IN ({placeholders})")
            params.extend(self.filters["modes"])
        elif self.current_mode != -1:
            clauses.append(f"{alias}.mode = ?")
            params.append(self.current_mode)
        return " AND ".join(clauses), params

    def get_current_selection(self):
        return str(self.filters)


class _UserShellStub:
    def __init__(self, conn, output_dir):
        self.conn = conn
        self.output_dir = output_dir
        self.selector = _SelectorStub()
        self.current_mode = 3
        self.mode_names = {-1: "All", 1: "Step", 3: "Catch"}

    def get_unique_filename(self, base, ext):
        return f"{Path(base).stem}.{ext}"


class TestStatsUserPlugins(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(
            RED="RED",
            YELLOW="YELLOW",
            GREEN="GREEN",
            CYAN="CYAN",
            BOLD="BOLD",
        )
        player_plugin.install(_UserShellStub, colorize=_colorize, colors=colors, db_safe_operation=_db_safe_operation, get_separator=_separator)
        profile_plugin.install(_UserShellStub, colorize=_colorize, colors=colors, db_safe_operation=_db_safe_operation)
        history_plugin.install(_UserShellStub, colorize=_colorize, colors=colors, db_safe_operation=_db_safe_operation, get_separator=_separator)
        search_plugin.install(_UserShellStub, colorize=_colorize, colors=colors, db_safe_operation=_db_safe_operation, get_separator=_separator)

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        self._create_schema()
        self._seed_data()
        self.shell = _UserShellStub(self.conn, self.tempdir.name)

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _create_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE player_identity (
                player_id INTEGER,
                uid INTEGER,
                current_name TEXT
            );
            CREATE TABLE player_aliases (
                player_id INTEGER,
                alias TEXT
            );
            CREATE TABLE player_rankings (
                player_id INTEGER,
                mode INTEGER,
                rank INTEGER,
                name TEXT,
                lv INTEGER,
                exp INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                crawl_time timestamp
            );
            CREATE TABLE player_rankings_mm (
                player_id INTEGER,
                mode INTEGER,
                rank INTEGER,
                name TEXT,
                lv INTEGER,
                mm_value INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                crawl_time timestamp
            );
            CREATE TABLE player_mmr_daily (
                uid INTEGER,
                mode INTEGER,
                day TEXT,
                mmr INTEGER,
                mm_rank INTEGER,
                sample_time timestamp
            );
            CREATE TABLE player_profiles (
                uid INTEGER,
                avatar_url TEXT,
                join_date TEXT,
                bio TEXT
            );
            CREATE TABLE player_titles (
                uid INTEGER,
                title TEXT
            );
            CREATE TABLE player_achievements (
                uid INTEGER,
                achievement_code INTEGER
            );
            CREATE TABLE songs (
                sid INTEGER,
                title TEXT,
                artist TEXT
            );
            CREATE TABLE charts (
                cid INTEGER,
                sid INTEGER,
                version TEXT,
                level TEXT,
                status INTEGER,
                creator_name TEXT,
                heat REAL,
                donate_count INTEGER,
                last_updated TEXT,
                mode INTEGER,
                server_exists INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        self.conn.commit()

    def _seed_data(self):
        cursor = self.conn.cursor()
        cursor.executemany(
            "INSERT INTO player_identity (player_id, uid, current_name) VALUES (?, ?, ?)",
            [(1, 1001, "Alice"), (2, 1002, "Bob")],
        )
        cursor.executemany(
            "INSERT INTO player_aliases (player_id, alias) VALUES (?, ?)",
            [(1, "Alicia"), (2, "Bobby")],
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings
            (player_id, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 3, 1, "Alice", 20, 2000, 99.5, 300, 10, datetime(2026, 4, 1)),
                (1, 1, 5, "Alice", 18, 1500, 98.0, 220, 8, datetime(2026, 4, 1)),
                (1, 3, 2, "Alice", 19, 1800, 99.0, 280, 9, datetime(2026, 3, 1)),
                (2, 3, 2, "Bob", 18, 1700, 97.2, 240, 7, datetime(2026, 4, 1)),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings_mm
            (player_id, mode, rank, name, lv, mm_value, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 3, 1, "Alice", 20, 12345, 99.5, 300, 10, datetime(2026, 4, 1)),
                (1, 1, 4, "Alice", 18, 9800, 98.0, 220, 8, datetime(2026, 4, 1)),
                (1, 3, 2, "Alice", 19, 12000, 99.0, 280, 9, datetime(2026, 3, 1)),
                (2, 3, 2, "Bob", 18, 11000, 97.2, 240, 7, datetime(2026, 4, 1)),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_mmr_daily
            (uid, mode, day, mmr, mm_rank, sample_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1001, 0, "2026-04-01", 5679, 12155, datetime(2026, 4, 1)),
                (1001, 3, "2026-03-30", 12100, 2, datetime(2026, 3, 30)),
                (1001, 3, "2026-04-01", 12345, 1, datetime(2026, 4, 1)),
            ],
        )
        cursor.execute("INSERT INTO player_profiles (uid, avatar_url, join_date, bio) VALUES (?, ?, ?, ?)", (1001, "https://avatar", "2025-01-01", "hello"))
        cursor.execute("INSERT INTO player_titles (uid, title) VALUES (?, ?)", (1001, "Champion"))
        cursor.execute("INSERT INTO player_achievements (uid, achievement_code) VALUES (?, ?)", (1001, 101))
        cursor.executemany(
            "INSERT INTO songs (sid, title, artist) VALUES (?, ?, ?)",
            [(10, "Catch Song", "Artist A"), (11, "Step Song", "Artist B")],
        )
        cursor.executemany(
            """
            INSERT INTO charts
            (cid, sid, version, level, status, creator_name, heat, donate_count, last_updated, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (101, 10, "MX", "12", 2, "Creator A", 25, 3, "2026-04-01", 3),
                (102, 11, "HD", "9", 2, "Creator A", 8, 1, "2026-04-01", 1),
            ],
        )
        self.conn.commit()

    def test_player_supports_current_name_lookup(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alice 3")

        output = stdout.getvalue()
        self.assertIn("Alice", output)
        self.assertIn("排名", output)
        self.assertIn("MM", output)

    def test_player_supports_alias_lookup(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alicia 3")

        self.assertIn("Alicia", stdout.getvalue())

    def test_player_supports_mm_rank_type_lookup(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alice 3 mm")

        output = stdout.getvalue()
        self.assertIn("Alice", output)
        self.assertIn("MM:", output)

    def test_player_mm_auto_mode_prefers_mm_table_when_current_mode_is_all(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM player_rankings_mm WHERE player_id = 1 AND mode = 1")
        cursor.execute(
            """
            INSERT INTO player_rankings
            (player_id, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 3, "Alice", 21, 2200, 99.6, 320, 11, datetime(2026, 5, 1)),
        )
        self.conn.commit()

        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alice mm")

        output = stdout.getvalue()
        self.assertIn("MM:", output)
        self.assertIn("12345", output)

    def test_player_mm_auto_mode_respects_selector_mode_filter(self):
        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        self.shell.selector.filters["modes"] = [1]
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alice mm")

        output = stdout.getvalue()
        self.assertIn("MM:", output)
        self.assertIn("9800", output)
        self.assertNotIn("12345", output)

    def test_player_all_does_not_show_mm_value_as_exp_when_exp_missing(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM player_rankings WHERE player_id = 1 AND mode = 3")
        self.conn.commit()

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_player("Alice 3")

        output = stdout.getvalue()
        self.assertIn("经验: N/A", output)
        self.assertIn("MM: 12345", output)

    def test_profile_supports_current_name_without_separator_error(self):
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_profile("Alice 3")

        output = stdout.getvalue()
        self.assertIn("详细资料", output)
        self.assertIn("Champion", output)

    def test_profile_all_modes_includes_mm_and_sorts_by_exp_desc(self):
        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_profile("Alice")

        output = stdout.getvalue()
        self.assertIn("各模式最新排名", output)
        self.assertIn("EXP", output)
        self.assertIn("MM", output)
        pos_mode3 = output.find("模式 3(")
        pos_mode1 = output.find("模式 1(")
        self.assertNotEqual(pos_mode3, -1)
        self.assertNotEqual(pos_mode1, -1)
        self.assertLess(pos_mode3, pos_mode1)
        self.assertIn("模式 0(", output)
        self.assertIn("MMR 5679", output)

    def test_profile_mmr_fallback_uses_latest_sample_time_on_same_day(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO player_mmr_daily
            (uid, mode, day, mmr, mm_rank, sample_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1001, 0, "2026-04-01", 6000, 12000, datetime(2026, 4, 1, 12, 0, 0)),
        )
        self.conn.commit()

        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_profile("Alice")

        output = stdout.getvalue()
        self.assertIn("模式 0(", output)
        self.assertIn("MMR 6000", output)

    def test_history_supports_uid_lookup_and_generates_chart(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_history("1001 3 60")

        output = stdout.getvalue()
        self.assertIn("已生成", output)
        self.assertTrue((Path(self.tempdir.name) / "player_history_1001_mode3.png").exists())

    def test_history_supports_mm_rank_metric(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_history("1001 3 60 mm_rank")

        output = stdout.getvalue()
        self.assertIn("已生成", output)
        self.assertTrue((Path(self.tempdir.name) / "player_history_1001_mode3_mm_rank.png").exists())

    def test_history_supports_mmr_metric(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_history("1001 3 60 mmr")

        output = stdout.getvalue()
        self.assertIn("MMR", output)
        self.assertTrue((Path(self.tempdir.name) / "player_history_1001_mode3_mmr.png").exists())

    def test_history_auto_mode_for_mmr_is_deterministic_when_timestamps_tie(self):
        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        with patch("sys.stdout", new_callable=io.StringIO):
            self.shell.do_history("1001 mmr")

        self.assertTrue((Path(self.tempdir.name) / "player_history_1001_mode0_mmr.png").exists())

    def test_history_auto_mode_respects_selector_mode_filter(self):
        self.shell.current_mode = -1
        self.shell.selector.current_mode = -1
        self.shell.selector.filters["modes"] = [3]
        with patch("sys.stdout", new_callable=io.StringIO):
            self.shell.do_history("1001 mmr")

        self.assertTrue((Path(self.tempdir.name) / "player_history_1001_mode3_mmr.png").exists())

    def test_search_player_supports_alias_keyword(self):
        self.shell.selector.current_mode = -1
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_search("Alicia player")

        output = stdout.getvalue()
        self.assertIn("Alice", output)

    def test_search_player_mode_argument_overrides_current_mode(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_search("Alice player 1")

        output = stdout.getvalue()
        self.assertIn("等级 18", output)
        self.assertNotIn("等级 20", output)

    def test_search_chart_mode_argument_overrides_current_mode(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_search("Step chart 1")

        output = stdout.getvalue()
        self.assertIn("Step Song", output)
        self.assertNotIn("Catch Song", output)

    def test_search_creator_mode_argument_overrides_current_mode(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_search("Creator creator 1")

        output = stdout.getvalue()
        self.assertIn("Creator A", output)
        self.assertIn("1 个谱面", output)
