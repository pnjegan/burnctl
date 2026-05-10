"""Tests for the savings-gate in fix_tracker.compute_delta.

When the post-fix window has no sessions (current.sessions_count == 0),
per-turn token attribution collapses to 0, making baseline-minus-current
"savings" an attribution artifact. The gate zeroes only the savings
fields (tokens_saved, api_equivalent_savings_monthly) and tags the
delta with savings_unreliable_reason="no_current_sessions". Verdict
logic (determine_verdict) is untouched.

Live repro: fix #12 (WikiLoop) showed verdict=worsened (correct) AND
$316.79/mo phantom savings (wrong) before this gate.

See BURNCTL-DATA-1 for the orphan-waste-events root cause that lets
waste counts persist while session rows do not.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import db  # noqa: E402
from fix_tracker import compute_delta, determine_verdict  # noqa: E402


# Fix #12's real baseline_json, captured 2026-04-15.
BASELINE = {
    "project": "WikiLoop",
    "captured_at": 1776350376,
    "days_window": 7,
    "plan_type": "max",
    "plan_cost_usd": 100.0,
    "sessions_count": 2,
    "cost_usd": 73.9177,
    "avg_cost_per_session": 36.9588,
    "cache_hit_rate": 95.41,
    "avg_turns_per_session": 99.0,
    "compaction_events": 2,
    "compaction_rate": 1.0,
    "waste_events": {"floundering": 0, "repeated_reads": 5,
                     "deep_no_compact": 0, "cost_outliers": 0, "total": 5},
    "subagent_cost_pct": 0.0,
    "window_hit_rate": 0.0,
    "tokens_wasted_on_floundering": 0,
    "tokens_wasted_on_repeated_reads": 1352873,
    "waste_free_ratio": 94.95,
    "files_per_window": 2,
    "_total_tokens": 26792875,
    "_avg_tokens_per_turn": 135317.55,
    "_avg_cache_read_per_turn": 135287.33,
}

# Case (a): mirrors fix #12 live state — sessions_count=0, waste +40%,
# attribution collapsed.
CURRENT_NO_SESSIONS = {
    "project": "WikiLoop",
    "captured_at": 1776956046,
    "days_window": 7,
    "plan_type": "max",
    "plan_cost_usd": 100.0,
    "sessions_count": 0,
    "cost_usd": 0.0,
    "avg_cost_per_session": 0.0,
    "cache_hit_rate": 0.0,
    "avg_turns_per_session": 0.0,
    "compaction_events": 0,
    "compaction_rate": 0.0,
    "waste_events": {"floundering": 2, "repeated_reads": 5,
                     "deep_no_compact": 0, "cost_outliers": 0, "total": 7},
    "subagent_cost_pct": 0.0,
    "window_hit_rate": 0.0,
    "tokens_wasted_on_floundering": 0,
    "tokens_wasted_on_repeated_reads": 0,
    "waste_free_ratio": 0.0,
    "files_per_window": 0,
    "_total_tokens": 0,
    "_avg_tokens_per_turn": 0.0,
    "_avg_cache_read_per_turn": 0.0,
}

# Case (b): healthy post-fix window — sessions present, waste reduced.
CURRENT_WITH_SESSIONS = {
    "project": "WikiLoop",
    "captured_at": 1776956046,
    "days_window": 7,
    "plan_type": "max",
    "plan_cost_usd": 100.0,
    "sessions_count": 3,
    "cost_usd": 30.0,
    "avg_cost_per_session": 10.0,
    "cache_hit_rate": 90.0,
    "avg_turns_per_session": 50.0,
    "compaction_events": 1,
    "compaction_rate": 0.33,
    "waste_events": {"floundering": 0, "repeated_reads": 1,
                     "deep_no_compact": 0, "cost_outliers": 0, "total": 1},
    "subagent_cost_pct": 0.0,
    "window_hit_rate": 0.0,
    "tokens_wasted_on_floundering": 0,
    "tokens_wasted_on_repeated_reads": 200000,
    "waste_free_ratio": 99.0,
    "files_per_window": 1,
    "_total_tokens": 10000000,
    "_avg_tokens_per_turn": 60000.0,
    "_avg_cache_read_per_turn": 60000.0,
}


class SavingsGateTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            prefix="burnctl-savings-gate-", suffix=".db", delete=False
        )
        self.tmp.close()
        self.db_path = self.tmp.name
        os.remove(self.db_path)

        self._orig_db_path = db.DB_PATH
        db.DB_PATH = self.db_path
        db.init_db()

        # Seed one WikiLoop fix with the fix-#12 baseline. compute_delta
        # reads baseline_json from this row; the test passes `current`
        # directly so we don't need sessions/waste_events table rows.
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM fixes")
        conn.execute(
            "INSERT INTO fixes (id, project, waste_pattern, title, "
            "fix_type, fix_detail, baseline_json, status, created_at, "
            "applied_at, baseline_corrupted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "WikiLoop", "repeated_reads", "test fix",
             "claude_md_rule", "rule body", json.dumps(BASELINE),
             "applied", 1776350376, 1776350376, 0),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        db.DB_PATH = self._orig_db_path
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_a_savings_zeroed_when_current_sessions_zero(self):
        """Case (a): sessions_count=0 -> tokens_saved=0, monthly=0,
        savings_unreliable_reason='no_current_sessions'."""
        conn = self._conn()
        delta, _verdict, _ = compute_delta(
            conn, 1, current=CURRENT_NO_SESSIONS
        )
        conn.close()

        self.assertEqual(delta["tokens_saved"], 0)
        self.assertEqual(delta["api_equivalent_savings_monthly"], 0.0)
        self.assertIn("savings_unreliable_reason", delta)
        self.assertEqual(
            delta["savings_unreliable_reason"], "no_current_sessions"
        )

    def test_b_savings_computed_when_sessions_present(self):
        """Case (b): sessions_count>0 -> savings math runs, key absent."""
        conn = self._conn()
        delta, _verdict, _ = compute_delta(
            conn, 1, current=CURRENT_WITH_SESSIONS
        )
        conn.close()

        # tokens_saved = (0+1352873) - (0+200000) = 1152873
        self.assertEqual(delta["tokens_saved"], 1152873)
        # per_session_saving = 36.9588 - 10.0 > 0; sessions_per_month > 0
        self.assertGreater(delta["api_equivalent_savings_monthly"], 0)
        self.assertNotIn("savings_unreliable_reason", delta)

    def test_c_verdict_unaffected_by_gate(self):
        """Case (c): the gate touches savings only. Verdict for case (a)
        matches what determine_verdict produces from the same delta,
        and waste_events +40% still drives 'worsened'."""
        conn = self._conn()
        delta, verdict_via_compute, _ = compute_delta(
            conn, 1, current=CURRENT_NO_SESSIONS
        )
        conn.close()

        # No sessions table rows seeded -> sessions_since == 0.
        verdict_reference = determine_verdict(delta, "max", 0)
        self.assertEqual(verdict_via_compute, verdict_reference)

        # And specifically: the gate must NOT drag verdict to
        # insufficient_data -- waste +40% drives 'worsened'.
        self.assertEqual(verdict_via_compute, "worsened")


if __name__ == "__main__":
    unittest.main()
