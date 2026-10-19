import sys
import sqlite3
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.scripts import check_stats_api_consistency as consistency  # noqa: E402


class TestStatsConsistencyScript(TestCase):
    def test_stabilizer_ties_match_api_sort(self):
        from malody_api.core.services.chart_service import ChartService

        def connection():
            conn=sqlite3.connect(':memory:')
            conn.row_factory=sqlite3.Row
            conn.execute('CREATE TABLE charts(stabled_by_name TEXT,status INTEGER,mode INTEGER,heat INTEGER,last_updated TEXT)')
            conn.executemany('INSERT INTO charts VALUES(?,2,3,?,NULL)',[('Z',1),('B',10),('A',10)])
            return conn

        conn=connection()
        try:baseline=consistency.calc_top_stabilizers_baseline(conn,3,20)
        finally:conn.close()
        with patch('malody_api.core.services.chart_service.get_db_connection',side_effect=connection):
            actual=ChartService().get_top_stabilizers(3,20)
        self.assertEqual([r['stabilizer_name'] for r in baseline],['A','B','Z'])
        self.assertEqual([r['stabilizer_name'] for r in actual],[r['stabilizer_name'] for r in baseline])

    def test_parse_csv_ints(self):
        self.assertEqual(consistency.parse_csv_ints(""), [])
        self.assertEqual(consistency.parse_csv_ints("0, 1,2"), [0, 1, 2])

    def test_parse_threshold_rules_and_prefixes(self):
        rules = consistency._parse_threshold_rules('{"quality.issues.": 2, "summary.total_charts": 0}')
        self.assertEqual(rules["quality.issues."], 2.0)
        self.assertEqual(rules["summary.total_charts"], 0.0)
        self.assertEqual(consistency._parse_prefixes("summary.,quality."), ["summary.", "quality."])

    @patch("malody_api.scripts.check_stats_api_consistency.api_get")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_top_stabilizers_baseline")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_quality_baseline")
    @patch("malody_api.scripts.check_stats_api_consistency.calc_summary_baseline")
    def test_run_consistency_case(
        self,
        mock_summary,
        mock_quality,
        mock_top,
        mock_api_get,
    ):
        mock_summary.return_value = {"total_charts": 10, "unique_songs": 5, "unique_creators": 2}
        mock_quality.return_value = {
            "total_charts_checked": 10,
            "issues": {"missing_creator_name": 0, "missing_level": 0},
        }
        mock_top.return_value = [{"stabilizer_name": "Alice", "stable_count": 3}]
        mock_api_get.side_effect = [
            {"total_charts": 10, "unique_songs": 5, "unique_creators": 2},
            {"total_charts_checked": 10, "issues": {"missing_creator_name": {"count": 0}, "missing_level": {"count": 0}}},
            [{"stabilizer_name": "Alice", "stable_count": 3}],
        ]

        case = consistency.run_consistency_case(conn=None, base_url="http://localhost:8000", mode=0, limit=20)
        self.assertEqual(case["summary"]["failed_checks"], 0)
        self.assertEqual(case["summary"]["blocking_checks"], 0)
        self.assertEqual(case["mode"], 0)
        self.assertEqual(case["limit"], 20)

    def test_threshold_exceeded_not_blocking_when_prefix_not_selected(self):
        check = consistency.compare_values(
            name="summary.total_charts",
            baseline=100,
            api_value=103,
            default_threshold=1,
            threshold_rules={},
            block_on_prefixes=["quality."],
        )
        self.assertFalse(check["equal"])
        self.assertTrue(check["threshold_exceeded"])
        self.assertFalse(check["blocking"])

    def test_non_numeric_diff_is_exceeded_even_with_positive_threshold(self):
        check = consistency.compare_values(
            name="top_stabilizers.rank_pairs",
            baseline=[("Alice", 3)],
            api_value=[("Alice", 4)],
            default_threshold=10,
            threshold_rules={},
            block_on_prefixes=["top_stabilizers."],
        )
        self.assertFalse(check["equal"])
        self.assertTrue(check["threshold_exceeded"])
        self.assertTrue(check["blocking"])
