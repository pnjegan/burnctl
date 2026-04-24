"""Tests for baseline_scanner.py and db baseline helpers.

Run: python3 -m unittest tests.test_baseline_scanner -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

# Ensure project root on sys.path (mirrors other tests)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestEstimateTokens(unittest.TestCase):
    def test_empty_string(self):
        from baseline_scanner import estimate_tokens
        self.assertEqual(estimate_tokens(""), 0)

    def test_known_text(self):
        from baseline_scanner import estimate_tokens
        # "hello world" should produce a positive, small token count whether
        # tiktoken is used or the char approx fallback.
        result = estimate_tokens("hello world")
        self.assertGreater(result, 0)
        self.assertLess(result, 20)

    def test_char_approx_fallback(self):
        """When tiktoken is unavailable, estimate_tokens uses len * 0.25."""
        import baseline_scanner
        # Force fallback regardless of tiktoken availability
        text = "a" * 400  # 400 * 0.25 = 100
        with mock.patch.object(baseline_scanner, "TIKTOKEN_AVAILABLE", False):
            self.assertEqual(baseline_scanner.estimate_tokens(text), 100)


class TestScanBaseline(unittest.TestCase):
    def test_returns_required_keys(self):
        from baseline_scanner import scan_baseline
        result = scan_baseline()
        self.assertIn("timestamp", result)
        self.assertIn("total_tokens", result)
        self.assertIn("sources", result)
        self.assertIsInstance(result["sources"], list)
        self.assertIsInstance(result["total_tokens"], int)

    def test_total_matches_sum(self):
        from baseline_scanner import scan_baseline
        result = scan_baseline()
        calculated = sum(int(s.get("tokens") or 0) for s in result["sources"])
        self.assertEqual(result["total_tokens"], calculated)

    def test_no_crash_on_missing_dirs(self):
        """scan_baseline must return a valid dict even if ~/.claude dirs
        don't exist — it points at missing paths and each internal scanner
        skips silently."""
        import baseline_scanner
        # Also stub BURNCTL_PROJECT_ROOTS so v4.5.3 E-01 project-root walk
        # can't accidentally find real CLAUDE.md files on the test host.
        with mock.patch.object(baseline_scanner, "AGENTS_DIR", "/nonexistent/agents"), \
             mock.patch.object(baseline_scanner, "SKILLS_DIR", "/nonexistent/skills"), \
             mock.patch.object(baseline_scanner, "GLOBAL_CLAUDEMD", "/nonexistent/CLAUDE.md"), \
             mock.patch.object(baseline_scanner, "PROJECTS_DIR", "/nonexistent/projects"), \
             mock.patch.object(baseline_scanner, "MCP_CONFIG_CANDIDATES", ["/nonexistent/x.json"]), \
             mock.patch.object(baseline_scanner, "_DEFAULT_PROJECT_PARENTS", ["/nonexistent/projects-parent"]), \
             mock.patch.dict(os.environ, {"BURNCTL_PROJECT_ROOTS": ""}, clear=False):
            result = baseline_scanner.scan_baseline()
        self.assertIsNotNone(result)
        self.assertEqual(result["total_tokens"], 0)
        self.assertEqual(result["sources"], [])

    def test_source_schema(self):
        from baseline_scanner import scan_baseline
        result = scan_baseline()
        for source in result["sources"]:
            self.assertIn("type", source)
            self.assertIn("name", source)
            self.assertIn("tokens", source)
            self.assertIn(source["type"], ["agent", "skill", "mcp", "claudemd"])
            self.assertIsInstance(source["tokens"], int)


class TestDbBaselineHelpers(unittest.TestCase):
    """DB helpers operate on an isolated temp DB per test."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = os.path.join(self.tmpdir.name, "usage.db")
        import db as _db
        self._orig_db_path = _db.DB_PATH
        _db.DB_PATH = self.tmp_db
        _db.init_db()

    def tearDown(self):
        import db as _db
        _db.DB_PATH = self._orig_db_path
        self.tmpdir.cleanup()

    def test_insert_and_latest(self):
        from db import insert_baseline_reading, get_latest_baseline
        sources = [{"type": "agent", "name": "t", "tokens": 100}]
        rid = insert_baseline_reading("2026-04-24T09:00:00", 100, sources)
        self.assertIsInstance(rid, int)
        latest = get_latest_baseline()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["total_tokens"], 100)
        self.assertEqual(latest["snapshot_date"], "2026-04-24")
        self.assertEqual(latest["sources"], sources)

    def test_previous_baseline(self):
        from db import insert_baseline_reading, get_previous_baseline, get_latest_baseline
        insert_baseline_reading("2026-04-23T09:00:00", 100, [])
        insert_baseline_reading("2026-04-24T09:00:00", 200, [])
        self.assertEqual(get_latest_baseline()["total_tokens"], 200)
        self.assertEqual(get_previous_baseline()["total_tokens"], 100)

    def test_readings_dedup_by_day(self):
        """get_baseline_readings returns latest-per-day, newest first."""
        from db import insert_baseline_reading, get_baseline_readings
        insert_baseline_reading("2026-04-22T09:00:00", 50, [])
        insert_baseline_reading("2026-04-23T09:00:00", 100, [])
        insert_baseline_reading("2026-04-23T18:00:00", 150, [])  # same day, later
        insert_baseline_reading("2026-04-24T09:00:00", 200, [])
        rows = get_baseline_readings(days=14)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["snapshot_date"], "2026-04-24")
        self.assertEqual(rows[1]["snapshot_date"], "2026-04-23")
        self.assertEqual(rows[1]["total_tokens"], 150)  # took latest for that day

    def test_prune_deletes_rows_older_than_cutoff(self):
        """v4.5.3 M-2: prune_old_baseline_readings honours the days cutoff."""
        from db import insert_baseline_reading, prune_old_baseline_readings, get_conn
        import datetime
        old = (datetime.date.today() - datetime.timedelta(days=100)).isoformat() + "T00:00:00"
        recent = datetime.datetime.now().isoformat()
        insert_baseline_reading(old, 999, [])      # 100 days old
        insert_baseline_reading(recent, 1000, [])  # today
        deleted = prune_old_baseline_readings(days=90)
        self.assertEqual(deleted, 1)
        conn = get_conn()
        try:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM baseline_readings"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(remaining, 1)

    def test_prune_on_empty_table_is_safe(self):
        """Running prune on an empty table returns 0, does not crash."""
        from db import prune_old_baseline_readings
        self.assertEqual(prune_old_baseline_readings(days=90), 0)


