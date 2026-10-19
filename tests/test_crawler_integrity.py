"""Regression cases for the 2026-10 real-source crawler audit."""

from collections import deque
from contextlib import closing
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import asyncio
import os
import subprocess
import sys
import threading

from bs4 import BeautifulSoup
import requests

from crawlers import rankings
from crawlers.ingestion import (
    FetchList,
    TaskStore,
    atomic,
    atomic_json,
    ensure_schema,
    is_login_page,
    now,
    read_progress,
)
from crawlers.player_profile import PlayerProfileCrawler
from crawlers.stb import STBCrawler
from scripts import recrawl

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

FIXTURES = Path(__file__).parent / "fixtures/malody"


def response(body="", status=200, url="https://m.mugzone.net/"):
    result = Mock(text=body, content=body.encode(), status_code=status, url=url)
    result.raise_for_status.side_effect = (
        requests.HTTPError(str(status)) if status >= 400 else None
    )
    return result


class IntegrityCase(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        self.addCleanup(self.conn.close)
        self.manager = SimpleNamespace(get_connection=lambda: self.conn)
        self.database_patch = patch.object(
            rankings, "DatabaseManager", return_value=self.manager
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        rankings.init_database()
        self.chart = STBCrawler.__new__(STBCrawler)
        self.chart.db_manager = self.manager
        self.chart.logger = Mock()
        self.chart.crawl_stats = dict.fromkeys(
            ("new", "updated", "unchanged", "failed"), 0
        )
        self.chart.processed_charts = set()
        self.chart.processed_songs = set()
        self.chart.retry_queue = deque()
        self.chart._should_stop = Mock(return_value=False)
        self.chart._consume_skip = Mock(return_value=False)
        self.chart.init_database()
        self.chart.session = Mock()
        self.profile = PlayerProfileCrawler.__new__(PlayerProfileCrawler)
        self.profile.logger = Mock()
        self.profile.db_manager = self.manager
        self.profile.processed_uids = set()
        self.profile.rate_limiter = Mock()
        self.profile.session = Mock()
        self.profile.init_database()
        self.time = datetime(2026, 10, 18, 1, 0)

    def chart_data(self, **changes):
        data = dict(
            cid=17302,
            version="4K",
            level="10",
            mode=0,
            status=2,
            chart_length=137,
            recommend_count=100,
            not_recommend_count=4,
            comment_count=5,
            heat=200,
            _source="newapi",
            _complete=True,
        )
        data.update(changes)
        return data

    def song_data(self, **changes):
        data = dict(
            sid=4448,
            title="Song",
            artist="Artist",
            length=140,
            _source="newapi",
            _complete=True,
        )
        data.update(changes)
        return data

    def profile_data(self, **changes):
        data = dict(
            uid="1",
            current_name="Alice",
            gold=42,
            join_date="2020-01-01",
            titles=["A"],
            achievements=[{"code": 1}],
            _complete=True,
            _complete_groups=["titles", "achievements"],
        )
        data.update(changes)
        return data

    def test_identity_rename_stays_with_uid(self):
        first = rankings.resolve_player_identity("Alice", self.time, "1")
        second = rankings.resolve_player_identity(
            "Bob", self.time + timedelta(seconds=1), "1"
        )
        self.assertEqual(first, second)
        self.assertEqual(
            self.conn.execute(
                "SELECT alias FROM player_aliases ORDER BY alias"
            ).fetchall(),
            [("Alice",), ("Bob",)],
        )

    def test_identity_conflict_cannot_steal_uid(self):
        rankings.resolve_player_identity("Alice", self.time, "1")
        self.assertIsNone(rankings.resolve_player_identity("Alice", self.time, "2"))
        self.assertEqual(
            self.conn.execute("SELECT uid FROM player_identity").fetchall(), [("1",)]
        )

    def test_manual_alias_link_cannot_merge_different_uids(self):
        rankings.resolve_player_identity("Alice", self.time, "1")
        rankings.resolve_player_identity("Bob", self.time, "2")
        self.assertFalse(rankings.link_player_aliases("Alice", "Bob", self.time))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_identity").fetchone()[0], 2
        )

    def test_alias_is_not_a_current_name_match(self):
        rankings.resolve_player_identity("Alice", self.time, "1")
        rankings.resolve_player_identity("Bob", self.time + timedelta(seconds=1), "1")
        # Fault injection only: the source's old-name reuse policy is unverified.
        other = rankings.resolve_player_identity(
            "Alice", self.time + timedelta(seconds=2), "2"
        )
        self.assertIsNotNone(other)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_identity").fetchone()[0], 2
        )

    def test_identity_does_not_commit_outer_transaction(self):
        with self.assertRaises(ValueError):
            with atomic(self.conn):
                rankings.resolve_player_identity("Alice", self.time, "1")
                raise ValueError("after identity")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_identity").fetchone()[0], 0
        )

    def test_unique_source_identity_constraints(self):
        rankings.resolve_player_identity("Alice", self.time, "1")
        for uid, name in (("1", "Bob"), ("2", "Alice")):
            with self.assertRaises(sqlite3.IntegrityError), atomic(self.conn):
                self.conn.execute(
                    "INSERT INTO player_identity(uid,current_name,first_seen,last_seen) VALUES(?,?,?,?)",
                    (uid, name, self.time, self.time),
                )

    def test_old_identity_observation_cannot_undo_rename(self):
        rankings.resolve_player_identity("Bob", self.time, "1")
        rankings.resolve_player_identity("Alice", self.time - timedelta(seconds=1), "1")
        self.assertEqual(
            self.conn.execute("SELECT current_name FROM player_identity").fetchone()[0],
            "Bob",
        )

    def test_profile_missing_fields_and_lists_preserve_known_values(self):
        self.assertEqual(self.profile.save_player_profile(self.profile_data()), "new")
        partial = self.profile_data(
            gold=None, titles=[], achievements=[], _complete=False, _complete_groups=[]
        )
        self.profile.save_player_profile(partial)
        self.assertEqual(
            self.conn.execute("SELECT gold FROM player_profiles").fetchone()[0], 42
        )
        self.assertEqual(
            self.conn.execute("SELECT title FROM player_titles").fetchall(), [("A",)]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT achievement_code FROM player_achievements"
            ).fetchall(),
            [(1,)],
        )

    def test_complete_empty_lists_and_zero_are_applied(self):
        self.profile.save_player_profile(self.profile_data())
        self.profile.save_player_profile(
            self.profile_data(gold=0, titles=[], achievements=[])
        )
        self.assertEqual(
            self.conn.execute("SELECT gold FROM player_profiles").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_titles").fetchone()[0], 0
        )

    def test_stale_profile_cannot_remove_newer_collections(self):
        self.profile.save_player_profile(
            self.profile_data(_observed_at="2021-01-01T00:00:00")
        )
        self.profile.save_player_profile(
            self.profile_data(
                titles=[], achievements=[], _observed_at="2020-01-01T00:00:00"
            )
        )
        self.assertEqual(
            self.conn.execute("SELECT title FROM player_titles").fetchall(), [("A",)]
        )

    def test_profile_failure_rolls_back_record_and_lists(self):
        self.profile.save_player_profile(self.profile_data())
        self.conn.execute(
            "CREATE TRIGGER fail_achievement BEFORE INSERT ON player_achievements WHEN NEW.achievement_code=2 BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        self.conn.commit()
        self.assertIsNone(
            self.profile.save_player_profile(
                self.profile_data(gold=0, titles=["B"], achievements=[{"code": 2}])
            )
        )
        self.assertEqual(
            self.conn.execute("SELECT gold FROM player_profiles").fetchone()[0], 42
        )
        self.assertEqual(
            self.conn.execute("SELECT title FROM player_titles").fetchall(), [("A",)]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT success_count,error_count,needs_update FROM player_profile_crawl_status"
            ).fetchone(),
            (1, 1, 1),
        )

    def test_failed_initial_profile_leaves_no_business_rows(self):
        self.conn.execute(
            "CREATE TRIGGER fail_achievement BEFORE INSERT ON player_achievements BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        self.conn.commit()
        self.assertIsNone(self.profile.save_player_profile(self.profile_data()))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_profiles").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM crawl_observations WHERE section='failure'"
            ).fetchone()[0],
            1,
        )

    def test_achievement_first_seen_is_not_fabricated_acquired_date(self):
        self.profile.save_player_profile(self.profile_data())
        first = self.conn.execute(
            "SELECT acquired_date,first_observed_at FROM player_achievements"
        ).fetchone()
        self.profile.save_player_profile(self.profile_data())
        self.assertIsNone(first[0])
        self.assertIsNotNone(first[1])
        self.assertEqual(
            first,
            self.conn.execute(
                "SELECT acquired_date,first_observed_at FROM player_achievements"
            ).fetchone(),
        )

    def test_failed_ranking_rolls_back_entire_profile(self):
        html = (FIXTURES / "profile.html").read_text(encoding="utf-8")
        self.profile.fetch_player_profile = Mock(return_value=html)
        self.conn.execute(
            "CREATE TRIGGER fail_rank BEFORE INSERT ON player_rankings BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        self.conn.commit()
        self.assertFalse(self.profile.crawl_player_profile("100704"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_profiles").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_identity").fetchone()[0], 0
        )
        self.assertNotIn("100704", self.profile.processed_uids)

    def test_profile_save_failure_is_not_marked_done(self):
        self.profile.fetch_player_profile = Mock(
            return_value=(FIXTURES / "profile.html").read_text(encoding="utf-8")
        )
        self.profile.save_player_profile = Mock(return_value=None)
        self.assertFalse(self.profile.crawl_player_profile("100704"))
        self.assertNotIn("100704", self.profile.processed_uids)

    def test_known_uid_union_and_retry_due_selection(self):
        self.profile.save_player_profile(self.profile_data())
        rankings.resolve_player_identity("Bob", self.time, "2")
        with atomic(self.conn):
            self.conn.execute(
                "UPDATE player_profile_crawl_status SET needs_update=1,next_crawl_time=?",
                (datetime.now() + timedelta(days=1),),
            )
        self.assertEqual(self.profile.crawl_from_database(), ["2"])

    def test_batch_deduplicates_and_respects_failure_backoff(self):
        self.profile.crawl_player_profile = Mock(return_value=False)
        self.assertEqual(
            self.profile.crawl_players_batch(["1", "1"], max_workers=1), (0, 1)
        )
        self.assertEqual(self.profile.crawl_players_batch(["1"], max_workers=1), (0, 0))
        self.profile.crawl_player_profile.assert_called_once()

    def test_range_exit_and_bounded_chunks(self):
        self.profile.crawl_players_batch = Mock(return_value=(0, 0))
        self.profile.crawl_uid_range(1, 2100, max_workers=1)
        self.assertEqual(self.profile.crawl_players_batch.call_count, 3)
        self.assertEqual(
            [
                len(list(c.args[0]))
                for c in self.profile.crawl_players_batch.call_args_list
            ],
            [1000, 1000, 100],
        )

    def test_profile_stop_signal_sets_shared_stop_flag(self):
        import signal
        from crawlers.player_profile import signal_handler

        with patch.object(rankings, "stop_requested", False):
            signal_handler(signal.SIGTERM, None)
            self.assertTrue(rankings.is_stop_requested())

    def test_chart_partial_fields_do_not_replace_known_metadata(self):
        self.assertTrue(self.chart.save_chart_data(self.chart_data(), self.song_data()))
        self.assertTrue(
            self.chart.save_chart_data(
                self.chart_data(
                    chart_length=None,
                    recommend_count=0,
                    not_recommend_count=0,
                    _source="page_chart",
                ),
                self.song_data(title="Wrong", _source="page_chart"),
            )
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT chart_length,recommend_count,not_recommend_count FROM charts"
            ).fetchone(),
            (137, 0, 0),
        )
        self.assertEqual(
            self.conn.execute("SELECT title FROM songs").fetchone()[0], "Song"
        )

    def test_chart_song_identity_mismatch_rejected(self):
        self.assertFalse(
            self.chart.save_chart_data(self.chart_data(sid=99), self.song_data())
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM charts").fetchone()[0], 0
        )

    def test_new_unknown_chart_counters_are_null(self):
        data = self.chart_data(
            chart_length=None,
            recommend_count=None,
            not_recommend_count=None,
            comment_count=None,
        )
        self.chart.save_chart_data(data, self.song_data())
        self.assertEqual(
            self.conn.execute(
                "SELECT chart_length,recommend_count,not_recommend_count,comment_count FROM charts"
            ).fetchone(),
            (None, None, None, None),
        )

    def test_partial_comment_list_keeps_current_rows_and_summary(self):
        self.chart.save_chart_data(self.chart_data(), self.song_data())
        complete = FetchList(
            [{"tid": 1, "content": "old", "talk_type": 0}], complete=True
        )
        complete.generation = "old"
        self.chart.save_chart_data(self.chart_data(), self.song_data(), complete)
        partial = FetchList(
            [{"tid": 2, "content": "new", "talk_type": 0}], complete=False
        )
        partial.generation = "new"
        self.chart.save_chart_data(
            self.chart_data(comment_count=None), self.song_data(), partial
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM chart_comments WHERE is_current=1"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.conn.execute("SELECT comment_count FROM charts").fetchone()[0], 1
        )

    def test_complete_comment_generation_keeps_history_but_updates_current(self):
        self.chart.save_chart_data(self.chart_data(), self.song_data())
        for tid, generation in ((1, "old"), (2, "new")):
            items = FetchList(
                [{"tid": tid, "content": "text", "talk_type": 0}], complete=True
            )
            items.generation = generation
            self.chart.save_chart_data(self.chart_data(), self.song_data(), items)
        self.assertEqual(
            self.conn.execute(
                "SELECT tid,is_current FROM chart_comments ORDER BY tid"
            ).fetchall(),
            [(1, 0), (2, 1)],
        )
        self.assertEqual(
            self.conn.execute("SELECT comment_count FROM charts").fetchone()[0], 1
        )

    def test_duplicate_comment_ids_cannot_cross_charts(self):
        self.chart.save_chart_data(
            self.chart_data(), self.song_data(), [{"tid": 1, "content": "A"}]
        )
        self.assertFalse(
            self.chart.save_chart_data(
                self.chart_data(cid=2), self.song_data(), [{"tid": 1, "content": "B"}]
            )
        )
        self.assertEqual(
            self.conn.execute("SELECT cid,content FROM chart_comments").fetchone(),
            (17302, "A"),
        )

    def test_stale_comment_generation_cannot_replace_newer_list(self):
        fresh = FetchList([{"tid": 1, "content": "Fresh"}], complete=True)
        fresh.generation = "fresh"
        fresh.generation_started_at = "2021-01-01T00:00:00"
        self.assertTrue(
            self.chart.save_chart_data(self.chart_data(), self.song_data(), fresh)
        )
        stale = FetchList([], complete=True)
        stale.generation = "stale"
        stale.generation_started_at = "2020-01-01T00:00:00"
        self.assertFalse(
            self.chart.save_chart_data(self.chart_data(), self.song_data(), stale)
        )
        self.assertEqual(
            self.conn.execute("SELECT tid,is_current FROM chart_comments").fetchall(),
            [(1, 1)],
        )

    def test_old_metadata_cannot_replace_new_but_votes_can_decline(self):
        self.chart.save_chart_data(
            self.chart_data(last_updated="2026-10-18", _source_time="2026-10-18"),
            self.song_data(),
        )
        self.chart.save_chart_data(
            self.chart_data(
                version="old",
                last_updated="2026-10-17",
                _source_time="2026-10-17",
                recommend_count=90,
            ),
            self.song_data(),
        )
        self.assertEqual(
            self.conn.execute("SELECT version,recommend_count FROM charts").fetchone(),
            ("4K", 90),
        )

    def test_repeated_chart_save_does_not_invent_changes(self):
        self.chart.save_chart_data(
            self.chart_data(last_updated=self.time), self.song_data()
        )
        count = self.conn.execute("SELECT COUNT(*) FROM crawl_changes").fetchone()[0]
        self.chart.save_chart_data(
            self.chart_data(last_updated=self.time.isoformat()), self.song_data()
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM crawl_changes").fetchone()[0], count
        )

    def test_exp_common_precision_preserves_level_and_raw_accuracy(self):
        pid = rankings.resolve_player_identity("Alice", self.time, "1")
        rankings.save_player_ranking_record(
            pid, "1", 0, 1, "Alice", 74, 100, 99.4562586, 100, 20, self.time, "newapi"
        )
        op = rankings.save_player_ranking_record(
            pid,
            "1",
            0,
            1,
            "Alice",
            None,
            100,
            99.46,
            100,
            20,
            self.time + timedelta(seconds=1),
            "page_profile",
        )
        self.assertEqual(op, "same_insert")
        self.assertEqual(
            self.conn.execute(
                "SELECT lv,acc FROM player_rankings ORDER BY id DESC LIMIT 1"
            ).fetchone(),
            (74, 99.4562586),
        )

    def test_exp_replayed_same_observation_does_not_duplicate(self):
        pid = rankings.resolve_player_identity("Alice", self.time, "1")
        args = (
            pid,
            "1",
            0,
            1,
            "Alice",
            74,
            100,
            99.4562586,
            100,
            20,
            self.time,
            "newapi",
        )
        rankings.save_player_ranking_record(*args)
        rankings.save_player_ranking_record(*args)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_rankings").fetchone()[0], 1
        )

    def test_api_precision_changes_are_not_rounded_away(self):
        pid = rankings.resolve_player_identity("Alice", self.time, "1")
        rankings.save_player_ranking_record(
            pid,
            "1",
            0,
            1,
            "Alice",
            74,
            100,
            99.4562586,
            100,
            20,
            self.time,
            "newapi_ranking_global",
        )
        op = rankings.save_player_ranking_record(
            pid,
            "1",
            0,
            1,
            "Alice",
            74,
            100,
            99.4562188,
            100,
            20,
            self.time + timedelta(seconds=1),
            "newapi_ranking_global",
        )
        self.assertEqual(op, "diff_insert")

    def test_mm_missing_stats_preserve_known_values(self):
        pid = rankings.resolve_player_identity("Alice", self.time, "1")
        rankings.save_player_ranking_mm_record(
            pid, "1", 0, 1, "Alice", 100, 74, 99.4, 100, 20, self.time, "newapi"
        )
        rankings.save_player_ranking_mm_record(
            pid,
            "1",
            0,
            2,
            "Alice",
            90,
            None,
            None,
            None,
            None,
            self.time + timedelta(seconds=1),
            "newapi",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT lv,acc,combo,pc FROM player_rankings_mm ORDER BY id DESC LIMIT 1"
            ).fetchone(),
            (74, 99.4, 100, 20),
        )

    def test_mm_and_mmr_respect_outer_transaction(self):
        pid = rankings.resolve_player_identity("Alice", self.time, "1")
        with self.assertRaises(ValueError):
            with atomic(self.conn):
                rankings.save_player_ranking_mm_record(
                    pid, "1", 0, 1, "Alice", 100, 74, 99.4, 100, 20, self.time, "newapi"
                )
                rankings.save_player_mmr_sample(
                    pid, "1", 0, 3, 1, "Alice", self.time, "newapi"
                )
                raise ValueError("after save")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_rankings_mm").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM player_mmr_samples").fetchone()[0],
            0,
        )

    def test_real_chart_and_profile_parsers(self):
        for file, cid, status in [("alpha.html", 160725, 0), ("beta.html", 151903, 1)]:
            parsed, _ = self.chart.parse_chart_page(
                (FIXTURES / file).read_text(encoding="utf-8"), cid
            )
            self.assertEqual(parsed["status"], status)
        chart, song = self.chart.parse_chart_page(
            (FIXTURES / "chart.html").read_text(encoding="utf-8"), 17302
        )
        self.assertEqual(song["sid"], 4448)
        self.assertEqual(song["length"], 140)
        self.assertEqual(song["title"], "無人区-Vacuum Track#ADD8E6-")
        self.assertIsNone(chart["chart_length"])
        ranks = rankings.parse_player_profile(
            (FIXTURES / "profile.html").read_text(encoding="utf-8"), "100704"
        )
        self.assertTrue(ranks.complete)
        self.assertEqual(len(ranks), 6)
        self.assertIsNone(ranks[0]["lv"])

    def test_real_never_played_player_has_complete_empty_rankings(self):
        rows = rankings.parse_player_profile(
            (FIXTURES / "never.html").read_text(encoding="utf-8"), "1149101"
        )
        self.assertEqual(rows, [])
        self.assertTrue(rows.complete)

    def test_legacy_never_date_is_repaired_without_converter_failure(self):
        self.conn.execute(
            "INSERT INTO player_profiles(uid,current_name,last_play_date,last_crawled) VALUES('1149101','Jaow777','Never',?)",
            (self.time,),
        )
        self.conn.commit()
        data = self.profile.parse_player_profile_full(
            (FIXTURES / "never.html").read_text(encoding="utf-8"), "1149101"
        )
        self.assertIsNone(data["last_play_date"])
        self.assertEqual(self.profile.save_player_profile(data), "updated")
        self.assertIsNone(
            self.conn.execute("SELECT last_play_date FROM player_profiles").fetchone()[
                0
            ]
        )

    def test_malformed_profile_number_cannot_erase_known_value(self):
        html = (
            (FIXTURES / "never.html")
            .read_text(encoding="utf-8")
            .replace("Stable charts: 0", "Stable charts: N/A")
        )
        data = self.profile.parse_player_profile_full(html, "1149101")
        self.assertNotIn("stable_charts", data["_present"])

    def test_partial_or_wrong_id_page_is_rejected(self):
        html = (FIXTURES / "profile.html").read_text(encoding="utf-8")
        self.assertIsNone(self.profile.parse_player_profile_full(html, "2"))
        self.assertEqual(
            self.chart.parse_chart_page(
                (FIXTURES / "chart.html").read_text(encoding="utf-8"), 2
            ),
            (None, None),
        )
        self.assertIsNone(
            self.profile.parse_player_profile_full(
                '<div class="user_head"><div class="name"><span>A</span></div></div>',
                "1",
            )
        )

    def test_login_email_field_alone_does_not_mean_expired(self):
        self.assertFalse(is_login_page('<input name="email"><div>Latest charts</div>'))
        self.assertTrue(is_login_page('<div class="g_title">Sign in</div>'))

    def test_deleted_page_is_distinct_from_login_or_service_error(self):
        self.assertTrue(
            self.chart._is_confirmed_chart_deleted(
                response('<h1>404 Page Not Found</h1><input name="email">', 404)
            )
        )
        self.assertFalse(
            self.chart._is_confirmed_chart_deleted(response("<h1>503</h1>", 503))
        )
        self.assertFalse(
            self.chart._is_confirmed_chart_deleted(
                response('<div class="g_title">Sign in</div>', 404)
            )
        )

    def test_profile_auth_failure_is_explicit(self):
        self.profile.session.get.return_value = response(
            '<div class="g_title">Sign in</div>' + " " * 100,
            url="https://m.mugzone.net/accounts/login",
        )
        self.assertIsNone(self.profile.fetch_player_profile("1"))
        self.assertTrue(self.profile.auth_required_detected)

    def test_song_failure_is_not_a_complete_empty_list(self):
        self.chart.session.get.return_value = response("Unavailable", 503)
        result = self.chart.get_charts_from_song_page(4448)
        self.assertFalse(result.complete)

    def test_real_song_list_covers_all_chart_links(self):
        self.chart.session.get.return_value = response(
            (FIXTURES / "song.html").read_text(encoding="utf-8")
        )
        result = self.chart.get_charts_from_song_page(4448)
        self.assertTrue(result.complete)
        self.assertEqual(len(result), 219)
        self.assertIn(161112, result)
        self.assertIn(160725, result)

    def test_html_leaderboard_continues_through_verified_api_pagination(self):
        first = FetchList(
            [
                dict(
                    player_id=str(i),
                    rank=i,
                    name=f"Player{i}",
                    lv=1,
                    exp=1,
                    acc=99.0,
                    combo=1,
                    pc=1,
                )
                for i in range(1, 51)
            ],
            complete=True,
        )
        later = FetchList(
            [
                dict(
                    uid=i,
                    rank=i,
                    username=f"Player{i}",
                    level=1,
                    value=1,
                    acc=99.0,
                    combo=1,
                    playcount=1,
                )
                for i in range(1, 101)
            ],
            complete=False,
        )
        session = Mock()
        session.get.return_value = response("valid")
        with patch.object(
            rankings, "parse_player_list", return_value=first
        ), patch.object(rankings, "fetch_global_mode", return_value=later):
            frame = rankings.crawl_mode_player(session, 0, limit=75)
        self.assertEqual(len(frame), 75)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(frame.iloc[-1]["source"], "newapi_ranking_global")
        self.assertFalse(frame.attrs["complete"])

    def test_api_leaderboard_stalled_cursor_stays_incomplete(self):
        payload = {
            "code": 0,
            "data": [{"uid": 1, "rank": 1, "username": "A"}],
            "hasMore": True,
            "next": 0,
        }
        with patch.object(rankings, "_new_api_get", return_value=payload):
            rows = rankings.fetch_global_mode(Mock(), 0, limit=10)
        self.assertFalse(rows.complete)
        self.assertEqual(rows.error, "stalled_cursor")
        payload.pop("hasMore")
        with patch.object(rankings, "_new_api_get", return_value=payload):
            with self.assertRaises(RuntimeError):
                rankings.fetch_global_mode(Mock(), 0, 10)

    def test_source_same_rank_different_uid_is_not_discarded(self):
        rows = FetchList(
            [
                {"uid": 1, "rank": 2, "username": "Alice", "value": 100},
                {"uid": 2, "rank": 2, "username": "Bob", "value": 200},
            ],
            complete=True,
        )
        with patch.object(
            rankings, "fetch_global_mode", return_value=rows
        ), patch.object(rankings, "fetch_mm_global_mode", return_value=[]):
            frame, _ = rankings.crawl_mode_player_newapi(Mock(), 1, 10)
        self.assertEqual(set(frame["player_id"]), {"1", "2"})
        result = rankings.save_mm_ranking_rows(1, rows, self.time)
        self.assertEqual(result["saved_rows"], 2)
        self.assertEqual(result["dropped_dup_rank"], 0)

    def test_chart_search_uses_query_filters_instead_of_ignored_post_body(self):
        result = response("{}")
        result.json.return_value = {
            "code": 0,
            "data": {"list": [{"id": 151903}], "total": 89},
        }
        self.chart.session.get.return_value = result
        with patch.object(self.chart, "_has_auth_cookies", return_value=True):
            rows = self.chart.search_charts(mode=3, status=1, page=2)
        self.assertEqual(rows["list"][0]["id"], 151903)
        params = self.chart.session.get.call_args.kwargs["params"]
        self.assertEqual((params["mode"], params["status"], params["page"]), (3, 1, 2))
        self.assertNotIn("csrfmiddlewaretoken", params)
        self.chart.session.post.assert_not_called()

    def test_api_mmr_empty_success_is_distinct_from_missing_data(self):
        with patch.object(
            rankings, "_new_api_get", return_value={"code": 0, "data": []}
        ):
            self.assertTrue(rankings.fetch_player_mmr_from_api(Mock(), "1").complete)
        with patch.object(rankings, "_new_api_get", return_value={"code": 0}):
            with self.assertRaises(RuntimeError):
                rankings.fetch_player_mmr_from_api(Mock(), "1")

    def test_page_parser_real_sid_and_all_forty_ranks(self):
        from malody_api.routers.page_parser import PageParserService

        result = asyncio.run(
            PageParserService()._parse_chart_html(
                (FIXTURES / "chart.html").read_text(encoding="utf-8"), 17302
            )
        )
        self.assertEqual(result["chart_info"]["sid"], 4448)
        self.assertEqual([r["rank"] for r in result["ranking"]], list(range(1, 41)))

    def test_page_parser_mod_classes_preserve_unknown_codes(self):
        from malody_api.routers.page_parser import PageParserService

        node = BeautifulSoup(
            '<li><span class="mod"><i class="g_mod g_mod_4"></i><i class="g_mod g_mod_99"></i></span></li>',
            "html.parser",
        )
        self.assertEqual(PageParserService()._parse_mods(node), ["g_mod_4", "g_mod_99"])

    def test_source_filters_prevent_html_write_and_retry_queue(self):
        self.chart.mode_filter = [3]
        self.chart.session.get.return_value = response(
            (FIXTURES / "chart.html").read_text(encoding="utf-8")
        )
        self.assertFalse(self.chart.crawl_chart_detail_with_retry(17302))
        self.assertEqual(self.chart.last_fetch_state, "filtered")
        self.assertEqual(list(self.chart.retry_queue), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM charts").fetchone()[0], 0
        )

    def test_final_cid_retry_success_is_saved(self):
        with TemporaryDirectory() as directory, patch("crawlers.stb.time.sleep"):
            path = Path(directory) / "state.json"

            def first(cid, *args):
                self.chart.retry_queue.append((cid, 1))
                return False

            def final(*args):
                self.chart.retry_queue.clear()
                return 1

            self.chart.crawl_chart_detail_with_retry = Mock(side_effect=first)
            self.chart.process_retry_queue = Mock(side_effect=final)
            self.chart.crawl_cid_with_persistence(
                1, 1, progress_file=str(path), process_retry_every=50
            )
            self.assertEqual(read_progress(path)["retry_queue"], [])
            self.assertEqual(read_progress(path)["total_success"], 1)

    def test_foreign_key_catalog_extension_uses_actual_image(self):
        self.conn.execute(
            "CREATE TABLE achievement_catalog(code INTEGER PRIMARY KEY,img_url TEXT NOT NULL)"
        )
        self.conn.execute("DROP TABLE player_achievements")
        self.conn.execute(
            "CREATE TABLE player_achievements(uid TEXT,achievement_code INTEGER,acquired_date TIMESTAMP,first_observed_at TEXT,PRIMARY KEY(uid,achievement_code),FOREIGN KEY(uid) REFERENCES player_profiles(uid),FOREIGN KEY(achievement_code) REFERENCES achievement_catalog(code))"
        )
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=ON")
        data = self.profile_data(
            achievements=[{"code": 2, "image_url": "https://example.test/achieve/2"}]
        )
        self.assertEqual(self.profile.save_player_profile(data), "new")
        self.assertEqual(
            self.conn.execute("SELECT img_url FROM achievement_catalog").fetchone()[0],
            "https://example.test/achieve/2",
        )

    def test_song_retry_processes_all_children_before_success(self):
        with TemporaryDirectory() as directory, patch("crawlers.stb.time.sleep"):
            progress = Path(directory) / "progress.json"
            atomic_json(progress, {"failed_songs": [4448]})
            self.chart.get_charts_from_song_page = Mock(
                return_value=FetchList([1, 2, 3], complete=True)
            )
            self.chart.crawl_chart_detail_with_retry = Mock(
                side_effect=[True, False, True]
            )
            good, total = self.chart.retry_failed_items([str(progress)])
            self.assertEqual((good, total), (0, 1))
            self.assertEqual(self.chart.crawl_chart_detail_with_retry.call_count, 3)
            self.assertEqual(read_progress(progress)["failed_songs"], [4448])

    def test_retry_stop_does_not_discard_pending_tasks(self):
        self.chart.retry_queue = deque([(1, 1), (2, 1)])
        self.chart._should_stop.return_value = True
        self.chart.process_retry_queue(0)
        self.assertEqual(list(self.chart.retry_queue), [(1, 1), (2, 1)])

    def test_backwards_service_failure_does_not_advance_or_count_404(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.chart.set_api_rate_limit = Mock()
            self.chart.get_charts_from_song_page = Mock(
                return_value=FetchList(error="503")
            )
            self.chart.crawl_sid_backwards(start_sid=8, progress_file=str(path))
            saved = read_progress(path)
            self.assertEqual(saved["current_sid"], 8)
            self.assertEqual(saved["consecutive_404s"], 0)

    def test_talk_boundary_second_overlaps_and_deduplicates(self):
        def page(items, more):
            r = response()
            r.json.return_value = {"list": items, "next": more}
            return r

        self.chart.session.get.side_effect = [
            page([{"tid": 3, "time": 100}, {"tid": 2, "time": 99}], True),
            page([{"tid": 2, "time": 99}, {"tid": 1, "time": 99}], False),
        ]
        rows = self.chart._fetch_chart_talk_items(17302)
        self.assertTrue(rows.complete)
        self.assertEqual([r["tid"] for r in rows], [3, 2, 1])
        self.assertEqual(
            self.chart.session.get.call_args.kwargs["params"]["start"], 100
        )

    def test_talk_same_second_stall_stays_partial(self):
        r = response()
        r.json.return_value = {"list": [{"tid": 1, "time": 100}], "next": True}
        self.chart.session.get.return_value = r
        rows = self.chart._fetch_chart_talk_items(17302)
        self.assertFalse(rows.complete)
        self.assertEqual(rows.error, "ambiguous_time_cursor")

    def test_live_talk_empty_success_is_complete(self):
        r = response()
        r.json.return_value = {"code": 0}  # Live CID 156762; no comments.
        self.chart.session.get.return_value = r
        rows = self.chart._fetch_chart_talk_items(156762)
        self.assertTrue(rows.complete)
        self.assertEqual(list(rows), [])
        self.assertIsNone(rows.error)
        self.assertIsNone(rows.cursor)

    def test_live_talk_terminal_page_can_omit_next(self):
        first, last = response(), response()
        first.json.return_value = {
            "code": 0,
            "data": {"list": [{"tid": 2, "time": 100}], "next": True},
        }
        # Same terminal envelope as live CID 151181, following a nonterminal page.
        last.json.return_value = {"code": 0, "data": {"list": [{"tid": 1, "time": 99}]}}
        self.chart.session.get.side_effect = [first, last]
        rows = self.chart._fetch_chart_talk_items(151181)
        self.assertTrue(rows.complete)
        self.assertEqual([item["tid"] for item in rows], [2, 1])
        self.assertIsNone(rows.cursor)

    def test_unknown_talk_shape_stays_partial_and_reports_failure(self):
        self.chart.logger = logging.getLogger("STBCrawler")
        r = response()
        r.json.return_value = {"code": 0, "data": {"unexpected": True}}
        self.chart.session.get.return_value = r
        with self.assertLogs("STBCrawler", level="INFO") as captured:
            rows = self.chart._fetch_chart_talk_items(17302)
        self.assertFalse(rows.complete)
        self.assertEqual(rows.error, "Missing talk list")
        self.assertIn("尚未抓全", "\n".join(captured.output))

    def test_slow_request_reports_wait_and_completion_without_exposing_keys(self):
        messages = []
        heartbeat = threading.Event()

        def log(message, *args):
            rendered = message % args
            messages.append(rendered)
            if "仍在等待" in rendered:
                heartbeat.set()

        self.chart.logger.info.side_effect = log
        received = response()

        def fetch(*args, **kwargs):
            self.assertIn("开始请求", messages[0])
            self.assertTrue(
                heartbeat.wait(2), "A slow request must emit progress before returning"
            )
            return received

        self.chart.session.get.side_effect = fetch
        url = "https://api.mugzone.net/api/community/chart/info?key=example-private-key"
        with patch("crawlers.stb.REQUEST_PROGRESS_INTERVAL_SECONDS", 0.01):
            self.assertIs(
                self.chart._get_with_progress("谱面 CID=17302", url, timeout=30),
                received,
            )
        self.assertIn("收到响应", messages[-1])
        self.assertNotIn("example-private-key", "\n".join(messages))
        self.assertFalse(
            any(t.name == "stb-request-progress" for t in threading.enumerate())
        )

    def test_newapi_failure_is_visible_and_remains_in_retry_queue(self):
        self.chart.logger = logging.getLogger("STBCrawler")
        self.chart._new_api_ensure_guest_auth = Mock()

        def api(path, params=None, **kwargs):
            if path == "/store/list2":
                return {"code": 0, "data": [{"sid": 4448}], "hasMore": False}
            if path == "/community/song/charts":
                return {"code": 0, "data": [{"cid": 17302, "mode": 0, "type": 0}]}
            raise requests.ReadTimeout("Request failed: ?key=example-private-key")

        self.chart._new_api_get = Mock(side_effect=api)
        with self.assertLogs("STBCrawler", level="INFO") as captured:
            self.assertEqual(self.chart.crawl_from_new_api(max_charts=1), 0)
        output = "\n".join(captured.output)
        for expected in ("17302", "ReadTimeout", "60 秒后可重试", "本轮结束", "retry"):
            self.assertIn(expected, output)
        self.assertNotIn("example-private-key", output)
        self.assertEqual(
            self.conn.execute(
                "SELECT state,last_error FROM crawl_tasks WHERE kind='chart'"
            ).fetchone(),
            ("retry", "ReadTimeout"),
        )

    def test_newapi_limit_persists_all_children_and_cursor(self):
        self.chart._new_api_ensure_guest_auth = Mock()

        def api(path, params=None, **kwargs):
            if path == "/store/list2":
                return {"code": 0, "data": [{"sid": 4448}], "next": 1, "hasMore": False}
            if path == "/community/song/charts":
                return {
                    "code": 0,
                    "data": [{"cid": i, "mode": 0, "type": 0} for i in range(1, 220)],
                }
            if path == "/community/chart/info":
                return {"code": 0, "cid": params["cid"]}
            if path == "/community/song/info":
                return {"code": 0, "sid": 4448}
            raise AssertionError(path)

        self.chart._new_api_get = Mock(side_effect=api)
        self.chart.get_charts_from_song_page = Mock(
            return_value=FetchList(complete=True)
        )
        saved = []

        def save(info, *args):
            saved.append(info["cid"])
            self.chart.last_social_complete = True
            return True

        self.chart._save_chart_data_from_new_api = Mock(side_effect=save)
        for _ in range(22):
            self.chart.crawl_from_new_api(max_charts=10, modes=[0], statuses=[0])
        self.assertEqual(len(saved), 219)
        self.assertEqual(len(set(saved)), 219)
        self.assertEqual(
            self.chart._new_api_get.call_args_list[0].args[0], "/store/list2"
        )


class DurableTasksCase(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.store = TaskStore(self.conn, "one")

    def test_task_dedup_and_scope_isolation(self):
        with atomic(self.conn):
            self.store.add("chart", 1)
            self.store.add("chart", 1)
        self.assertEqual(len(self.store.claim(10)), 1)
        other = TaskStore(self.conn, "two")
        self.assertEqual(other.claim(), [])

    def test_crash_lease_can_be_reclaimed(self):
        with atomic(self.conn):
            self.store.add("chart", 1)
        self.assertEqual(len(self.store.claim(1, lease_seconds=-1)), 1)
        self.assertEqual(len(self.store.claim()), 1)
        self.assertEqual(
            self.conn.execute("SELECT attempts FROM crawl_tasks").fetchone()[0], 2
        )

    def test_expired_worker_cannot_acknowledge_another_workers_lease(self):
        with atomic(self.conn):
            self.store.add("chart", 1)
        self.store.claim(lease_seconds=-1)
        other = TaskStore(self.conn, "one")
        other.claim()
        self.assertFalse(self.store.finish("chart", 1))
        self.assertEqual(other.counts(), {"running": 1})
        self.assertTrue(other.finish("chart", 1))

    def test_retry_backoff_prevents_immediate_replay(self):
        with atomic(self.conn):
            self.store.add("chart", 1)
        self.store.claim()
        self.store.finish("chart", 1, state="retry", retry_seconds=3600)
        self.assertEqual(self.store.claim(), [])

    def test_done_is_not_reenqueued_by_discovery(self):
        with atomic(self.conn):
            self.store.add("chart", 1)
        self.store.claim()
        self.store.finish("chart", 1)
        with atomic(self.conn):
            self.store.add("chart", 1)
        self.assertEqual(self.store.claim(), [])

    def test_corrupt_progress_is_preserved_and_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                read_progress(path)
            self.assertEqual(path.read_text(), "{broken")

    def test_schema_migration_is_idempotent(self):
        self.conn.execute("CREATE TABLE charts(cid INTEGER PRIMARY KEY)")
        with atomic(self.conn):
            ensure_schema(self.conn)
            ensure_schema(self.conn)
        self.assertIn(
            "checksum",
            {row[1] for row in self.conn.execute("PRAGMA table_info(charts)")},
        )

    def test_mm_stale_file_recovers_and_live_owner_blocks_second_process(self):
        with TemporaryDirectory() as directory, patch.object(
            rankings, "MM_RUN_LOCK_FILE", str(Path(directory) / "mm.lock")
        ):
            Path(rankings.MM_RUN_LOCK_FILE).write_text('{"pid":99999999}')
            self.assertTrue(rankings._acquire_mm_run_lock())
            try:
                code = "from crawlers import rankings; import sys; rankings.MM_RUN_LOCK_FILE=sys.argv[1]; print('LOCK_RESULT',rankings._acquire_mm_run_lock())"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-c",
                        code,
                        rankings.MM_RUN_LOCK_FILE,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("LOCK_RESULT False", result.stdout)
            finally:
                rankings._release_mm_run_lock()
            self.assertTrue(rankings._acquire_mm_run_lock())
            rankings._release_mm_run_lock()


class ManualRecrawlCase(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        with closing(sqlite3.connect(self.source)) as conn:
            conn.executescript(
                "CREATE TABLE charts(cid INTEGER PRIMARY KEY);INSERT INTO charts VALUES(2);CREATE TABLE songs(sid INTEGER PRIMARY KEY);INSERT INTO songs VALUES(1);CREATE TABLE player_profiles(uid TEXT PRIMARY KEY);INSERT INTO player_profiles VALUES('3');"
            )
        self.original = recrawl.digest(self.source)

    def test_prepare_is_isolated_and_network_free(self):
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No requests permitted"),
        ):
            manifest = recrawl.prepare(
                self.source, self.root / "batch", known_only=True
            )
            result = recrawl.status(self.root / "batch")
        self.assertEqual(recrawl.digest(self.source), self.original)
        self.assertTrue(manifest["manual_start_required"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["tasks"]["pending"], 23)

    def test_player_script_help_runs_from_project_root(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "crawlers/player_profile.py", "--help"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--from-db", result.stdout)

    def test_full_coverage_requires_explicit_verified_bounds(self):
        with self.assertRaises(ValueError):
            recrawl.prepare(self.source, self.root / "batch")
        self.assertFalse((self.root / "batch").exists())
        with self.assertRaises(ValueError):
            recrawl.prepare(
                self.source, self.root / "batch", uid_max=2, sid_max=1, cid_max=2
            )

    def test_range_feeding_is_bounded_and_recoverable(self):
        recrawl.prepare(
            self.source,
            self.root / "batch",
            uid_max=10000,
            sid_max=10000,
            cid_max=10000,
        )
        with closing(recrawl.open_db(self.root / "batch/data.db")) as conn:
            recrawl.feed_ranges(conn, count=10)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0], 20
            )
            conn.execute("UPDATE crawl_tasks SET state='done'")
            conn.commit()
            recrawl.feed_ranges(conn, count=10)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM crawl_tasks WHERE state='pending'"
                ).fetchone()[0],
                30,
            )
            recrawl.feed_ranges(conn, count=10)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM crawl_tasks WHERE state='pending'"
                ).fetchone()[0],
                30,
            )

    def test_manual_run_uses_stage_database_and_leaves_source_unchanged(self):
        source = self.root / "full.db"
        rankings.DatabaseManager().close_connection()
        with patch.object(rankings, "DB_FILE", str(source)), patch.dict(
            os.environ, {}, clear=False
        ):
            rankings.init_database()
            profiles = PlayerProfileCrawler(session=Mock())
            profiles.save_player_profile(
                {"uid": "3", "current_name": "Player", "_complete": True}
            )
            charts = STBCrawler.__new__(STBCrawler)
            charts.db_manager = rankings.DatabaseManager()
            charts.logger = Mock()
            charts.init_database()
            rankings.DatabaseManager().close_connection()
            original = recrawl.digest(source)
            recrawl.prepare(source, self.root / "batch", known_only=True)
            with patch.object(
                PlayerProfileCrawler, "crawl_player_profile", return_value=True
            ), patch.object(STBCrawler, "_start_summary_hotkey_listener"), patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("Unexpected request"),
            ):
                result = recrawl.run(self.root / "batch", max_tasks=1)
            self.assertEqual(result["tasks"]["done"], 1)
            self.assertEqual(recrawl.digest(source), original)
            self.assertFalse(result["complete"])
            with closing(recrawl.open_db(self.root / "batch/data.db")) as conn:
                conn.execute("UPDATE crawl_tasks SET state='done'")
                conn.execute(
                    "INSERT INTO player_identity(uid,current_name,first_seen,last_seen) VALUES('99','New',?,?)",
                    (now(), now()),
                )
                conn.execute(
                    "UPDATE sqlite_sequence SET seq=99 WHERE name='player_identity'"
                )
                conn.commit()
            self.assertTrue(recrawl.publish(self.root / "batch")["published"])
            with closing(recrawl.open_db(source)) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT seq FROM sqlite_sequence WHERE name='player_identity'"
                    ).fetchone()[0],
                    99,
                )

    def finish_batch(self):
        recrawl.prepare(self.source, self.root / "batch", known_only=True)
        with closing(recrawl.open_db(self.root / "batch/data.db")) as conn:
            conn.execute("UPDATE crawl_tasks SET state='done'")
            conn.commit()

    def test_incomplete_batch_cannot_publish(self):
        recrawl.prepare(self.source, self.root / "batch", known_only=True)
        with self.assertRaises(ValueError):
            recrawl.publish(self.root / "batch")
        self.assertEqual(recrawl.digest(self.source), self.original)

    def test_publish_refuses_concurrent_source_change(self):
        self.finish_batch()
        with closing(recrawl.open_db(self.source)) as conn:
            conn.execute("INSERT INTO charts VALUES(99)")
            conn.commit()
        with self.assertRaisesRegex(ValueError, "Source data changed"):
            recrawl.publish(self.root / "batch")
        with closing(recrawl.open_db(self.source)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM charts").fetchone()[0], 2
            )

    def test_failed_publish_rolls_back_schema_and_all_data(self):
        with closing(recrawl.open_db(self.source)) as conn:
            conn.execute(
                "CREATE TRIGGER reject_chart BEFORE INSERT ON charts WHEN NEW.cid=3 BEGIN SELECT RAISE(ABORT,'reject'); END"
            )
            conn.commit()
        self.finish_batch()
        with closing(recrawl.open_db(self.root / "batch/data.db")) as conn:
            conn.execute("DROP TRIGGER reject_chart")
            conn.execute("INSERT INTO charts(cid) VALUES(3)")
            conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            recrawl.publish(self.root / "batch")
        with closing(recrawl.open_db(self.source)) as conn:
            self.assertEqual(conn.execute("SELECT cid FROM charts").fetchall(), [(2,)])
            self.assertEqual(
                [r[1] for r in conn.execute("PRAGMA table_info(charts)")], ["cid"]
            )

    def test_publish_preserves_old_rows_and_applies_staged_additions(self):
        self.finish_batch()
        with closing(recrawl.open_db(self.root / "batch/data.db")) as conn:
            conn.execute("INSERT INTO charts(cid) VALUES(3)")
            conn.commit()
        self.assertTrue(recrawl.publish(self.root / "batch")["published"])
        with closing(recrawl.open_db(self.source)) as conn:
            self.assertEqual(
                conn.execute("SELECT cid FROM charts ORDER BY cid").fetchall(),
                [(2,), (3,)],
            )

    def test_report_includes_outstanding_tasks_without_network(self):
        recrawl.prepare(self.source, self.root / "batch", known_only=True)
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Unexpected request"),
        ):
            result = recrawl.report(self.root / "batch")
        self.assertFalse(result["complete"])
        self.assertTrue((self.root / "batch/exceptions.csv").exists())
