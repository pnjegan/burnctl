"""Contract test for FIX-DETECTOR — log-scaled robust_score.

The fix: score LOG1P cost, not raw cost, so a k lands in the 2-5% calibration
band (raw scoring left a fat tail no k could threshold). These tests cover the
STATE-3 assertions that are NOT already pinned in test_brief.py /
test_brief_calibrate.py (the hand-checked re-pins): zero-cost safety, the <3-prior
insufficiency, single-source, tail compression, and determinism.

The headline assertion (re-calibration over REAL history lands a k in band) is an
inherently live check — proven by `burnctl brief --calibrate` and re-run by the
independent verifier, not unit-tested against a fixed DB. Stdlib only.
"""
import math
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import brief as B


def _raw_score(cost, priors):
    """The PRE-FIX raw scoring, kept LOCAL to this test purely to prove the tail
    compresses under log — never imported into production."""
    import statistics
    med = statistics.median(priors)
    mad = statistics.median([abs(x - med) for x in priors]) or 1e-9
    return (cost - med) / mad


class TestFixDetector(unittest.TestCase):

    # -- 3. ZERO-COST SAFE: no NaN/inf/divide on zero/near-zero priors --
    def test_zero_and_nearzero_costs_are_safe(self):
        for cost, priors in [(0.0, [0.0, 0.0, 0.0]),
                             (5.0, [0.0, 0.0, 0.0]),
                             (0.0, [10.0, 12.0, 14.0]),
                             (1000.0, [0.0, 0.0, 0.01])]:
            s = B.robust_score(cost, priors)
            self.assertFalse(math.isnan(s), (cost, priors))
            self.assertFalse(math.isinf(s), (cost, priors))
        # log1p(0)==0 exactly -> a zero today vs zero priors scores 0, not error:
        self.assertEqual(B.robust_score(0.0, [0.0, 0.0, 0.0]), 0.0)

    # -- 4. INSUFFICIENCY: <3 prior days -> no baseline / no score, never bogus --
    def test_insufficient_history_yields_no_flag(self):
        # brief() guards at BRIEF_MIN_PRIOR_DAYS: a huge spike with 2 priors -> 0.0
        recs = [{"account": "a", "project": "P", "date": "2026-07-01",
                 "total_tokens": 1, "total_cost_usd": 10.0, "cache_hit_rate": 0, "session_count": 1},
                {"account": "a", "project": "P", "date": "2026-07-02",
                 "total_tokens": 1, "total_cost_usd": 10.0, "cache_hit_rate": 0, "session_count": 1},
                {"account": "a", "project": "P", "date": "2026-07-03",
                 "total_tokens": 1, "total_cost_usd": 999.0, "cache_hit_rate": 0, "session_count": 1}]
        p = B.brief(recs, "2026-07-03")["projects"][0]
        self.assertFalse(p["anomaly"])
        self.assertEqual(p["robust_score"], 0.0)   # guard skipped -> no baseline

    # -- log compresses the right-skewed tail (the mechanism of the fix) --
    def test_log_scaling_compresses_the_tail(self):
        # a right-skewed prior + a big multiplicative spike:
        priors = [2.0, 3.0, 2.5, 4.0, 3.0]
        spike = 400.0
        raw = _raw_score(spike, priors)
        log = B.robust_score(spike, priors)
        self.assertGreater(raw, 100)          # raw is in the fat-tail regime
        self.assertLess(log, raw / 10)        # log compresses the tail by >10x

    # -- 5. SINGLE-SOURCE: the log/MAD math exists in exactly ONE place --
    def test_single_source_math(self):
        with open(os.path.join(REPO, "brief.py")) as fh:
            src = fh.read()
        self.assertEqual(src.count("median([abs(x - med)"), 1)
        self.assertEqual(src.count("math.log1p(max(0.0, x))"), 1)

    # -- 7. DETERMINISM: same data -> identical score --
    def test_determinism(self):
        self.assertEqual(B.robust_score(30.0, [10.0, 8.0, 14.0, 6.0, 12.0]),
                         B.robust_score(30.0, [10.0, 8.0, 14.0, 6.0, 12.0]))


if __name__ == "__main__":
    unittest.main()
