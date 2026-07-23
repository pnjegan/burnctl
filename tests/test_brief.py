"""Assertion suite for `burnctl brief` (docs/goals/BURNCTL-PROACTIVE-BRIEF.md).

Five assertions, all deterministic and fixture-driven — no ambient DB, no
network, no wall-clock in the pass/fail path:

  1. 3x spike on the latest day for project P -> flags exactly P; steady
     projects stay unflagged; baseline (median) + robust_score hand-checked.
  2. <3 prior days of data -> no anomaly flag (insufficient-baseline guard).
  3. brief() output serializes to valid JSON with the promised per-project
     schema (incl. robust_score, and cause when anomalous).
  4. Integration: seed a real sessions table, run compute_daily_snapshots
     ITSELF (with injected `now`), read back through SnapshotUsageSource, and
     brief -> >=1 project. No dependence on ambient data.
  5. Determinism: identical input twice -> byte-identical JSON.
"""

import json
import sqlite3
import unittest
from datetime import datetime, timezone

import brief as B
from brief import brief, SnapshotUsageSource

DAY = 86400


def _rec(date, project, cost, account="acct", tokens=400_000, cache=80.0, sessions=4):
    """One normalized per-project-day record (a daily_snapshots row shape)."""
    return {
        "date": date,
        "account": account,
        "project": project,
        "total_tokens": tokens,
        "total_cost_usd": cost,
        "cache_hit_rate": cache,
        "session_count": sessions,
    }


# Prior-day costs shared by the spike fixtures. Hand math:
#   baseline (output field) = RAW median of [6,8,10,12,14] = 10  (unchanged)
#   robust_score now scores LOG1P cost (FIX-DETECTOR) — see the hand math in
#   test_baseline_and_robust_score_hand_checked below.
_PRIOR_DATES = ["2026-07-15", "2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19"]
_PRIOR_COSTS = [10.0, 8.0, 14.0, 6.0, 12.0]
_TODAY = "2026-07-20"


class TestSpikeFlagsExactlyP(unittest.TestCase):
    """Assertion 1 — spike detection, steady-project immunity, baseline math."""

    def setUp(self):
        records = []
        # Project P: steady prior week, then a 3x-median spike TODAY, plus a
        # cache drop + session/tps spike so attribution has something to surface.
        for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS):
            records.append(_rec(d, "P", c))
        records.append(_rec(_TODAY, "P", 30.0, tokens=3_000_000, cache=55.0, sessions=10))
        # Project Q: same steady prior week, steady today (~median) — must NOT flag.
        for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS):
            records.append(_rec(d, "Q", c))
        records.append(_rec(_TODAY, "Q", 11.0))
        self.result = brief(records, _TODAY)
        self.by_name = {p["project"]: p for p in self.result["projects"]}

    def test_flags_exactly_P(self):
        flagged = [p["project"] for p in self.result["projects"] if p["anomaly"]]
        self.assertEqual(flagged, ["P"])

    def test_steady_project_unflagged(self):
        self.assertFalse(self.by_name["Q"]["anomaly"])

    def test_baseline_and_robust_score_hand_checked(self):
        p = self.by_name["P"]
        # baseline = median(prior costs) = 10.0 (RAW median; baseline is unchanged)
        self.assertEqual(p["baseline"], 10.0)
        # robust = z-score of LOG1P cost (FIX-DETECTOR re-pin; was 10.0 pre-fix):
        #   log1p priors [10,8,14,6,12] = [2.3979,2.1972,2.7081,1.9459,2.5649]
        #   median = 2.3979 ; MAD = median|dev| = 0.2007 ; log1p(30) = 3.4340
        #   (3.4340 - 2.3979) / 0.2007 = 5.163 -> round(1) = 5.2
        self.assertEqual(p["robust_score"], 5.2)

    def test_anomaly_carries_heuristic_cause(self):
        p = self.by_name["P"]
        self.assertIn("cause", p)
        self.assertTrue(p["cause"]["heuristic"])
        self.assertIn(p["cause"]["kind"],
                      {"cache_hit_drop", "session_count_spike", "tokens_per_session_jump"})

    def test_movement_hand_checked(self):
        # BRIEF-REFRAME: movement = today_cost / baseline(prior median), rounded 2.
        #   P: 30.0 / 10.0 = 3.0     Q: 11.0 / 10.0 = 1.1
        self.assertEqual(self.by_name["P"]["movement"], 3.0)
        self.assertEqual(self.by_name["Q"]["movement"], 1.1)

    def test_sorted_by_today_cost_desc(self):
        # BRIEF-REFRAME: biggest burner first (was sorted account,project).
        #   P today $30 sorts before Q today $11.
        order = [p["project"] for p in self.result["projects"]]
        self.assertEqual(order, ["P", "Q"])


