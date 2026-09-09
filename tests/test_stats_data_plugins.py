import io
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli.plugins import stb_stats_plugin, stb_summary_plugin, top_plugin  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return str(text)


def _separator() -> str:
    return "----"


def _terminal_width() -> int:
    return 120


def _db_safe_operation(func):
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    wrapper.__doc__ = getattr(func, "__doc__", None)
    return wrapper


class _SelectorStub:
    def __init__(self):
        self.current_mode = -1
        self.filters = {
            "modes": [],
            "players": [],
            "time_range": None,
        }

    def get_current_selection(self):
        return dict(self.filters)

    def set_filters(self, **kwargs):
        self.filters.update(kwargs)

    def build_chart_sql_where(self, alias):
        clauses = ["1=1"]
        params = []
        if self.filters["modes"]:
            placeholders = ",".join("?" for _ in self.filters["modes"])
            clauses.append(f"{alias}.mode IN ({placeholders})")
            params.extend(self.filters["modes"])
        if self.filters["players"]:
            placeholders = ",".join("?" for _ in self.filters["players"])
            clauses.append(f"{alias}.stabled_by_name IN ({placeholders})")
            params.extend(self.filters["players"])
        if self.filters["time_range"]:
            clauses.append(f"{alias}.last_updated BETWEEN ? AND ?")
            params.extend([self.filters["time_range"]["start"], self.filters["time_range"]["end"]])
        return " AND ".join(clauses), params

    def build_player_sql_where(self, alias):
        clauses = ["1=1"]
        params = []
        if self.filters["modes"]:
            placeholders = ",".join("?" for _ in self.filters["modes"])
            clauses.append(f"{alias}.mode IN ({placeholders})")
            params.extend(self.filters["modes"])
        elif self.current_mode != -1:
            clauses.append(f"{alias}.mode = ?")
            params.append(self.current_mode)
        if self.filters["players"]:
            placeholders = ",".join("?" for _ in self.filters["players"])
            clauses.append(f"{alias}.name IN ({placeholders})")
            params.extend(self.filters["players"])
        if self.filters["time_range"]:
            clauses.append(f"{alias}.crawl_time BETWEEN ? AND ?")
            params.extend([self.filters["time_range"]["start"], self.filters["time_range"]["end"]])
        return " AND ".join(clauses), params


class _DataShellStub:
    def __init__(self, conn, output_dir):
        self.conn = conn
        self.selector = _SelectorStub()
        self.current_mode = -1
        self.mode_names = {-1: "All", 0: "Key", 1: "Step", 3: "Catch"}
        self.output_dir = output_dir

    def get_unique_filename(self, base, ext):
        return f"{Path(base).stem}.{ext}"


