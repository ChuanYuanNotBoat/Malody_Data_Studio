import os
import sys
from pathlib import Path
from unittest import TestCase

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.stats_update_runner import build_update_command, split_cli_args  # noqa: E402


def _colorize(text: str, _color: str) -> str:
    return text


class TestStatsUpdateRunner(TestCase):
    def test_split_cli_args(self):
        args = split_cli_args('--uid "1001 1002" --limit 10', _colorize, "RED")
        self.assertEqual(args, ["--uid", "1001 1002", "--limit", "10"])

    def test_build_update_default_leaderboard(self):
        cmd = build_update_command([], ".", "python", _colorize, "RED", "YELLOW")
        self.assertEqual(cmd, ["python", os.path.join(".", "crawlers/rankings.py"), "--once"])

    def test_build_update_player_unknown_flag(self):
        cmd = build_update_command(["--player", "--unknown"], ".", "python", _colorize, "RED", "YELLOW")
        self.assertIsNone(cmd)

    def test_build_update_stb_sid_mapping(self):
        cmd = build_update_command(
            ["--stb", "--sid-crawl", "--start", "10", "--end", "20", "--limit", "30", "--resume", "false"],
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
                "--max-charts",
                "30",
                "--sid-crawl",
                "--start-sid",
                "10",
                "--end-sid",
                "20",
                "--no-resume",
            ],
        )
