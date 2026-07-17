"""Regression: waste_events.token_cost can never claim more waste than spend.

The 2026-07-17 token-cost-inflation bug: every detector stored the FULL
session cost as token_cost, so a session flagged under 4 patterns claimed
4x its own cost as "waste", and fix-rules reported $30,645/mo savings
against $8,913/mo of actual spend. Two invariants now hold:

  1. per-row:     token_cost <= the session's real SUM(cost_usd)
  2. per-session: SUM(token_cost) across ALL its waste_events rows
                  <= the session's real cost (code enforces 1x via
                  _normalize_session_waste; the goal bound is 2x)

Also pins the stale-session gate: a session inactive for longer than
WASTE_WINDOW_DAYS must produce no waste_events rows, no matter how bad it
looks — detected_at is stamped at scan time, so without the gate every
rescan drags months-old sessions back into the "recent" waste window.

Shape mirrors tests/test_core_clean_scan_contract.py (temp DB via real
db.init_db + a temp JSONL fixture; never prod).
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import db  # noqa: E402
import waste_patterns as wp  # noqa: E402

DAY = 86400
NOW = int(time.time())

# The "hot" session is engineered to fire EVERY session-level detector at
# once — floundering, repeated_reads, cost_outlier, deep_no_compact, and
# cost_anomaly (r1 + r3) — the worst case for cross-pattern inflation.
HOT_TURNS = 150
HOT_COST_PER_TURN = 2.0
HOT_COST = HOT_TURNS * HOT_COST_PER_TURN  # $300 — clears the r1 $300 floor

# JSONL: 5 identical Bash calls (floundering: 5 repeats >= threshold 4)
# + 4 reads of one file (repeated_reads: 4 >= threshold 3) + 1 other call.
HOT_JSONL = (
    [{"type": "assistant", "sessionId": "hot",
      "message": {"content": [{"type": "tool_use", "name": "Bash",
                               "input": {"command": "npm test"}}]}}] * 5
    + [{"type": "assistant", "sessionId": "hot",
        "message": {"content": [{"type": "tool_use", "name": "Read",
                                 "input": {"file_path": "/p/app.py"}}]}}] * 4
    + [{"type": "assistant", "sessionId": "hot",
        "message": {"content": [{"type": "tool_use", "name": "Grep",
                                 "input": {"pattern": "x"}}]}}]
)


def _temp_env():
    tmp = tempfile.mkdtemp(prefix="burnctl-integrity-")
    temp_db = os.path.join(tmp, "data", "usage.db")
    orig = db.DB_PATH
    db.DB_PATH = temp_db
    try:
        db.init_db()
    finally:
        db.DB_PATH = orig
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    return conn, tmp


def _insert_turn(conn, sid, ts, cost, out_tok, source_path=""):
    conn.execute(
        "INSERT INTO sessions (session_id, timestamp, project, account, model,"
        " input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,"
        " cost_usd, source_path, compaction_detected, is_subagent)"
        " VALUES (?, ?, 'P', 'a', 'claude-opus', 100, ?, 0, 0, ?, ?, 0, 0)",
        (sid, ts, out_tok, cost, source_path),
    )


class TestWasteEventsCostIntegrity(unittest.TestCase):
    def setUp(self):
        self.conn, self._tmp = _temp_env()
        jsonl = os.path.join(self._tmp, "hot.jsonl")
        with open(jsonl, "w") as f:
            for obj in HOT_JSONL:
                f.write(json.dumps(obj) + "\n")
        self.conn.execute(
            "INSERT INTO scan_state (file_path, last_offset, last_scanned,"
            " lines_processed) VALUES (?, 1, ?, ?)",
            (jsonl, NOW, len(HOT_JSONL)),
        )

        # 10 cheap baseline sessions in the 6 days before "hot" — the
        # cost_outlier project average AND the r1 trailing-window baseline.
        for i in range(10):
            _insert_turn(self.conn, f"base-{i}", NOW - (i % 6 + 1) * DAY - i,
                         cost=1.0, out_tok=20000)

        # THE HOT SESSION: 150 turns, $300, tiny output, zero compaction —
        # fires every detector at once.
        for t in range(HOT_TURNS):
            _insert_turn(self.conn, "hot", NOW - 3600 + t,
                         cost=HOT_COST_PER_TURN, out_tok=5)

        # THE STALE SESSION: even worse numbers, but inactive for 90 days —
        # must produce NO waste rows at all.
        for t in range(HOT_TURNS):
            _insert_turn(self.conn, "old", NOW - 90 * DAY + t,
                         cost=4.0, out_tok=5)
        self.conn.commit()

        wp.detect_all(self.conn)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _session_cost(self, sid):
        return self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM sessions"
            " WHERE session_id = ?", (sid,)).fetchone()[0]

    def test_nonvacuous_hot_session_fires_multiple_patterns(self):
        pats = sorted(r[0] for r in self.conn.execute(
            "SELECT pattern_type FROM waste_events WHERE session_id='hot'"))
        for expected in ("cost_anomaly", "cost_outlier", "deep_no_compact",
                         "floundering", "repeated_reads"):
            self.assertIn(expected, pats,
                          f"fixture must fire {expected}; got {pats}")

    def test_per_session_waste_sum_never_exceeds_2x_real_cost(self):
        rows = self.conn.execute(
            "SELECT session_id, SUM(token_cost) AS waste"
            " FROM waste_events GROUP BY session_id").fetchall()
        self.assertTrue(rows, "vacuous — no waste rows to check")
        for r in rows:
            cost = self._session_cost(r["session_id"])
            self.assertLessEqual(
                r["waste"], 2 * cost,
                f"{r['session_id']}: claimed waste ${r['waste']:.2f} exceeds"
                f" 2x real cost ${cost:.2f} — token-cost inflation regressed")

    def test_per_session_waste_sum_capped_at_real_cost(self):
        # The code invariant is stronger than the 2x bound: a session cannot
        # waste more than it spent (_normalize_session_waste).
        rows = self.conn.execute(
            "SELECT session_id, SUM(token_cost) AS waste"
            " FROM waste_events GROUP BY session_id").fetchall()
        for r in rows:
            cost = self._session_cost(r["session_id"])
            self.assertLessEqual(r["waste"], cost * 1.000001,
                                 f"{r['session_id']}: waste > spend")

    def test_no_single_row_exceeds_session_cost(self):
        rows = self.conn.execute(
            "SELECT session_id, pattern_type, token_cost"
            " FROM waste_events").fetchall()
        for r in rows:
            cost = self._session_cost(r["session_id"])
            self.assertLessEqual(
                r["token_cost"], cost * 1.000001,
                f"{r['session_id']}/{r['pattern_type']}: row token_cost"
                f" ${r['token_cost']:.2f} > session cost ${cost:.2f}")

    def test_stale_session_produces_no_waste_rows(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM waste_events WHERE session_id='old'"
        ).fetchone()[0]
        self.assertEqual(n, 0,
                         "session inactive >WASTE_WINDOW_DAYS must not be"
                         " re-stamped into the recent waste window")


if __name__ == "__main__":
    unittest.main()