class TestStatsDataPlugins(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(
            RED="RED",
            YELLOW="YELLOW",
            GREEN="GREEN",
            CYAN="CYAN",
            BLUE="BLUE",
            BOLD="BOLD",
            MAGENTA="MAGENTA",
            WHITE="WHITE",
        )
        stb_stats_plugin.install(
            _DataShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
            get_separator=_separator,
        )
        stb_summary_plugin.install(
            _DataShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
            get_separator=_separator,
        )
        top_plugin.install(
            _DataShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
            get_separator=_separator,
            get_terminal_width=_terminal_width,
        )

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.conn = sqlite3.connect(":memory:")
        self._create_schema()
        self._seed_data()
        self.shell = _DataShellStub(self.conn, self.tempdir.name)

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _create_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE charts (
                cid INTEGER PRIMARY KEY,
                sid INTEGER,
                level TEXT,
                status INTEGER,
                creator_name TEXT,
                stabled_by_name TEXT,
                heat REAL,
                donate_count INTEGER,
                last_updated TEXT,
                mode INTEGER,
                server_exists INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE player_rankings (
                mode INTEGER,
                rank INTEGER,
                name TEXT,
                lv INTEGER,
                exp INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                crawl_time TEXT
            );
            CREATE TABLE player_rankings_mm (
                mode INTEGER,
                rank INTEGER,
                name TEXT,
                lv INTEGER,
                mm_value INTEGER,
                acc REAL,
                combo INTEGER,
                pc INTEGER,
                crawl_time TEXT
            );
            """
        )
        self.conn.commit()

    def _seed_data(self):
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT INTO charts
            (cid, sid, level, status, creator_name, stabled_by_name, heat, donate_count, last_updated, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, 10, "12", 2, "Creator A", "Alice", 5, 1, "2026-01-01", 3),
                (2, 10, "13", 1, "Creator A", "Alice", 20, 3, "2026-02-01", 3),
                (3, 11, "9", 0, "Creator B", "Bob", 0, 0, "2026-02-15", 1),
                (4, 12, None, 2, None, "Carol", 80, 5, "2026-03-01", 3),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings
            (mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (3, 1, "Alice", 20, 2000, 99.5, 300, 10, "2026-03-01"),
                (3, 2, "Bob", 19, 1800, 98.1, 250, 8, "2026-03-01"),
                (1, 1, "Carol", 18, 1700, 97.2, 230, 7, "2026-03-01"),
                (3, 3, "VeryLongPlayerNameForTruncation", 18, 1600, 97.0, 220, 6, "2026-03-01"),
                (3, 1, "Alice", 19, 1900, 99.0, 280, 9, "2026-02-01"),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO player_rankings_mm
            (mode, rank, name, lv, mm_value, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (3, 1, "Alice", 20, 12345, 99.5, 300, 10, "2026-03-01"),
                (3, 2, "Bob", 19, 11200, 98.1, 250, 8, "2026-03-01"),
                (1, 1, "Carol", 18, 9800, 97.2, 230, 7, "2026-03-01"),
                (3, 1, "Alice", 19, 12000, 99.0, 280, 9, "2026-02-01"),
            ],
        )
        self.conn.commit()

    def test_stb_stats_reports_invalid_mode_argument(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_stb_stats("abc")

        self.assertIn("模式", stdout.getvalue())

    def test_stb_stats_uses_current_mode_when_selector_has_no_mode_filter(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_stb_stats("")

        output = stdout.getvalue()
        self.assertIn("总谱面数", output)
        self.assertIn("3", output)
        self.assertIn("Creator A", output)

    def test_stb_stats_shows_empty_message_when_no_rows_match(self):
        self.shell.selector.set_filters(players=["Nobody"])

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_stb_stats("")

        self.assertIn("没有", stdout.getvalue())

    def test_get_chart_stats_returns_safe_defaults_on_query_error(self):
        cursor = self.conn.cursor()

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            stats = self.shell._get_chart_stats(cursor, "bad sql", [])

        self.assertEqual(stats["total_charts"], 0)
        self.assertEqual(stats["status_dist"], {0: 0, 1: 0, 2: 0})
        self.assertIn("出错", stdout.getvalue())

    def test_stb_summary_basic_report_runs(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_stb_summary("basic 3")

        output = stdout.getvalue()
        self.assertIn("综合统计", output)
        self.assertIn("总谱面数", output)
        self.assertIn("状态分布", output)

    def test_stb_summary_detailed_can_skip_chart_generation(self):
        with patch("builtins.input", return_value="n"), patch.object(
            self.shell, "_generate_summary_charts"
        ) as generate_mock, patch("sys.stdout", new_callable=io.StringIO):
            self.shell.do_stb_summary("3 detailed")

        generate_mock.assert_not_called()

    def test_stb_summary_detailed_can_generate_chart(self):
        with patch("builtins.input", return_value="y"), patch.object(
            self.shell, "_generate_summary_charts"
        ) as generate_mock, patch("sys.stdout", new_callable=io.StringIO):
            self.shell.do_stb_summary("3 detailed")

        generate_mock.assert_called_once()

    def test_get_comprehensive_stats_detailed_contains_expected_sections(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3

        stats = self.shell._get_comprehensive_stats(self.conn.cursor(), 3, "detailed")

        self.assertEqual(stats["total_charts"], 3)
        self.assertEqual(stats["unique_songs"], 2)
        self.assertIn("top_creators", stats)
        self.assertIn("monthly_updates", stats)
        self.assertEqual(stats["high_heat"], 1)

    def test_generate_summary_charts_saves_file(self):
        stats = {
            "status_dist": {0: 1, 1: 1, 2: 2},
            "zero_heat": 1,
            "low_heat": 1,
            "medium_heat": 1,
            "high_heat": 1,
            "level_breakdown": [("9", 1), ("12", 1)],
            "top_creators": [("Creator A", 2), ("Creator B", 1)],
        }

        self.shell._generate_summary_charts(stats, 3)

        self.assertTrue((Path(self.tempdir.name) / "stb_summary_mode3.png").exists())

    def test_top_rejects_invalid_limit_inputs(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("0")
            self.shell.do_top("abc")

        output = stdout.getvalue()
        self.assertIn("数量", output)

    def test_top_reports_when_no_data_exists(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM player_rankings")
        self.conn.commit()

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("")

        self.assertIn("没有找到数据", stdout.getvalue())

    def test_top_ignores_player_filter_and_uses_latest_snapshot(self):
        self.shell.selector.set_filters(players=["Nobody"])
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("5")

        output = stdout.getvalue()
        self.assertIn("Alice", output)
        self.assertIn("Bob", output)
        self.assertIn("2026-03-01", output)
        self.assertNotIn("2026-02-01", output)

    def test_top_respects_explicit_time_range_and_mode_filters(self):
        self.shell.selector.set_filters(
            modes=[3],
            time_range={"start": "2026-02-01", "end": "2026-02-01"},
        )

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("5")

        output = stdout.getvalue()
        self.assertIn("Alice", output)
        self.assertNotIn("Bob", output)

    def test_top_supports_mm_rank_type(self):
        self.shell.current_mode = 3
        self.shell.selector.current_mode = 3
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("5 mm")

        output = stdout.getvalue()
        self.assertIn("顶级玩家排名 (mm)", output)
        self.assertIn("MM", output)
        self.assertIn("Alice", output)


    def test_top_mm_reports_missing_table_gracefully(self):
        cursor = self.conn.cursor()
        cursor.execute("DROP TABLE player_rankings_mm")
        self.conn.commit()

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("5 mm")

        self.assertIn("player_rankings_mm", stdout.getvalue())

    def test_top_with_time_range_uses_latest_snapshot_within_range(self):
        self.shell.selector.set_filters(
            modes=[3],
            time_range={"start": "2026-02-01", "end": "2026-03-01"},
        )

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("10")

        output = stdout.getvalue()
        self.assertIn("2026-03-01", output)
        self.assertIn("Alice", output)
        self.assertIn("Bob", output)
        self.assertEqual(output.count("Alice"), 1)

    def test_top_caps_large_limit_to_avoid_spam(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.shell.do_top("500")

        output = stdout.getvalue()
        self.assertIn("200", output)
