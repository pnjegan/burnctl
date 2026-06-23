"""Detector-contract criteria for the cost_anomaly spend detector.

`tests/test_cost_anomaly.py` already locks the *headline* catch (the
#68285/#57719 runaway fires r1+r3 red, and only the runaway flags). It does NOT
lock three other properties that SESSION-STATE claims as "done" but that were
only ever proven *by construction* or on the live usage.db at prompt time:

  A. insufficient_baseline is **reported, not flagged**, below MIN_BASELINE.
  B. r3 (spend-without-output) fires **below the r1 floor**, and its floors are
     real boundaries — not "flag everything expensive".
  C. the detector is **surface-only**: read-only against `sessions`, and no flag
     it emits carries an enforcement action (pause/kill/throttle/block).

Each criterion carries a POSITIVE case that proves it catches the failure, not
just that it passes trivially (the runaway-fixture lesson):
  A → the same candidate DOES flag once it has enough baseline.
  B → r3 goes QUIET at the exact output floor and below the cost floor.
  C → an enforcement-shaped flag is REJECTED by the contract validator.

All thresholds are referenced symbolically off `waste_patterns` so the criteria
survive a retune of the constants. Read-only: no product code is imported for
mutation, no DB on disk is touched.
"""

import copy
import sqlite3
import unittest

import waste_patterns as wp

DAY = 86400
HOUR = 3600
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


def _row(sid, cost, out, ts, proj="P", acct="a"):
    return {"sid": sid, "proj": proj, "acct": acct, "cost": cost,
            "out": out, "ts": ts}


def _flagged_ids(flags):
    return {f["session_id"] for f in flags}


# ── Criterion A — insufficient_baseline is reported, not flagged ──────────────
class TestBaselineGuardReportsNotFlags(unittest.TestCase):
    """A session r1 cannot judge (too little trailing history) must be COUNTED
    as insufficient_baseline, never emitted as a flag. The positive case proves
    the guard suppresses rather than flag-never: the identical candidate flags
    once its baseline clears MIN_BASELINE."""

    # candidate: above the r1 floor, but high output so r3 can never fire —
    # isolating r1's baseline guard as the only thing that can flag it.
    CAND_COST = wp.COST_ANOMALY_R1_FLOOR + 200.0
    CAND_OUT = wp.COST_ANOMALY_R3_OUTPUT_FLOOR * 10  # well clear of r3

    def _trailing(self, n):
        # n cheap, stable sessions inside the trailing window before the candidate.
        return [_row(f"base-{i}", 5.0, 20000, _FIXED_NOW - (i + 1) * HOUR)
                for i in range(n)]

    def test_below_min_baseline_is_reported_not_flagged(self):
        n = wp.COST_ANOMALY_MIN_BASELINE - 3  # strictly under the floor
        rows = self._trailing(n) + [
            _row("CAND", self.CAND_COST, self.CAND_OUT, _FIXED_NOW)]
        conn = _make_sessions_db(rows)
        flags, insufficient = wp._detect_cost_anomalies(conn)
        conn.close()
        self.assertNotIn("CAND", _flagged_ids(flags),
                         "candidate has too little baseline — must NOT flag")
        self.assertGreaterEqual(insufficient, 1,
                                "the unjudgeable candidate must be COUNTED")

    def test_positive_enough_baseline_flags(self):
        # POSITIVE: same candidate, now with >= MIN_BASELINE trailing sessions →
        # r1 can judge it and DOES flag. Fails if the baseline/r1 path is broken.
        n = wp.COST_ANOMALY_MIN_BASELINE
        rows = self._trailing(n) + [
            _row("CAND", self.CAND_COST, self.CAND_OUT, _FIXED_NOW)]
        conn = _make_sessions_db(rows)
        flags, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        by_id = {f["session_id"]: f for f in flags}
        self.assertIn("CAND", by_id,
                      "with enough baseline the candidate MUST flag (r1)")
        self.assertIn("r1_robust_outlier", by_id["CAND"]["detail"]["rules"])