class TestBaselineInsights(unittest.TestCase):
    """The 4 v4.5.0 rules fire under expected conditions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = os.path.join(self.tmpdir.name, "usage.db")
        import db as _db
        self._orig_db_path = _db.DB_PATH
        _db.DB_PATH = self.tmp_db
        _db.init_db()

    def tearDown(self):
        import db as _db
        _db.DB_PATH = self._orig_db_path
        self.tmpdir.cleanup()

    def _count_insights(self, insight_type):
        from db import get_conn
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM insights WHERE insight_type = ?",
                (insight_type,),
            ).fetchone()
            return row[0]
        finally:
            conn.close()

    def test_sos_spike_fires_on_large_increase(self):
        from db import insert_baseline_reading
        from insights import generate_insights
        insert_baseline_reading("2026-04-23T09:00:00", 10000,
                                [{"type": "agent", "name": "a", "tokens": 10000}])
        insert_baseline_reading("2026-04-24T09:00:00", 14000,
                                [{"type": "agent", "name": "a", "tokens": 10000},
                                 {"type": "agent", "name": "b", "tokens": 4000}])
        generate_insights()
        self.assertGreaterEqual(self._count_insights("baseline_sos_spike"), 1)

    def test_sos_spike_quiet_on_small_change(self):
        from db import insert_baseline_reading
        from insights import generate_insights
        insert_baseline_reading("2026-04-23T09:00:00", 10000, [])
        insert_baseline_reading("2026-04-24T09:00:00", 10400, [])  # 4% up
        generate_insights()
        self.assertEqual(self._count_insights("baseline_sos_spike"), 0)

    def test_claudemd_bloat_fires_above_threshold(self):
        from db import insert_baseline_reading
        from insights import generate_insights
        # single CLAUDE.md source at 3000 tokens — above 2000 threshold
        insert_baseline_reading(
            "2026-04-24T09:00:00", 3000,
            [{"type": "claudemd", "name": "~/.claude/CLAUDE.md",
              "path": "/root/.claude/CLAUDE.md", "tokens": 3000}],
        )
        generate_insights()
        self.assertGreaterEqual(self._count_insights("claudemd_bloat"), 1)

    def test_claudemd_bloat_quiet_below_threshold(self):
        from db import insert_baseline_reading
        from insights import generate_insights
        insert_baseline_reading(
            "2026-04-24T09:00:00", 1500,
            [{"type": "claudemd", "name": "CLAUDE.md",
              "path": "/x/CLAUDE.md", "tokens": 1500}],
        )
        generate_insights()
        self.assertEqual(self._count_insights("claudemd_bloat"), 0)


class TestDailyReport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = os.path.join(self.tmpdir.name, "usage.db")
        import db as _db
        self._orig_db_path = _db.DB_PATH
        _db.DB_PATH = self.tmp_db
        _db.init_db()

    def tearDown(self):
        import db as _db
        _db.DB_PATH = self._orig_db_path
        self.tmpdir.cleanup()

    def test_brief_returns_expected_keys(self):
        from daily_report import build_daily_brief
        b = build_daily_brief()
        for key in ("date", "weekday", "baseline", "runtime",
                    "recommendations", "trends", "last_outcome"):
            self.assertIn(key, b)

    def test_brief_handles_empty_db(self):
        from daily_report import build_daily_brief
        b = build_daily_brief()
        self.assertFalse(b["baseline"].get("available"))
        self.assertEqual(b["recommendations"], [])
        self.assertIsNone(b["last_outcome"])

    def test_cost_label_plan_user(self):
        """Max/Pro/Team users should see 'API EQUIV TODAY', not 'EST. DAILY COST'."""
        from db import get_conn
        from daily_report import build_daily_brief
        conn = get_conn()
        conn.execute(
            "INSERT INTO accounts (account_id,label,plan,monthly_cost_usd,"
            "window_token_limit,color,data_paths,active,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("p1", "Personal (Max)", "max", 100.0, 1000000, "#fff", "[]", 1, 0),
        )
        conn.commit()
        conn.close()
        b = build_daily_brief()
        self.assertEqual(b["runtime"].get("cost_label"), "API EQUIV TODAY")
        self.assertIn("Max plan", b["runtime"].get("cost_note", ""))

    def test_cost_label_api_user(self):
        """API-only users should see the default 'EST. DAILY COST' label."""
        from db import get_conn
        from daily_report import build_daily_brief
        conn = get_conn()
        # init_db seeds config.ACCOUNTS (which includes a 'max' account) —
        # wipe that so this test reflects a pure API-only user.
        conn.execute("DELETE FROM accounts")
        conn.execute(
            "INSERT INTO accounts (account_id,label,plan,monthly_cost_usd,"
            "window_token_limit,color,data_paths,active,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("a1", "Work (API)", "api", 0.0, 1000000, "#fff", "[]", 1, 0),
        )
        conn.commit()
        conn.close()
        b = build_daily_brief()
        self.assertEqual(b["runtime"].get("cost_label"), "EST. DAILY COST")
        self.assertEqual(b["runtime"].get("cost_note", ""), "")


if __name__ == "__main__":
    unittest.main()
