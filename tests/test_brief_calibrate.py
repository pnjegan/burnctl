"""Contract test for `burnctl brief --calibrate` — grounding the anomaly k in
REAL history before launch, without ever mutating the threshold or the DB.

Proves the five STATE-3 assertions:
  1. Reuse   — calibrate scores via the SAME robust_score as the live brief
               (one source; both call it; the MAD math exists in exactly one place).
  2. Distribution correctness — on a hand-checked fixture, percentiles + per-k
               flag counts match arithmetic done by hand.
  3. Read-only — the CLI calibrate path mutates NO config value and writes NO DB
               row (BRIEF_MAD_K and the DB file are byte-identical before/after).
  4. Insufficient-history — below the >=3-prior guard -> "insufficient", no bogus k.
  5. Determinism — same data -> identical suggestion + distribution.

Module-path invocation only. Stdlib only. calibrate() is exercised as a pure
function on constructed fixtures; the read-only assertion drives the real CLI
branch against a seeded temp DB.
"""

import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

import brief as B


# ─────────────────────────── fixtures ───────────────────────────

def _row(account, project, d, cost, tokens=1000, cache=50.0, sessions=3):
    return {"account": account, "project": project, "date": d,
            "total_tokens": tokens, "total_cost_usd": cost,
            "cache_hit_rate": cache, "session_count": sessions}


# Five projects, each: 3 prior days (10, 12, 14 -> median 12, MAD 2) + 1 today.
# Only the today-day (d4) clears the >=3-prior guard, so each contributes exactly
# one qualifying project-day. today costs chosen for clean hand-checked scores:
#   score = (today - 12) / 2
_D1, _D2, _D3, _D4 = "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"
_TODAY_COSTS = {"A": 20, "B": 30, "C": 13, "D": 24, "E": 16}   # log scores: 3.35 6.07 0.52 4.57 1.87


def _hand_fixture():
    recs = []
    for proj, today_cost in _TODAY_COSTS.items():
        recs += [
            _row("acct", proj, _D1, 10),
            _row("acct", proj, _D2, 12),
            _row("acct", proj, _D3, 14),
            _row("acct", proj, _D4, today_cost),
        ]
    return recs