# ── Criterion B — r3 fires below the r1 floor; its floors are real boundaries ──
class TestR3SpendWithoutOutput(unittest.TestCase):
    """r3 is the stuck-loop guard (GH #57719): cost >= R3_COST_FLOOR AND output
    strictly < R3_OUTPUT_FLOOR. The existing suite only ever sees r3 bundled
    with r1 on the $420 runaway; here it is isolated BELOW the r1 floor, and the
    QUIET cases prove the floors actually gate."""

    # below the r1 floor so r1 can never fire — r3 is the only governing rule.
    LOW_COST = wp.COST_ANOMALY_R3_COST_FLOOR + 5.0

    def test_r3_fires_below_r1_floor_on_low_output(self):
        rows = [_row("STUCK", self.LOW_COST,
                     wp.COST_ANOMALY_R3_OUTPUT_FLOOR - 1, _FIXED_NOW)]
        conn = _make_sessions_db(rows)
        flags, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        by_id = {f["session_id"]: f for f in flags}
        self.assertIn("STUCK", by_id, "spend-without-output must flag via r3")
        rules = by_id["STUCK"]["detail"]["rules"]
        self.assertIn("r3_spend_without_output", rules)
        self.assertNotIn("r1_robust_outlier", rules,
                         "below the r1 floor, r1 must NOT be credited")
        self.assertEqual(by_id["STUCK"]["severity"], "red")

    def test_r3_quiet_at_output_floor(self):
        # boundary: output == floor is NOT below it (strict <) → no flag.
        rows = [_row("OK", self.LOW_COST,
                     wp.COST_ANOMALY_R3_OUTPUT_FLOOR, _FIXED_NOW)]
        conn = _make_sessions_db(rows)
        flags, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        self.assertNotIn("OK", _flagged_ids(flags),
                         "output exactly at the floor must stay quiet")

    def test_r3_quiet_below_cost_floor(self):
        # boundary: cost under the gate, even at zero output → no flag.
        rows = [_row("CHEAP", wp.COST_ANOMALY_R3_COST_FLOOR - 1.0,
                     0, _FIXED_NOW)]
        conn = _make_sessions_db(rows)
        flags, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        self.assertNotIn("CHEAP", _flagged_ids(flags),
                         "cost below the r3 gate must stay quiet")


# ── Criterion C — surface-only: read-only + no enforcement path ───────────────
# Enforcement verbs that must never appear in a flag (key or value). The detector
# is documented as flag-and-record only; this is the mechanical lock for that.
_ENFORCEMENT_TOKENS = {
    "action", "enforced", "enforce", "kill", "killed", "pause", "paused",
    "throttle", "throttled", "block", "blocked", "stop", "stopped",
    "suspend", "suspended", "terminate", "terminated",
}
_REPORT_SEVERITIES = {"red", "amber", "green"}


def _is_surface_only(flag):
    """True iff `flag` is a pure report — no enforcement action anywhere.

    A flag is surface-only when its severity is a report level and no key or
    string value (recursively) is an enforcement verb. Used both to assert real
    flags pass AND, in the positive case, to prove an enforcement-shaped flag is
    rejected."""
    if flag.get("severity") not in _REPORT_SEVERITIES:
        return False

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and k.lower() in _ENFORCEMENT_TOKENS:
                    return False
                if not _walk(v):
                    return False
        elif isinstance(node, list):
            return all(_walk(x) for x in node)
        elif isinstance(node, str):
            if node.lower() in _ENFORCEMENT_TOKENS:
                return False
        return True

    return _walk(flag)


class TestDetectorIsSurfaceOnly(unittest.TestCase):
    """Locks the 'surface-only, verified by construction' claim mechanically:
    detection does not mutate the sessions table, and no emitted flag carries an
    enforcement action."""

    def _runaway_db(self):
        rows = [_row(f"normal-{i}", 5.0, 20000,
                     _FIXED_NOW - 6 * DAY + i * (DAY // 2)) for i in range(8)]
        rows.append(_row("RUNAWAY", wp.COST_ANOMALY_R1_FLOOR + 120.0,
                         500, _FIXED_NOW))
        return _make_sessions_db(rows)

    def test_detection_does_not_mutate_sessions(self):
        conn = self._runaway_db()
        before = conn.execute(
            "SELECT * FROM sessions ORDER BY session_id").fetchall()
        before = [tuple(r) for r in before]
        flags, _ = wp._detect_cost_anomalies(conn)
        after = [tuple(r) for r in conn.execute(
            "SELECT * FROM sessions ORDER BY session_id").fetchall()]
        conn.close()
        self.assertEqual(before, after,
                         "detector must be read-only against `sessions`")
        # ran on a live detection, not a vacuous pass:
        self.assertGreaterEqual(len(flags), 1)

    def test_no_flag_carries_an_enforcement_action(self):
        conn = self._runaway_db()
        flags, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        self.assertGreaterEqual(len(flags), 1, "need a live flag to test")
        for f in flags:
            self.assertTrue(
                _is_surface_only(f),
                f"flag carries an enforcement action: {f}")

    def test_positive_validator_rejects_an_enforcement_flag(self):
        # POSITIVE: if a future change ever made the detector emit an
        # enforcement action, _is_surface_only must catch it. Prove the
        # validator is not vacuous by feeding it the failure it must reject.
        conn = self._runaway_db()
        real, _ = wp._detect_cost_anomalies(conn)
        conn.close()
        tainted = copy.deepcopy(real[0])
        tainted["detail"]["action"] = "throttle"  # an enforcement path appears
        self.assertFalse(
            _is_surface_only(tainted),
            "validator must REJECT a flag that carries an enforcement action")
        # and a severity that is an enforcement verb, not a report level:
        tainted2 = copy.deepcopy(real[0])
        tainted2["severity"] = "killed"
        self.assertFalse(_is_surface_only(tainted2))


if __name__ == "__main__":
    unittest.main()
