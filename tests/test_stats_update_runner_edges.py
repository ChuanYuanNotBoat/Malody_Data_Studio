import io
import os
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.stats_update_runner import (  # noqa: E402
    build_update_command,
    parse_cli_options,
    run_streaming_command,
    split_cli_args,
)


def _colorize(text: str, _color: str) -> str:
    return text


class TestStatsUpdateRunnerEdges(TestCase):
    def test_split_cli_args_rejects_unclosed_quote(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            args = split_cli_args('--uid "1001', _colorize, "RED")

        self.assertIsNone(args)
        self.assertTrue(stdout.getvalue())

    def test_parse_cli_options_rejects_positional_token(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            options = parse_cli_options(["oops"], _colorize, "RED")

        self.assertIsNone(options)
        self.assertIn("oops", stdout.getvalue())

    def test_build_update_command_rejects_multiple_crawler_types(self):
        cmd = build_update_command(["--player", "--stb"], ".", "python", _colorize, "RED", "YELLOW")
        self.assertIsNone(cmd)

    def test_build_update_command_rejects_leaderboard_unknown_flag(self):
        cmd = build_update_command(["--leaderboard", "--limit", "5"], ".", "python", _colorize, "RED", "YELLOW")
        self.assertIsNone(cmd)

    def test_build_update_command_builds_player_command_with_all_flag_types(self):
        cmd = build_update_command(
            [
                "--player",
                "--uid",
                "1001",
                "--uid-list",
                "1001,1002",
                "--leaderboard-mode",
                "3",
                "--limit",
                "20",
                "--days-since-update",
                "7",
                "--max-workers",
                "4",
                "--rpm",
                "60",
                "--log-level",
                "info",
                "--log-file",
                "crawler.log",
                "--resume-file",
                "resume.bin",
                "--save-interval",
                "10",
                "--from-db",
                "--from-leaderboard",
                "--test",
                "--print-only",
                "--status",
                "--no-default-players",
            ],
            ".",
            "python",
            _colorize,
            "RED",
            "YELLOW",
        )

        self.assertEqual(
            cmd,
            [
                "python",
                os.path.join(".", "crawlers/player_profile.py"),
                "--uid",
                "1001",
                "--uid-list",
                "1001,1002",
                "--log-level",
                "info",
                "--log-file",
                "crawler.log",
                "--resume-file",
                "resume.bin",
                "--leaderboard-mode",
                "3",
                "--limit",
                "20",
                "--days-since-update",
                "7",
                "--max-workers",
                "4",
                "--rpm",
                "60",
                "--save-interval",
                "10",
                "--from-db",
                "--from-leaderboard",
                "--test",
                "--print-only",
                "--status",
                "--no-default-players",
            ],
        )

    def test_build_update_command_rejects_invalid_player_integer_flag(self):
        cmd = build_update_command(["--player", "--limit", "0"], ".", "python", _colorize, "RED", "YELLOW")
        self.assertIsNone(cmd)

    def test_build_update_command_rejects_invalid_stb_source_resume_and_log_level(self):
        invalid_source = build_update_command(["--stb", "--source", "bad"], ".", "python", _colorize, "RED", "YELLOW")
        invalid_resume = build_update_command(["--stb", "--resume", "maybe"], ".", "python", _colorize, "RED", "YELLOW")
        invalid_level = build_update_command(["--stb", "--log-level", "trace"], ".", "python", _colorize, "RED", "YELLOW")

        self.assertIsNone(invalid_source)
        self.assertIsNone(invalid_resume)
        self.assertIsNone(invalid_level)

    def test_build_update_command_maps_stb_cid_range_by_default(self):
        cmd = build_update_command(
            ["--stb", "--start", "10", "--end", "20", "--limit", "30", "--source", "api", "--resume", "true"],
            ".",
            "python",
            _colorize,
            "RED",
            "YELLOW",
        )

        self.assertEqual(
            cmd,
            [
                "python",
                os.path.join(".", "crawlers/stb.py"),
                "--source",
                "api",
                "--max-charts",
                "30",
                "--start-cid",
                "10",
                "--end-cid",
                "20",
            ],
        )

    def test_run_streaming_command_reports_success_failure_and_spawn_errors(self):
        success_process = Mock()
        success_process.stdout = iter(["ok\n", "\x1b[31mwarn\x1b[0m\n"])
        success_process.returncode = 0

        failed_process = Mock()
        failed_process.stdout = iter(["bad\n"])
        failed_process.returncode = 7

        with patch("malody_api.utils.stats_update_runner.subprocess.Popen", side_effect=[success_process, failed_process]):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                run_streaming_command(["python", "ok.py"], _colorize, "CYAN", "GREEN", "RED")
                run_streaming_command(["python", "bad.py"], _colorize, "CYAN", "GREEN", "RED")

        output = stdout.getvalue()
        self.assertIn("ok", output)
        self.assertIn("warn", output)
        self.assertIn("7", output)

        with patch("malody_api.utils.stats_update_runner.subprocess.Popen", side_effect=OSError("spawn failed")):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                run_streaming_command(["python", "boom.py"], _colorize, "CYAN", "GREEN", "RED")

        self.assertIn("spawn failed", stdout.getvalue())