def _dates(n, start=date(2026, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class TestCalibrate(unittest.TestCase):

    # -- 1. REUSE: one scoring source; both brief() and calibrate() call it --
    def test_1_single_source_both_call_robust_score(self):
        calls = {"n": 0}
        orig = B.robust_score

        def spy(cost, prior):
            calls["n"] += 1
            return orig(cost, prior)

        B.robust_score = spy
        try:
            B.calibrate(_hand_fixture())
            after_cal = calls["n"]
            self.assertGreater(after_cal, 0, "calibrate must call robust_score")
            B.brief(_hand_fixture(), _D4)
            self.assertGreater(calls["n"], after_cal,
                               "brief must call the SAME robust_score (shared source)")
        finally:
            B.robust_score = orig
        # the MAD math lives in exactly ONE place (no reimplementation):
        with open(os.path.join(os.path.dirname(B.__file__), "brief.py")) as fh:
            src = fh.read()
        self.assertEqual(src.count("median([abs(x - med)"), 1,
                         "the median/MAD math must exist in exactly one function")

    # -- 2. DISTRIBUTION CORRECTNESS on the hand-checked fixture --
    def test_2_distribution_and_flag_counts_hand_checked(self):
        res = B.calibrate(_hand_fixture())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["qualifying_project_days"], 5)   # one per project

        d = res["distribution"]
        # LOG-SCALED scoring (FIX-DETECTOR re-pin; was [0.5,2,4,6,9] pre-fix).
        # priors [10,12,14] -> log1p [2.3979,2.5649,2.7081]; median=2.5649;
        # MAD=median(|dev|)=0.1431. scores = (log1p(today)-2.5649)/0.1431:
        #   A(20)=3.351  B(30)=6.073  C(13)=0.518  D(24)=4.570  E(16)=1.875
        # sorted: [0.518, 1.875, 3.351, 4.570, 6.073]
        self.assertEqual(d["count"], 5)
        self.assertEqual(d["min"], 0.52)
        self.assertEqual(d["max"], 6.07)
        self.assertEqual(d["p50"], 3.35)   # idx ceil(.5*5)-1 = 2
        self.assertEqual(d["p90"], 6.07)   # idx ceil(.9*5)-1 = 4
        self.assertEqual(d["p95"], 6.07)
        self.assertEqual(d["p99"], 6.07)

        # per-k flag counts (score > k AND cost >= floor; all costs >= $1):
        by_k = {e["k"]: e for e in res["flag_table"]}
        self.assertEqual(by_k[3]["flag_count"], 3)   # >3: 3.35,4.57,6.07
        self.assertEqual(by_k[4]["flag_count"], 2)   # >4: 4.57,6.07
        self.assertEqual(by_k[5]["flag_count"], 1)   # >5: 6.07
        self.assertEqual(by_k[6]["flag_count"], 1)   # >6: 6.07
        self.assertEqual(by_k[8]["flag_count"], 0)   # >8: none
        self.assertAlmostEqual(by_k[3]["flag_rate"], 0.6)
        self.assertAlmostEqual(by_k[6]["flag_rate"], 0.2)

        # suggested k = closest flag_rate to 3%; rates {.6,.4,.2,.2,.0} -> .0 nearest
        # (k=8), below the 2% floor -> "too stable" note.
        self.assertEqual(res["suggested_k"], 8)
        self.assertAlmostEqual(res["suggested_flag_rate"], 0.0)
        self.assertFalse(res["in_band"])
        self.assertIn("stable", res["note"].lower())

    # -- suggestion rule: centered on 3%, lands in band when data supports it --
    def test_2b_suggested_k_centers_in_band(self):
        # 32 steady qualifying days (cost flat -> score 0) + 1 lone spike ->
        # flag-rate = 1/33 = 3.03%, squarely in the 2-5% band, closest to 3%.
        recs = [_row("a", "steady", d, 10) for d in _dates(35)]        # 35 days -> 32 qualifying
        recs += [_row("a", "spike", d, 10) for d in _dates(3, date(2026, 5, 1))]
        recs.append(_row("a", "spike", date(2026, 5, 4).isoformat(), 1000))
        res = B.calibrate(recs)
        self.assertEqual(res["qualifying_project_days"], 33)
        self.assertEqual(res["suggested_k"], 8)          # all k flag only the spike; tie -> highest
        self.assertAlmostEqual(res["suggested_flag_rate"], round(1 / 33, 4))
        self.assertTrue(res["in_band"])
        self.assertIn("band", res["note"].lower())

    def test_2c_below_band_note_when_too_stable(self):
        # Perfectly flat history -> zero flags at every k -> below the 2% floor.
        recs = [_row("a", "flat", d, 10) for d in _dates(6)]   # 3 qualifying, all score 0
        res = B.calibrate(recs)
        self.assertEqual(res["qualifying_project_days"], 3)
        self.assertTrue(all(e["flag_count"] == 0 for e in res["flag_table"]))
        self.assertFalse(res["in_band"])
        self.assertIn("stable", res["note"].lower())

    # -- 3. READ-ONLY: CLI calibrate mutates no config, writes no DB row --
    def test_3_calibrate_is_read_only(self):
        import cli
        d = tempfile.mkdtemp(prefix="cal-ro-")
        try:
            db_path = os.path.join(d, "usage.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE daily_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "date TEXT, account TEXT, project TEXT, total_tokens INTEGER, "
                "total_cost_usd REAL, cache_hit_rate REAL, session_count INTEGER, "
                "UNIQUE(date, account, project))")
            # a sessions table so a stray compute_daily_snapshots WOULD leave a trace:
            conn.execute("CREATE TABLE sessions (timestamp INTEGER, project TEXT, "
                         "account TEXT, cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER)")
            for i, dt in enumerate(_dates(6, date(2026, 7, 5))):
                conn.execute("INSERT INTO daily_snapshots "
                             "(date, account, project, total_tokens, total_cost_usd, cache_hit_rate, session_count) "
                             "VALUES (?,?,?,?,?,?,?)",
                             (dt, "all", "proj", 1000, 10.0 + i, 50.0, 3))
            conn.commit()
            conn.close()

            def _hash():
                with open(db_path, "rb") as fh:
                    return hashlib.sha256(fh.read()).hexdigest()

            def _snap_count():
                c = sqlite3.connect(db_path)
                n = c.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
                c.close()
                return n

            def _factory():
                c = sqlite3.connect(db_path)
                c.row_factory = sqlite3.Row
                return c

            k_before = B.BRIEF_MAD_K
            hash_before = _hash()
            count_before = _snap_count()

            orig_get_conn = cli.get_conn
            orig_argv = sys.argv
            cli.get_conn = _factory
            sys.argv = ["burnctl", "brief", "--calibrate"]
            try:
                with redirect_stdout(io.StringIO()):
                    cli._cmd_brief_calibrate()
            finally:
                cli.get_conn = orig_get_conn
                sys.argv = orig_argv

            self.assertEqual(B.BRIEF_MAD_K, k_before, "calibrate must NOT mutate BRIEF_MAD_K")
            self.assertEqual(_snap_count(), count_before, "calibrate must write NO DB row")
            self.assertEqual(_hash(), hash_before, "DB file must be byte-identical after calibrate")
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    # -- 4. INSUFFICIENT-HISTORY: below the guard -> no bogus k --
    def test_4_insufficient_history_emits_no_k(self):
        # Two projects, two days each -> no project-day has >=3 prior days.
        recs = [_row("a", "p1", _D1, 10), _row("a", "p1", _D2, 99),
                _row("a", "p2", _D1, 5), _row("a", "p2", _D2, 50)]
        res = B.calibrate(recs)
        self.assertEqual(res["status"], "insufficient")
        self.assertIsNone(res["suggested_k"])
        self.assertEqual(res["qualifying_project_days"], 0)

    # -- 5. DETERMINISM: same data -> identical distribution + suggestion --
    def test_5_determinism(self):
        r1 = B.calibrate(_hand_fixture())
        r2 = B.calibrate(_hand_fixture())
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
