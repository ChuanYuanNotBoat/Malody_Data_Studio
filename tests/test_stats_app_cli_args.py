import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.stats_cli import app as stats_app  # noqa: E402


class TestStatsAppCliArgs(TestCase):
    def test_database_path_honors_environment(self):
        with patch.dict("os.environ", {"MALODY_DB_PATH": "custom.db"}):
            self.assertEqual(stats_app._resolve_db_path(), "custom.db")

    def test_database_path_prefers_data_directory_and_falls_back_to_legacy(self):
        root = Path(stats_app.__file__).resolve().parents[1]
        with patch.dict("os.environ", {}, clear=True):
            with patch("malody_api.stats_cli.app.os.path.exists", return_value=True):
                self.assertEqual(Path(stats_app._resolve_db_path()), root / "data" / "malody_rankings.db")
            with patch("malody_api.stats_cli.app.os.path.exists", return_value=False):
                self.assertEqual(Path(stats_app._resolve_db_path()), root / "malody_rankings.db")

    def test_main_executes_commands_from_c(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.app.MalodyViz"
        ) as mock_viz:
            inst = mock_viz.return_value
            inst.onecmd.return_value = False

            rc = stats_app.main(["-c", "mode 3", "-c", "top 5"])

        self.assertEqual(rc, 0)
        inst.onecmd.assert_any_call("mode 3")
        inst.onecmd.assert_any_call("top 5")
        self.assertEqual(inst.onecmd.call_count, 2)
        inst.cmdloop.assert_not_called()

    def test_main_executes_direct_command_tokens(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.app.MalodyViz"
        ) as mock_viz:
            inst = mock_viz.return_value
            inst.onecmd.return_value = False

            rc = stats_app.main(["mode", "3"])

        self.assertEqual(rc, 0)
        inst.onecmd.assert_called_once_with("mode 3")
        inst.cmdloop.assert_not_called()

    def test_main_enters_cmdloop_without_commands(self):
        with patch("malody_api.stats_cli.app.os.path.exists", return_value=True), patch(
            "malody_api.stats_cli.app.MalodyViz"
        ) as mock_viz:
            inst = mock_viz.return_value

            rc = stats_app.main([])

        self.assertEqual(rc, 0)
        inst.cmdloop.assert_called_once()