class TestInsufficientBaseline(unittest.TestCase):
    """Assertion 2 — fewer than 3 prior days must not raise a flag."""

    def test_two_prior_days_no_flag(self):
        records = [
            _rec("2026-07-18", "P", 10.0),
            _rec("2026-07-19", "P", 10.0),
            _rec(_TODAY, "P", 100.0),  # huge spike, but only 2 prior days
        ]
        result = brief(records, _TODAY)
        p = result["projects"][0]
        self.assertFalse(p["anomaly"])
        self.assertEqual(p["robust_score"], 0.0)  # guard skips the computation


class TestJsonSchema(unittest.TestCase):
    """Assertion 3 — output is valid JSON with the promised per-project schema."""

    def test_json_parses_and_has_schema(self):
        records = [_rec(d, "P", c) for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS)]
        records.append(_rec(_TODAY, "P", 30.0, tokens=3_000_000, cache=55.0, sessions=10))
        result = brief(records, _TODAY)

        text = json.dumps(result, indent=2, sort_keys=True)
        parsed = json.loads(text)  # must round-trip

        self.assertEqual(parsed["generated_for"], _TODAY)
        self.assertGreaterEqual(len(parsed["projects"]), 1)
        p = parsed["projects"][0]
        for key in ("tokens", "cost", "cache_pct", "baseline", "movement",
                    "robust_score", "anomaly"):
            self.assertIn(key, p)
        self.assertIsInstance(p["anomaly"], bool)
        if p["anomaly"]:
            self.assertIn("cause", p)  # cause present only when anomalous


class TestMovementNoBaseline(unittest.TestCase):
    """BRIEF-REFRAME assertion 2 — no baseline -> movement None, no divide error."""

    def test_zero_prior_days_movement_none(self):
        # Only today, zero prior days -> baseline 0 -> movement None (not a ratio).
        result = brief([_rec(_TODAY, "P", 50.0)], _TODAY)
        p = result["projects"][0]
        self.assertIsNone(p["movement"])
        self.assertEqual(p["baseline"], 0.0)

    def test_all_zero_prior_costs_movement_none(self):
        # Prior days exist but all cost $0 -> baseline 0 -> movement None, no
        # ZeroDivisionError even though today has cost.
        recs = [_rec(d, "P", 0.0) for d in _PRIOR_DATES]
        recs.append(_rec(_TODAY, "P", 25.0))
        p = brief(recs, _TODAY)["projects"][0]
        self.assertIsNone(p["movement"])

    def test_subcent_baseline_reads_no_baseline_not_absurd_ratio(self):
        # BRIEF-REFRAME hardening (bug-hunt): a sub-cent typical day rounds to
        # baseline 0.00; movement must then read "no baseline" (None), never an
        # absurd ×50000 ratio next to a displayed baseline of 0.0. The displayed
        # baseline and movement can never contradict.
        recs = [_rec(d, "P", 0.001) for d in _PRIOR_DATES]
        recs.append(_rec(_TODAY, "P", 50.0))
        p = brief(recs, _TODAY)["projects"][0]
        self.assertEqual(p["baseline"], 0.0)
        self.assertIsNone(p["movement"])

    def test_negative_today_cost_does_not_produce_negative_movement(self):
        # BRIEF-REFRAME hardening: a stray negative today cost (a credit/refund or
        # a bad record) is clamped like robust_score's max(0.0,x) — movement 0.0,
        # never "×-0.5".
        recs = [_rec(d, "P", 10.0) for d in _PRIOR_DATES]
        recs.append(_rec(_TODAY, "P", -5.0))
        p = brief(recs, _TODAY)["projects"][0]
        self.assertEqual(p["movement"], 0.0)

    def test_unflagged_project_still_has_full_descriptive_row(self):
        # BRIEF-REFRAME assertion 3 — a steady, UNflagged project still renders a
        # complete descriptive row (tokens, cost, cache, movement) so the brief is
        # useful on a zero-flag day.
        recs = [_rec(d, "P", c) for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS)]
        recs.append(_rec(_TODAY, "P", 11.0))  # steady, ~median -> no flag
        p = brief(recs, _TODAY)["projects"][0]
        self.assertFalse(p["anomaly"])
        self.assertEqual(p["movement"], 1.1)      # 11.0 / 10.0
        self.assertGreater(p["tokens"], 0)
        self.assertEqual(p["cost"], 11.0)


