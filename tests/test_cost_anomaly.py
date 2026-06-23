"""Positive-case fixture for the cost_anomaly spend detector.

burnctl's live usage.db contains NO genuine phantom-billing incident, so the
detector's catch-path (gap-doc cluster #1, GH #68285 / #57719) was only ever
proven structurally + on benign large sessions. This fixture manufactures the
runaway signature and asserts the detector flags it — so "done" for the
detector is a committed file, not a prompt-time backtest the next session has
to re-run from memory.

Surface-only contract is unaffected: this exercises detection, not enforcement.
"""

import sqlite3
import unittest

import waste_patterns as wp

DAY = 86400
_FIXED_NOW = 1_700_000_000  # fixed epoch — tests never read the wall clock


def _make_sessions_db(rows):
    """In-memory DB with just the columns _detect_cost_anomalies reads."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE sessions ("
        "session_id TEXT, project TEXT, account TEXT, "
        "cost_usd REAL, output_tokens INTEGER, timestamp INTEGER)"
    )
    conn.executemany(
        "INSERT INTO sessions "
        "(session_id, project, account, cost_usd, output_tokens, timestamp) "
        "VALUES (:sid, :proj, :acct, :cost, :out, :ts)",
        rows,
    )
    conn.commit()
    return conn


class TestCostAnomalyCatchesRunaway(unittest.TestCase):
    def setUp(self):
        rows = []
        # 8 normal, cheap sessions across the 6 days before the runaway —
        # a stable baseline (median ~$5, ~0 MAD) for r1 to measure against.
        for i in range(8):
            rows.append({
                "sid": f"normal-{i}", "proj": "P", "acct": "a",
                "cost": 5.0, "out": 20000,
                "ts": _FIXED_NOW - 6 * DAY + i * (DAY // 2),
            })
        # THE RUNAWAY: $420 (>= $300 r1 floor, ~hundreds-x the median) AND
        # near-zero output — the stuck-loop / spend-without-output signature.
        rows.append({
            "sid": "RUNAWAY", "proj": "P", "acct": "a",
            "cost": 420.0, "out": 500, "ts": _FIXED_NOW,
        })
        self.conn = _make_sessions_db(rows)

    def tearDown(self):
        self.conn.close()

    def test_runaway_flagged_red_by_r1_and_r3(self):
        flags, _ = wp._detect_cost_anomalies(self.conn)
        by_id = {f["session_id"]: f for f in flags}
        self.assertIn("RUNAWAY", by_id, "the runaway session must be flagged")
        f = by_id["RUNAWAY"]
        rules = f["detail"]["rules"]
        # r1: robust median+MAD outlier, above the absolute floor
        self.assertIn("r1_robust_outlier", rules)
        self.assertGreaterEqual(f["cost"], wp.COST_ANOMALY_R1_FLOOR)
        # r3: spend-without-output (high cost, low output) — the #57719 guard
        self.assertIn("r3_spend_without_output", rules)
        # a genuine anomaly is red, and carries its evidence
        self.assertEqual(f["severity"], "red")
        self.assertEqual(f["detail"]["detector"], "cost_anomaly")

    def test_only_the_runaway_flags(self):
        flags, _ = wp._detect_cost_anomalies(self.conn)
        flagged = {f["session_id"] for f in flags}
        self.assertEqual(
            flagged, {"RUNAWAY"},
            "the 8 normal sessions must stay quiet — only the runaway flags",
        )


if __name__ == "__main__":
    unittest.main()
