import io
import re
import sqlite3
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import TestCase

from cli.selector import MCSelector
from stats_cli.plugins import stb_hot_plugin


class _Shell:
    pass


class TestStbHot(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(RED="", YELLOW="", CYAN="", WHITE="", BOLD="")
        stb_hot_plugin.install(
            _Shell,
            colorize=lambda text, color: text,
            colors=colors,
            db_safe_operation=lambda func: func,
            get_separator=lambda: "----",
        )

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            CREATE TABLE songs (sid INTEGER PRIMARY KEY, title TEXT, artist TEXT);
            CREATE TABLE charts (
                cid INTEGER PRIMARY KEY, sid INTEGER, version TEXT, level TEXT,
                status INTEGER, mode INTEGER, creator_name TEXT, stabled_by_name TEXT,
                heat INTEGER, donate_count INTEGER, play_count INTEGER,
                last_updated TEXT, server_exists INTEGER, recommend_count INTEGER
            );
            INSERT INTO songs VALUES (1, 'Song', 'Artist');
        """)
        self.conn.executemany("""
            INSERT INTO charts VALUES (?, 1, 'Hard', '10', ?, ?, 'Creator', NULL,
                ?, 0, 0, '2026-10-01', ?, ?)
        """, [
            (10, 2, 0, 100, 1, 3),
            (20, 2, 3, 10, 1, 50),
            (30, 1, 0, 20, 0, 50),
            (40, 2, 0, 30, 1, None),
            (50, 2, 0, 40, 1, 0),
        ])
        self.shell = _Shell()
        self.shell.conn = self.conn
        self.shell.selector = MCSelector()
        self.shell.current_mode = -1
        self.shell.mode_names = {-1: "All", 0: "Key", 3: "Catch"}

    def run_command(self, arg):
        output = io.StringIO()
        with redirect_stdout(output):
            self.shell.do_stb_hot(arg)
        text = output.getvalue()
        return [int(cid) for cid in re.findall(r"CID: (\d+)", text)], text

    def test_recommend_descending_with_limit_and_deleted_marker(self):
        cids, output = self.run_command("-1 recommend_count 3")
        self.assertEqual(cids, [20, 30, 10])
        self.assertIn("推荐数降序", output)
        self.assertIn("推荐: 50", output)
        self.assertIn("*Song", output)

    def test_null_recommendations_sort_as_zero_with_stable_ties(self):
        cids, output = self.run_command("recommend_count")
        self.assertEqual(cids, [20, 30, 10, 40, 50])
        self.assertIn("推荐: 0", output)

    def test_explicit_mode_overrides_current_without_changing_selector(self):
        self.shell.current_mode = 0
        self.shell.selector.current_mode = 0
        cids, output = self.run_command("3 recommend_count 10")
        self.assertEqual(cids, [20])
        self.assertIn("3(Catch)", output)
        self.assertEqual(self.shell.selector.current_mode, 0)

    def test_explicit_all_modes_overrides_current(self):
        self.shell.current_mode = 0
        self.shell.selector.current_mode = 0
        self.assertEqual(self.run_command("-1 recommend_count 2")[0], [20, 30])

    def test_current_mode_and_selector_filters(self):
        self.shell.current_mode = 0
        self.shell.selector.current_mode = 0
        self.assertEqual(self.run_command("recommend_count")[0], [30, 10, 40, 50])
        self.shell.selector.set_filters(modes=[3], statuses=[2])
        self.assertEqual(self.run_command("0 recommend_count 10")[0], [20])
        self.shell.selector.set_filters(statuses=[0])
        self.assertIn("没有找到", self.run_command("recommend_count")[1])

    def test_existing_heat_sort_remains_default(self):
        self.assertEqual(self.run_command("")[0], [10, 50, 40, 30, 20])

    def test_missing_counters_are_shown_as_unknown(self):
        self.conn.execute("UPDATE charts SET donate_count=NULL,play_count=NULL WHERE cid=20")
        output = self.run_command("-1 recommend_count 1")[1]
        self.assertIn("打赏: 未知, 游玩: 未知", output)

    def test_legacy_play_placeholder_is_not_presented_as_real_zero(self):
        self.assertIn("游玩: 未知（历史值 0）", self.run_command("")[1])

    def test_invalid_arguments_do_not_return_rows(self):
        for arg in ("-1 recommend_count 0", "-1 recommend_count -2",
                    "99 recommend_count 3", "-1 unknown 3", "recommend_count abc",
                    "-1 recommend_count abc", "-1 recommend_count 3 extra"):
            with self.subTest(arg=arg):
                cids, output = self.run_command(arg)
                self.assertEqual(cids, [])
                self.assertTrue("错误" in output or "用法" in output)

    def test_legacy_database_reports_missing_column_for_recommendations(self):
        self.conn.execute("ALTER TABLE charts DROP COLUMN recommend_count")
        self.assertIn("缺少 recommend_count", self.run_command("recommend_count")[1])
        self.assertEqual(self.run_command("")[0], [10, 50, 40, 30, 20])
