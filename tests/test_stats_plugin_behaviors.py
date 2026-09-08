import io
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli.plugins import (  # noqa: E402
    export_plugin,
    help_plugin,
    optimize_plugin,
    repair_plugin,
    update_plugin,
    utility_plugin,
)
from stats_cli.plugins.registry import reload_plugins  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return text


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
        self.filters = {}

    def get_current_selection(self):
        return self.filters

    def set_filters(self, **kwargs):
        self.filters.update(kwargs)


class _ShellStub:
    def __init__(self):
        self.conn = object()
        self.selector = _SelectorStub()
        self.output_dir = "tmp"
        self.current_mode = -1
        self.mode_names = {-1: "All", 0: "Key", 3: "Catch"}
        self.cleaned = False

    def _parse_time_range_string(self, raw):
        return {"raw": raw}

    def get_unique_filename(self, base, ext):
        return f"{base}.{ext}"

    def cleanup(self):
        self.cleaned = True


class TestStatsPluginBehaviors(TestCase):
    @classmethod
    def setUpClass(cls):
        colors = SimpleNamespace(RED="RED", YELLOW="YELLOW", GREEN="GREEN", CYAN="CYAN", BLUE="BLUE")
        update_plugin.install(_ShellStub, colorize=_colorize, colors=colors, base_dir=".")
        export_plugin.install(_ShellStub, colorize=_colorize, colors=colors, db_safe_operation=_db_safe_operation)
        utility_plugin.install(
            _ShellStub,
            colorize=_colorize,
            colors=colors,
            get_separator=_separator,
            db_safe_operation=_db_safe_operation,
        )
        help_plugin.install(
            _ShellStub,
            colorize=_colorize,
            colors=colors,
            get_separator=_separator,
            get_subseparator=_separator,
        )
        optimize_plugin.install(_ShellStub, colorize=_colorize, colors=colors, base_dir=".")
        repair_plugin.install(
            _ShellStub,
            colorize=_colorize,
            colors=colors,
            db_safe_operation=_db_safe_operation,
            get_separator=_separator,
        )

    def test_update_command_skips_when_split_fails(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.update_plugin.split_cli_args", return_value=None), patch(
            "malody_api.stats_cli.plugins.update_plugin.build_update_command"
        ) as build_mock:
            shell.do_update('bad "quote')

        build_mock.assert_not_called()

    def test_update_command_skips_when_command_build_fails(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.update_plugin.split_cli_args", return_value=["--stb"]), patch(
            "malody_api.stats_cli.plugins.update_plugin.build_update_command", return_value=None
        ), patch("malody_api.stats_cli.plugins.update_plugin.run_streaming_command") as run_mock:
            shell.do_update("--stb")

        run_mock.assert_not_called()

    def test_update_command_runs_streaming_command_on_success(self):
        shell = _ShellStub()
        command = ["python", os.path.join(".", "crawlers", "stb.py")]
        with patch("malody_api.stats_cli.plugins.update_plugin.split_cli_args", return_value=["--stb"]), patch(
            "malody_api.stats_cli.plugins.update_plugin.build_update_command", return_value=command
        ) as build_mock, patch("malody_api.stats_cli.plugins.update_plugin.run_streaming_command") as run_mock:
            shell.do_update("--stb")

        build_mock.assert_called_once()
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["cmd"], command)

    def test_export_command_skips_when_request_parse_fails(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.export_plugin.parse_export_request", return_value=None), patch(
            "malody_api.stats_cli.plugins.export_plugin.run_export"
        ) as run_mock:
            shell.do_export("bad")

        run_mock.assert_not_called()

    def test_export_command_passes_shell_context_to_runner(self):
        shell = _ShellStub()
        request = object()
        with patch("malody_api.stats_cli.plugins.export_plugin.parse_export_request", return_value=request), patch(
            "malody_api.stats_cli.plugins.export_plugin.run_export"
        ) as run_mock:
            shell.do_export("top --mode 3")

        run_mock.assert_called_once()
        kwargs = run_mock.call_args.kwargs
        self.assertIs(kwargs["request"], request)
        self.assertIs(kwargs["conn"], shell.conn)
        self.assertIs(kwargs["selector"], shell.selector)
        self.assertEqual(kwargs["output_dir"], "tmp")

    def test_ls_command_lists_existing_directory(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.utility_plugin.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.plugins.utility_plugin.os.listdir", return_value=["subdir", "file.txt"]
        ), patch("malody_api.stats_cli.plugins.utility_plugin.os.path.isdir", side_effect=lambda p: p.endswith("subdir")), patch(
            "malody_api.stats_cli.plugins.utility_plugin.os.path.getsize", return_value=12
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_ls(".")

        output = stdout.getvalue()
        self.assertIn("subdir", output)
        self.assertIn("file.txt", output)

    def test_ls_command_reports_missing_path(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.utility_plugin.os.path.exists", return_value=False), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            shell.do_ls("missing")

        self.assertIn("missing", stdout.getvalue())

    def test_mode_command_reports_current_mode_without_argument(self):
        shell = _ShellStub()
        shell.current_mode = 3
        shell.selector.current_mode = 3
        shell.selector.filters = {"modes": [3]}
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_mode("")

        output = stdout.getvalue()
        self.assertIn("3", output)
        self.assertIn("Catch", output)

    def test_mode_command_switches_to_all_modes(self):
        shell = _ShellStub()
        shell.selector.filters = {"modes": [3]}

        shell.do_mode("*")

        self.assertEqual(shell.current_mode, -1)
        self.assertEqual(shell.selector.current_mode, -1)
        self.assertEqual(shell.selector.filters["modes"], [])

    def test_mode_command_switches_to_specific_mode(self):
        shell = _ShellStub()

        shell.do_mode("3")

        self.assertEqual(shell.current_mode, 3)
        self.assertEqual(shell.selector.current_mode, 3)
        self.assertEqual(shell.selector.filters["modes"], [3])

    def test_mode_command_rejects_out_of_range_and_non_integer(self):
        shell = _ShellStub()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_mode("99")
            shell.do_mode("abc")

        output = stdout.getvalue()
        self.assertIn("0-9", output)

    def test_exit_and_quit_commands_cleanup_and_stop(self):
        shell = _ShellStub()

        exit_result = shell.do_exit("")
        quit_result = shell.do_quit("")

        self.assertTrue(exit_result)
        self.assertTrue(quit_result)
        self.assertTrue(shell.cleaned)

    def test_help_command_shows_specific_command_doc(self):
        shell = _ShellStub()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_help("mode")

        self.assertIn("mode", stdout.getvalue().lower())

    def test_help_command_reports_unknown_command(self):
        shell = _ShellStub()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_help("does-not-exist")

        self.assertIn("does-not-exist", stdout.getvalue())

    def test_help_command_prints_command_index(self):
        shell = _ShellStub()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_help("")

        output = stdout.getvalue().lower()
        self.assertIn("export", output)
        self.assertIn("update", output)
        self.assertIn("reload", output)

    def test_reload_command_dispatches_by_module(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            reload_mock.return_value = {
                "ok": True,
                "message": "Reloaded plugin module: stats_cli.plugins.utility_plugin",
                "reloaded_modules": ["stats_cli.plugins.utility_plugin"],
            }
            shell.do_reload("module utility")

        reload_mock.assert_called_once_with(shell.__class__, module_name="utility")

    def test_reload_command_dispatches_by_command(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            reload_mock.return_value = {
                "ok": True,
                "message": "Reloaded plugin module: stats_cli.plugins.help_plugin",
                "reloaded_modules": ["stats_cli.plugins.help_plugin"],
            }
            shell.do_reload("command help")

        reload_mock.assert_called_once_with(shell.__class__, command_name="help")

    def test_reload_command_reports_argument_parse_failure(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            shell.do_reload('module "broken')

        reload_mock.assert_not_called()
        self.assertIn("failed to parse arguments", stdout.getvalue().lower())

    def test_reload_command_supports_misspelled_module_keyword(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            reload_mock.return_value = {
                "ok": True,
                "message": "Reloaded plugin module: stats_cli.plugins.help_plugin",
                "reloaded_modules": ["stats_cli.plugins.help_plugin"],
            }
            shell.do_reload("moudle help")

        reload_mock.assert_called_once_with(shell.__class__, module_name="help")

    def test_reload_question_mark_prints_usage(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            shell.do_reload("?")

        reload_mock.assert_not_called()
        output = stdout.getvalue().lower()
        self.assertIn("usage: reload", output)
        self.assertIn("reload command ls", output)

    def test_reload_module_unknown_command_shows_hint(self):
        shell = _ShellStub()
        with patch("stats_cli.plugins.registry.reload_plugins") as reload_mock, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            reload_mock.return_value = {
                "ok": False,
                "message": "Unknown plugin module: ls",
                "reloaded_modules": [],
                "hints": ["'ls' looks like a command. Try: reload command ls"],
            }
            shell.do_reload("module ls")

        reload_mock.assert_called_once_with(shell.__class__, module_name="ls")
        self.assertIn("try: reload command ls", stdout.getvalue().lower())

    def test_registry_unknown_module_suggests_command_hint(self):
        _ShellStub._plugin_install_context = {"ready": True}
        result = reload_plugins(_ShellStub, module_name="ls")
        self.assertFalse(result["ok"])
        self.assertIn("reload command ls", " ".join(result.get("hints", [])).lower())

    def test_registry_unknown_module_help_token_suggests_usage(self):
        _ShellStub._plugin_install_context = {"ready": True}
        result = reload_plugins(_ShellStub, module_name="?")
        self.assertFalse(result["ok"])
        self.assertIn("reload ?", " ".join(result.get("hints", [])).lower())

    def test_mm_stats_command_reports_invalid_limit(self):
        shell = _ShellStub()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_mm_stats("abc")
        self.assertIn("mm_limit", stdout.getvalue())

    def test_mm_stats_command_prints_summary_from_service(self):
        shell = _ShellStub()
        payload = {
            "counts": {
                "player_rankings_mm": 10,
                "player_mmr_samples": 20,
                "player_mmr_daily": 8,
            },
            "freshness": {
                "player_rankings_mm_max_crawl_time": "2026-04-28T22:52:28",
                "player_mmr_samples_max_crawl_time": "2026-04-28T23:08:09",
            },
            "tracked_players": {
                "union_players_count": 100,
                "manual_players_count": 4,
                "mm_top_players_count": 98,
                "overlap_count": 2,
                "mm_limit": 150,
            },
            "mm_latest_snapshot_by_mode": [
                {"mode": 3, "rows": 200, "dup_rank": 1, "dup_uid": 0, "min_rank": 1, "max_rank": 199}
            ],
            "mmr_samples_by_source": [
                {"source": "ranking_player_all", "sample_count": 20, "player_count": 10}
            ],
        }

        with patch("malody_api.stats_cli.plugins.utility_plugin._PkgPlayerService") as svc_cls, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            svc_cls.return_value.get_mm_stats.return_value = payload
            shell.do_mm_stats("150")

        svc_cls.return_value.get_mm_stats.assert_called_once_with(mm_limit=150)
        output = stdout.getvalue()
        self.assertIn("MM/MMR", output)
        self.assertIn("union=100", output)
        self.assertIn("mode=3", output)

    def test_mm_stats_fallback_excludes_zero_uid_from_tracked_players(self):
        shell = _ShellStub()
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE player_rankings_mm (
                mode INTEGER,
                rank INTEGER,
                uid TEXT,
                crawl_time TEXT
            );
            """
        )
        cursor.executemany(
            "INSERT INTO player_rankings_mm (mode, rank, uid, crawl_time) VALUES (?, ?, ?, ?)",
            [
                (3, 1, "0", "2026-04-01T00:00:00"),
                (3, 2, "1001", "2026-04-01T00:00:00"),
            ],
        )
        conn.commit()
        shell.conn = conn

        with patch("malody_api.stats_cli.plugins.utility_plugin._PkgPlayerService", None), patch(
            "malody_api.stats_cli.plugins.utility_plugin.os.path.exists", return_value=False
        ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_mm_stats("200")

        output = stdout.getvalue()
        self.assertIn("mm_top=1", output)
        self.assertNotIn("mm_top=2", output)
        conn.close()

    def test_repair_command_fixes_known_status_mismatch(self):
        shell = _ShellStub()
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE charts (
                cid INTEGER PRIMARY KEY,
                status INTEGER
            );
            INSERT INTO charts (cid, status) VALUES (139970, 0);
            """
        )
        conn.commit()
        shell.conn = conn

        with patch("sys.stdout", new_callable=io.StringIO):
            shell.do_repair("")

        cursor.execute("SELECT status FROM charts WHERE cid = 139970")
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()

    def test_optimize_command_ignores_argument_and_uses_base_dir_as_cwd(self):
        shell = _ShellStub()
        with patch("malody_api.stats_cli.plugins.optimize_plugin.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.plugins.optimize_plugin.subprocess.run"
        ) as run_mock, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            shell.do_optimize("extra")

        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["cwd"], ".")
        self.assertIn("已忽略", stdout.getvalue())