class TestIntegrationRealPipeline(unittest.TestCase):
    """Assertion 4 — sessions -> compute_daily_snapshots -> source -> brief.

    Seeds its own sessions table and drives the REAL snapshot builder with an
    injected `now`, so it is deterministic on clean CI and never touches
    ambient data. `days` is set absurdly high so get_daily_snapshots' own
    real-clock `since` window cannot exclude the fixed-epoch fixture rows.
    """

    FIXED_NOW = 1_700_000_000  # 2023-11-14 UTC — fixed; tests never read the clock

    def _seed_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE sessions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, timestamp INTEGER, "
            "project TEXT, account TEXT, model TEXT, input_tokens INTEGER, "
            "output_tokens INTEGER, cache_read_tokens INTEGER, "
            "cache_creation_tokens INTEGER, cost_usd REAL)"
        )
        conn.execute(
            "CREATE TABLE daily_snapshots ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, account TEXT, project TEXT, "
            "total_tokens INTEGER, total_cost_usd REAL, cache_hit_rate REAL, "
            "session_count INTEGER, UNIQUE(date, account, project))"
        )
        rows = []
        # One session per day for 6 consecutive UTC days ending at FIXED_NOW.
        for k in range(6):
            ts = self.FIXED_NOW - k * DAY
            rows.append((
                f"s{k}", ts, "alpha", "acct", "claude-sonnet",
                1000, 2000, 500, 300, 3.0 + k,
            ))
        conn.executemany(
            "INSERT INTO sessions (session_id, timestamp, project, account, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, "
            "cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        return conn

    def test_pipeline_produces_projects(self):
        from analyzer import compute_daily_snapshots

        conn = self._seed_conn()
        # Run the real snapshot builder with the injected clock — its ONLY clock.
        compute_daily_snapshots(conn, "all", now=self.FIXED_NOW)

        records = SnapshotUsageSource(conn).daily_records(days=100_000, account="all")
        self.assertGreaterEqual(len(records), 1)

        today = datetime.fromtimestamp(self.FIXED_NOW, tz=timezone.utc).strftime("%Y-%m-%d")
        result = brief(records, today)
        names = [p["project"] for p in result["projects"]]
        self.assertGreaterEqual(len(result["projects"]), 1)
        self.assertIn("alpha", names)


class TestDeterminism(unittest.TestCase):
    """Assertion 5 — identical input twice yields byte-identical output."""

    def test_byte_identical(self):
        records = [_rec(d, "P", c) for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS)]
        records.append(_rec(_TODAY, "P", 30.0, tokens=3_000_000, cache=55.0, sessions=10))
        records += [_rec(d, "Q", c) for d, c in zip(_PRIOR_DATES, _PRIOR_COSTS)]
        records.append(_rec(_TODAY, "Q", 11.0))

        a = json.dumps(brief(records, _TODAY), indent=2, sort_keys=True)
        b = json.dumps(brief(records, _TODAY), indent=2, sort_keys=True)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
