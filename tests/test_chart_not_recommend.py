import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from crawlers.chart_votes import classify_chart_vote, nonnegative_count
from crawlers.stb import STBCrawler
from scripts.backfill_not_recommend import apply_backfill, plan_backfill
from malody_api.core.services.chart_service import ChartService


class TestChartNotRecommend(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.crawler = STBCrawler.__new__(STBCrawler)
        self.crawler.logger = Mock()
        self.crawler.db_manager = SimpleNamespace(get_connection=lambda: self.conn)
        self.crawler.processed_charts = set()
        self.crawler.processed_songs = set()
        self.crawler.crawl_stats = dict.fromkeys(("new", "updated", "unchanged", "failed"), 0)
        self.crawler.init_database()
        self.crawler._apply_api_rate_limit = Mock()
        self.crawler.session = Mock()
        self.crawler.session.get.return_value.text = "<html></html>"
        self.crawler._build_chart_social_data = Mock(return_value=(0, 0, []))
        self.chart = {"cid": 17302, "sid": 4448, "like": 3546, "dislike": 381,
                      "version": "4K Normal Lv.10", "mode": 0, "type": 2}
        self.song = {"sid": 4448, "title": "Song", "artist": "Artist"}

    def test_real_negative_message_can_also_be_type_one(self):
        # Same shape and message prefix as the live chart_4236 talk response.
        item = {"type": 1, "content": "<p>Not recommended, score: 819578, combo: 136, acc: 97.86%</p>"}
        self.assertEqual(classify_chart_vote(item), "not_recommend")
        self.assertFalse(self.crawler._is_recommend_talk_item(item))
        self.assertEqual(classify_chart_vote({"content": "<p>Not recommended, score: 560607</p>"}), "not_recommend")

    def test_direction_requires_explicit_text_not_type_alone(self):
        for text in ("Notrecommend", "not recommend", "<b>Not recommended</b>, score: 1", "不推荐"):
            self.assertEqual(classify_chart_vote({"content": text}), "not_recommend")
        self.assertEqual(classify_chart_vote({"content": "<p>Recommend, score: 1</p>"}), "recommend")
        self.assertIsNone(classify_chart_vote({"type": 1, "content": ""}))
        self.assertIsNone(classify_chart_vote({"content": "I do not recommend this mapping"}))

    def test_negative_votes_are_not_comments_or_positive_votes(self):
        del self.crawler._build_chart_social_data
        self.crawler._fetch_chart_talk_items = Mock(return_value=[
            {"tid": 1, "type": 1, "content": "Recommend, score: 1"},
            {"tid": 2, "type": 1, "content": "<p>Not recommended, score: 1</p>"},
            {"tid": 3, "content": "A regular comment"},
            {"tid": 4, "type": 1, "content": ""},
        ])
        positives, comments, items = self.crawler._build_chart_social_data(17302)
        self.assertEqual((positives, comments), (1, 1))
        self.assertEqual([(i["is_recommend"], i["is_not_recommend"]) for i in items], [(1, 0), (0, 1), (0, 0), (0, 0)])

    def test_official_total_is_saved_and_unknown_does_not_erase_it(self):
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute("SELECT not_recommend_count FROM charts").fetchone()[0], 381)
        without_dislike = {k: v for k, v in self.chart.items() if k != "dislike"}
        self.assertTrue(self.crawler._save_chart_data_from_new_api(without_dislike, self.song))
        self.assertEqual(self.conn.execute("SELECT not_recommend_count FROM charts").fetchone()[0], 381)
        self.assertTrue(self.crawler._save_chart_data_from_new_api(dict(self.chart, dislike=0), self.song))
        self.assertEqual(self.conn.execute("SELECT not_recommend_count FROM charts").fetchone()[0], 0)

    def test_negative_event_count_is_not_used_as_official_total(self):
        self.crawler._build_chart_social_data.return_value = (0, 0, [
            {"tid": 123, "content": "Not recommended", "is_not_recommend": 1}
        ])
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertEqual(self.conn.execute("SELECT not_recommend_count FROM charts").fetchone()[0], 381)
        self.assertEqual(self.conn.execute("SELECT is_recommend,is_not_recommend FROM chart_comments").fetchone(), (0, 1))

    def test_unknown_total_is_null_and_invalid_counts_are_not_zero(self):
        self.chart.pop("dislike")
        self.assertTrue(self.crawler._save_chart_data_from_new_api(self.chart, self.song))
        self.assertIsNone(self.conn.execute("SELECT not_recommend_count FROM charts").fetchone()[0])
        for value in (None, "", -1, True, 1.5, "invalid"):
            self.assertIsNone(nonnegative_count(value))
        self.assertEqual(nonnegative_count("0"), 0)

    def test_html_path_can_supplement_authoritative_total(self):
        self.crawler._new_api_get = Mock(return_value={"code": 0, "cid": 17302, "dislike": 381})
        self.assertEqual(self.crawler._fetch_not_recommend_count(17302), 381)
        self.crawler._new_api_get.return_value = {"code": 0, "cid": 999, "dislike": 8}
        self.assertIsNone(self.crawler._fetch_not_recommend_count(17302))
        self.crawler._new_api_get.return_value = {"code": -1000}
        self.assertIsNone(self.crawler._fetch_not_recommend_count(17302))

    def test_backfill_migrates_legacy_schema_and_is_repeatable(self):
        with sqlite3.connect(":memory:") as legacy:
            legacy.executescript("""
                CREATE TABLE charts (cid INTEGER PRIMARY KEY,data_hash TEXT);
                INSERT INTO charts VALUES (1,'old'); INSERT INTO charts VALUES (2,'untouched');
                CREATE TABLE chart_comments (tid INTEGER PRIMARY KEY,cid INTEGER,content TEXT,is_recommend INTEGER);
                INSERT INTO chart_comments VALUES (10,1,'<p>Not recommended, score: 1</p>',1);
                INSERT INTO chart_comments VALUES (11,1,'<p>Recommend, score: 1</p>',0);
                INSERT INTO chart_comments VALUES (12,1,'ordinary comment',0);
            """)
            changes = plan_backfill(legacy)
            self.assertEqual(len(changes), 2)
            self.assertEqual(apply_backfill(legacy, changes, {1: 4}), (2, 1))
            self.assertEqual(tuple(legacy.execute("SELECT is_recommend,is_not_recommend FROM chart_comments WHERE tid=10").fetchone()), (0, 1))
            self.assertEqual(tuple(legacy.execute("SELECT not_recommend_count FROM charts WHERE cid=2").fetchone()), (None,))
            self.assertEqual(plan_backfill(legacy), [])

    def test_api_comments_exposes_flag_and_regular_filter_excludes_votes(self):
        self.crawler._build_chart_social_data.return_value = (0, 1, [
            {"tid": 1, "content": "Not recommended", "is_not_recommend": 1},
            {"tid": 2, "content": "regular comment"},
        ])
        self.crawler._save_chart_data_from_new_api(self.chart, self.song)
        # Service closes its connection, so expose a wrapper with a no-op close.
        connection = SimpleNamespace(cursor=self.conn.cursor, close=lambda: None)
        with patch("malody_api.core.services.chart_service.get_db_connection", return_value=connection):
            service = ChartService()
            all_items = service.get_chart_comments(17302)
            comments = service.get_chart_comments(17302, include_recommend=False)
        self.assertEqual(next(i for i in all_items if i["tid"] == 1)["is_not_recommend"], 1)
        self.assertEqual([i["tid"] for i in comments], [2])

    def test_comments_remain_readable_before_legacy_schema_migration(self):
        with sqlite3.connect(":memory:") as legacy:
            legacy.execute("CREATE TABLE chart_comments (tid INTEGER,cid INTEGER,uid INTEGER,name TEXT,content TEXT,talk_type INTEGER,is_recommend INTEGER,talk_time TEXT,crawl_time TEXT)")
            legacy.execute("INSERT INTO chart_comments VALUES (1,5,1,'name','comment',NULL,0,NULL,NULL)")
            connection = SimpleNamespace(cursor=legacy.cursor, close=lambda: None)
            with patch("malody_api.core.services.chart_service.get_db_connection", return_value=connection):
                rows = ChartService().get_chart_comments(5, include_recommend=False)
            self.assertEqual(rows[0]["is_not_recommend"], 0)
