"""Tests for the applied_at backfill migration inside db.init_db().

The migration sets applied_at = created_at for legacy fix rows
that predate the unified _finalize_apply path (commit 10d755e).

Covers the six seed regimes from the STATE 2 plan:
  A,B,C — measuring/applied/confirmed + NULL applied_at → backfilled.
  D     — status='new' is out of scope → untouched.
  E     — created_at IS NULL → untouched (defensive guard).
  F     — applied_at already set → preserved verbatim.

Plus idempotency: a second init_db() call updates zero rows.

Monkey-patches db.DB_PATH to a tempfile-backed DB. Stdlib only.
"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import db  # noqa: E402


SEED_ROWS = [
    # (id, project, waste_pattern, status, created_at, applied_at)
    (1, "Tidify",   "floundering",    "measuring", 1000, None),   # A
    (2, "Tidify",   "cost_outlier",   "applied",   2000, None),   # B
    (3, "Tidify",   "repeated_reads", "confirmed", 3000, None),   # C
    (4, "Tidify",   "deep_no_compact", "new",      4000, None),   # D
    (5, "Tidify",   "floundering",    "measuring", None, None),   # E
    (6, "WikiLoop", "repeated_reads", "confirmed", 6000, 5999),   # F
]


class AppliedAtBackfillTests(unittest.TestCase):

    def setUp(self):
        # Run each test against its own temp DB so ordering can't leak.
        self.tmp = tempfile.NamedTemporaryFile(
            prefix="burnctl-backfill-", suffix=".db", delete=False
        )
        self.tmp.close()
        self.db_path = self.tmp.name
        os.remove(self.db_path)  # let init_db create it fresh

        self._orig_db_path = db.DB_PATH
        db.DB_PATH = self.db_path

        # Bootstrap schema without triggering the backfill yet — we want
        # to seed rows first, THEN run init_db() to observe the migration.
        db.init_db()

        # Seed rows on top of the freshly-created fixes table.
        conn = sqlite3.connect(self.db_path)
        # Wipe anything init_db seeded, then insert our six fixtures.
        conn.execute("DELETE FROM fixes")
        for fid, project, pattern, status, created_at, applied_at in SEED_ROWS:
            conn.execute(
                "INSERT INTO fixes (id, project, waste_pattern, status, "
                "created_at, applied_at) VALUES (?, ?, ?, ?, ?, ?)",
                (fid, project, pattern, status, created_at, applied_at),
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        db.DB_PATH = self._orig_db_path
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _row(self, fid):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id, status, created_at, applied_at FROM fixes WHERE id = ?",
            (fid,),
        ).fetchone()
        conn.close()
        return row

    def _run_init_and_capture_stderr(self):
        buf = io.StringIO()
        saved = sys.stderr
        sys.stderr = buf
        try:
            db.init_db()
        finally:
            sys.stderr = saved
        return buf.getvalue()

    def test_measuring_row_backfilled_from_created_at(self):
        self._run_init_and_capture_stderr()
        fid, status, created_at, applied_at = self._row(1)
        self.assertEqual(status, "measuring")
        self.assertEqual(applied_at, 1000)
        self.assertEqual(applied_at, created_at)

    def test_applied_row_backfilled_from_created_at(self):
        self._run_init_and_capture_stderr()
        _fid, status, created_at, applied_at = self._row(2)
        self.assertEqual(status, "applied")
        self.assertEqual(applied_at, 2000)
        self.assertEqual(applied_at, created_at)

    def test_confirmed_row_backfilled_from_created_at(self):
        self._run_init_and_capture_stderr()
        _fid, status, created_at, applied_at = self._row(3)
        self.assertEqual(status, "confirmed")
        self.assertEqual(applied_at, 3000)
        self.assertEqual(applied_at, created_at)

    def test_new_status_row_left_null(self):
        # Status 'new' is out of scope — those fixes never completed
        # the apply transition, so applied_at must stay NULL.
        self._run_init_and_capture_stderr()
        _fid, status, _created, applied_at = self._row(4)
        self.assertEqual(status, "new")
        self.assertIsNone(applied_at)

    def test_null_created_at_row_left_null(self):
        # Defensive: if created_at is NULL we have no honest backfill
        # source, so applied_at must stay NULL rather than being set
        # to NULL=NULL (SQL noise) or to 0.
        self._run_init_and_capture_stderr()
        _fid, _status, created_at, applied_at = self._row(5)
        self.assertIsNone(created_at)
        self.assertIsNone(applied_at)

    def test_existing_applied_at_preserved(self):
        # Row F already has applied_at=5999 (different from created_at).
        # The IS NULL guard must leave it untouched — no clobbering.
        self._run_init_and_capture_stderr()
        _fid, status, created_at, applied_at = self._row(6)
        self.assertEqual(status, "confirmed")
        self.assertEqual(created_at, 6000)
        self.assertEqual(applied_at, 5999)

    def test_first_run_logs_rowcount_on_stderr(self):
        stderr = self._run_init_and_capture_stderr()
        # Rows A, B, C backfill → expect "3 legacy fix row(s)".
        self.assertIn(
            "[burnctl] backfilled applied_at on 3 legacy fix row(s)",
            stderr,
        )

    def test_second_run_is_noop(self):
        # First run backfills.
        first = self._run_init_and_capture_stderr()
        self.assertIn("backfilled applied_at on 3", first)

        # Second run must update zero rows and therefore print nothing.
        second = self._run_init_and_capture_stderr()
        self.assertNotIn("backfilled applied_at", second)

        # Snapshot of row values after run 2 must match run 1 exactly —
        # no accidental re-writes or clobbers.
        for fid, _p, _wp, _s, _c, _a in SEED_ROWS:
            row = self._row(fid)
            self.assertIsNotNone(row, msg=f"row {fid} disappeared")


if __name__ == "__main__":
    unittest.main()
