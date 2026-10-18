import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from crawlers.chart_metrics import parse_chart_metrics
from crawlers.stb import STBCrawler
from scripts import refresh_chart_metrics


HTML = """<div class="like_area">
<div class="num"><img src="icon-love.png"><span>Very Positive</span></div>
<div class="num"><img src="icon-donate.png">Donation<span class="l">118,222</span></div>
<div class="num"><img src="icon-play.png"><span>Hot</span><span class="l">1432717</span></div>
</div>"""


class TestStbMetrics(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.crawler = STBCrawler.__new__(STBCrawler)
        self.crawler.logger = Mock()
        self.crawler.db_manager = SimpleNamespace(get_connection=lambda: self.conn)
        self.crawler.crawl_stats = dict.fromkeys(["new", "updated", "unchanged", "failed"], 0)
        self.crawler.processed_charts = set()
        self.crawler.processed_songs = set()
        self.crawler.init_database()
        self.crawler.session = Mock()
        self.crawler.session.get.return_value.text = HTML
        self.crawler._apply_api_rate_limit = Mock()
        self.crawler._build_chart_social_data = Mock(return_value=(0, 0, []))
        self.chart = {"cid": 17302, "sid": 4448, "like": 3446, "hot": 1414193,
                      "creator": "ExNeko", "version": "4K Normal Lv.10", "type": 2, "mode": 0}
        self.song = {"sid": 4448, "title": "Song", "artist": "Artist"}

    def test_page_hot_is_not_play_count(self):
        self.assertEqual(parse_chart_metrics(HTML), {"donate_count": 118222, "heat": 1432717})

    def test_missing_invalid_and_explicit_zero_are_distinct(self):
        self.assertEqual(parse_chart_metrics("<html>Unavailable</html>"), {})
        self.assertNotIn("donate_count", parse_chart_metrics(HTML.replace("118,222", "N/A")))
        self.assertEqual(parse_chart_metrics(HTML.replace("118,222", "0"))["donate_count"], 0)

    def test_api_supplements_donation_and_keeps_play_unknown(self):
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute(
            "SELECT donate_count,play_count,recommend_count,heat FROM charts"
        ).fetchone(), (118222, None, 3446, 1414193))

    def test_failed_supplement_preserves_existing_counters(self):
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.conn.execute("UPDATE charts SET play_count=42")
        self.conn.commit()
        self.crawler.session.get.side_effect = requests.Timeout("timeout")
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute("SELECT donate_count,play_count FROM charts").fetchone(), (118222, 42))

    def test_explicit_zero_donation_is_saved(self):
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.crawler.session.get.return_value.text = HTML.replace("118,222", "0")
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute("SELECT donate_count FROM charts").fetchone()[0], 0)

    def test_new_chart_with_unavailable_page_stores_null(self):
        self.crawler.session.get.return_value.text = "<html>Login</html>"
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute("SELECT donate_count,play_count FROM charts").fetchone(), (None, None))

    def test_html_parser_does_not_invent_play_or_donation(self):
        chart, song = self.crawler.parse_chart_page("<html></html>", 123)
        self.assertIsNone(chart)
        self.assertIsNone(song)

    def test_refresh_repairs_only_selected_rows_and_backs_up(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("""
                    CREATE TABLE charts (cid INTEGER, heat INTEGER, donate_count INTEGER,
                        play_count INTEGER, data_hash TEXT, server_exists INTEGER, recommend_count INTEGER);
                    INSERT INTO charts VALUES (1, 10, 0, 0, 'old', 1, 100);
                    INSERT INTO charts VALUES (2, 10, 0, 0, 'old', 1, 50);
                """)
            response = Mock(text=HTML)
            session = Mock(headers={})
            session.get.return_value = response
            with patch.object(refresh_chart_metrics.requests, "Session") as factory:
                factory.return_value.__enter__.return_value = session
                self.assertEqual(refresh_chart_metrics.main(["--db-path", str(path), "--limit", "1"]), 0)
                with closing(sqlite3.connect(path)) as conn:
                    self.assertEqual(conn.execute("SELECT donate_count FROM charts WHERE cid=1").fetchone(), (0,))
                self.assertEqual(refresh_chart_metrics.main(["--db-path", str(path), "--limit", "1", "--apply"]), 0)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("SELECT donate_count,play_count FROM charts WHERE cid=1").fetchone(), (118222, None))
                self.assertEqual(conn.execute("SELECT donate_count,play_count FROM charts WHERE cid=2").fetchone(), (0, 0))
            backup = next((Path(directory) / "backups").glob("*.json"))
            self.assertEqual(json.loads(backup.read_text())["before"][0]["donate_count"], 0)
            with patch.object(refresh_chart_metrics.requests, "Session") as factory:
                factory.return_value.__enter__.return_value = session
                self.assertEqual(refresh_chart_metrics.main(["--db-path", str(path), "--cid", "2", "--apply"]), 0)
            self.assertTrue(session.get.call_args.args[0].endswith("/chart/2"))
