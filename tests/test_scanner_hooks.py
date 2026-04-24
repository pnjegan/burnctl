"""Integration tests for scanner end-of-run hooks.

Covers:
  - scanner._capture_daily_baseline — once-per-day idempotency + wiring
  - scanner._populate_daily_snapshots — aggregates sessions into daily_snapshots

Each test uses an isolated temp DB so no real data is touched.

Run: python3 -m unittest tests.test_scanner_hooks -v
"""
import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _IsolatedDbCase(unittest.TestCase):
    """Redirects db.DB_PATH to a temp file and initialises the schema."""

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


class TestCaptureDailyBaseline(_IsolatedDbCase):

    def test_baseline_written_on_first_call(self):
        """_capture_daily_baseline writes exactly one row on first call."""
        from db import get_conn, get_baseline_readings
        import scanner

        # Fake scan_baseline to return deterministic data so we don't
        # depend on ~/.claude/ contents in CI.
        fake = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "total_tokens": 1234,
            "sources": [{"type": "agent", "name": "t", "path": "/tmp/t.md",
                          "tokens": 1234, "last_modified": ""}],
        }
        conn = get_conn()
        try:
            with mock.patch("baseline_scanner.scan_baseline", return_value=fake):
                scanner._capture_daily_baseline(conn)
            readings = get_baseline_readings(days=1, conn=conn)
        finally:
            conn.close()
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0]["total_tokens"], 1234)

    def test_baseline_idempotent_within_day(self):
        """Second call on the same UTC day must NOT add a second row."""
        from db import get_conn, get_baseline_readings
        import scanner

        today_iso = datetime.date.today().isoformat()
        fake1 = {
            "timestamp": f"{today_iso}T08:00:00",
            "total_tokens": 1000,
            "sources": [{"type": "agent", "name": "a", "path": "/tmp/a.md",
                          "tokens": 1000, "last_modified": ""}],
        }
        fake2 = {
            "timestamp": f"{today_iso}T12:00:00",
            "total_tokens": 2000,  # would differ if written
            "sources": [{"type": "agent", "name": "a", "path": "/tmp/a.md",
                          "tokens": 2000, "last_modified": ""}],
        }
        conn = get_conn()
        try:
            with mock.patch("baseline_scanner.scan_baseline", return_value=fake1):
                scanner._capture_daily_baseline(conn)
            with mock.patch("baseline_scanner.scan_baseline", return_value=fake2):
                scanner._capture_daily_baseline(conn)
            # Count rows directly
            total = conn.execute(
                "SELECT COUNT(*) FROM baseline_readings"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(total, 1, "scanner wrote a second baseline on same UTC day")

    def test_baseline_total_matches_sources(self):
        """Round-trip: inserted total_tokens equals sum of sources."""
        from db import insert_baseline_reading, get_latest_baseline
        sources = [
            {"type": "agent", "name": "a1", "tokens": 500, "path": "/tmp/a1.md"},
            {"type": "skill", "name": "s1", "tokens": 300, "path": "/tmp/s1.md"},
        ]
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        insert_baseline_reading(ts, 800, sources)
        latest = get_latest_baseline()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["total_tokens"], 800)
        self.assertEqual(len(latest["sources"]), 2)

    def test_baseline_failure_is_swallowed(self):
        """If scan_baseline() raises, _capture_daily_baseline must not propagate."""
        from db import get_conn
        import scanner

        conn = get_conn()
        try:
            with mock.patch("baseline_scanner.scan_baseline",
                             side_effect=RuntimeError("boom")):
                # Must NOT raise — the hook is guarded so scanner can continue
                try:
                    scanner._capture_daily_baseline(conn)
                except RuntimeError:
                    self.fail("_capture_daily_baseline propagated a scan failure")
        finally:
            conn.close()


class TestPopulateDailySnapshots(_IsolatedDbCase):

    def test_populate_creates_row_for_today(self):
        """Inserted session row should appear as a daily_snapshots aggregate."""
        import scanner
        from db import get_conn
        import time as _time

        conn = get_conn()
        try:
            # Insert a session at "now" (UTC) so date(timestamp,'unixepoch')
            # matches today.
            now = int(_time.time())
            conn.execute(
                "INSERT INTO sessions (session_id,timestamp,project,account,"
                "model,input_tokens,output_tokens,cache_read_tokens,"
                "cache_creation_tokens,cost_usd) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("sess-test-1", now, "TestProj", "personal_max",
                 "claude-opus-4-7", 100, 50, 20, 10, 0.25),
            )
            conn.commit()
            scanner._populate_daily_snapshots(conn)
            conn.commit()
            today = datetime.date.today().isoformat()
            row = conn.execute(
                "SELECT total_tokens, total_cost_usd, session_count "
                "FROM daily_snapshots WHERE date = ? AND project = ?",
                (today, "TestProj"),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["total_tokens"], 180)  # 100+50+20+10
        self.assertAlmostEqual(row["total_cost_usd"], 0.25, places=4)
        self.assertEqual(row["session_count"], 1)

    def test_populate_is_idempotent(self):
        """Running twice must not duplicate rows (UNIQUE constraint + upsert)."""
        import scanner
        from db import get_conn
        import time as _time

        conn = get_conn()
        try:
            now = int(_time.time())
            conn.execute(
                "INSERT INTO sessions (session_id,timestamp,project,account,"
                "model,input_tokens,output_tokens,cache_read_tokens,"
                "cache_creation_tokens,cost_usd) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("sess-test-2", now, "TestProj", "personal_max",
                 "claude-opus-4-7", 100, 50, 20, 10, 0.25),
            )
            conn.commit()
            scanner._populate_daily_snapshots(conn)
            scanner._populate_daily_snapshots(conn)  # second run
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM daily_snapshots"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
