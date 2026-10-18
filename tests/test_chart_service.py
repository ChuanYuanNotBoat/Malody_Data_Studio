import sqlite3
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.core.services.chart_service import ChartService  # noqa: E402
from malody_api.utils.selector import MCSelector  # noqa: E402


def _seed_conn():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE songs (sid INTEGER PRIMARY KEY, title TEXT, artist TEXT)")
    cur.execute(
        """
        CREATE TABLE charts (
            cid INTEGER PRIMARY KEY,
            sid INTEGER,
            mode INTEGER,
            level TEXT,
            status INTEGER,
            creator_name TEXT,
            stabled_by_name TEXT,
            heat INTEGER,
            donate_count INTEGER,
            play_count INTEGER,
            last_updated TEXT
        )
        """
    )
    cur.execute("INSERT INTO songs (sid, title, artist) VALUES (1, 'Song A', 'Artist A')")
    cur.execute(
        """
        INSERT INTO charts (cid, sid, mode, level, status, creator_name, stabled_by_name, heat, donate_count, play_count, last_updated)
        VALUES (100, 1, 0, '10', 2, 'creator_x', 'stabilizer_x', 42, 5, 100, '2026-01-01')
        """
    )
    conn.commit()
    return conn


class TestChartService(TestCase):
    def setUp(self):
        self.service = ChartService()
        self.selector = MCSelector()

    def test_hot_charts_accepts_unknown_donation(self):
        def connection_with_unknown_donation():
            conn = _seed_conn()
            conn.execute("ALTER TABLE charts ADD COLUMN version TEXT DEFAULT 'Hard'")
            conn.execute("UPDATE charts SET donate_count = NULL")
            conn.commit()
            return conn

        with patch("malody_api.core.services.chart_service.get_db_connection", side_effect=connection_with_unknown_donation):
            charts = self.service.get_hot_charts(self.selector)
        self.assertEqual(len(charts), 1)
        self.assertIsNone(charts[0].donate_count)

    def test_summary(self):
        with patch("malody_api.core.services.chart_service.get_db_connection", side_effect=_seed_conn):
            data = self.service.get_chart_summary(self.selector, detail_level="detailed")
        self.assertIsInstance(data, dict)
        self.assertEqual(data["total_charts"], 1)

    def test_quality(self):
        with patch("malody_api.core.services.chart_service.get_db_connection", side_effect=_seed_conn):
            data = self.service.get_chart_quality(self.selector)
        self.assertIsInstance(data, dict)
        self.assertIn("quality_score", data)

    def test_top_stabilizers(self):
        with patch("malody_api.core.services.chart_service.get_db_connection", side_effect=_seed_conn):
            data = self.service.get_top_stabilizers(mode=0, limit=10)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["stabilizer_name"], "stabilizer_x")

    def test_creator_trends(self):
        with patch("malody_api.core.services.chart_service.get_db_connection", side_effect=_seed_conn):
            data = self.service.get_creator_trends("creator_x", period="days", mode=0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["count"], 1)

