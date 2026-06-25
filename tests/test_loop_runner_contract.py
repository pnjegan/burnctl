"""Contract test for the stateless loop runner — the anti-false-finish guard.

A checker is only worth trusting if it RED-flags a worker run that violates an
axis. This proves the six-axis checker is non-vacuous: a clean synthetic run
grades all 6 green, and each injected defect reds the TARGETED axis (a worker
cannot fake non-vacuity, real-code binding, or scope). The brake halts the
runner's own loop at the ceiling — it never pushes and never touches CC.

Module-path invocation only (never discover). The runner operates entirely in a
TEMP git repo on a SAFE synthetic goal — no prod usage.db, no ~/.claude logs.
"""

import shutil
import unittest

import loop_runner as lr


def _run_with(artifacts_fn):
    wd = lr._new_repo()
    try:
        return lr.run_loop(lr.synthetic_goal(wd), artifacts_fn)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def _axis(ledger, digit):
    return next(a for a in ledger["axes"] if a["axis"].split()[0] == digit)


class TestLoopRunnerNonVacuous(unittest.TestCase):
    def test_clean_run_grades_all_six_green(self):
        led = _run_with(lr.artifacts_clean)
        self.assertTrue(led["overall_green"], led)
        self.assertTrue(all(a["pass"] for a in led["axes"]),
                        [a for a in led["axes"] if not a["pass"]])
        self.assertFalse(led["halted_by_brake"])
        self.assertEqual(led["iterations"], 1)

    def test_reimpl_reds_axis3_real_binding(self):
        led = _run_with(lr.artifacts_defect_reimpl)
        self.assertFalse(led["overall_green"])
        self.assertFalse(_axis(led, "3")["pass"],
                         "a reimplementation must RED axis 3 (real-code binding)")

    def test_vacuous_reds_axis2_but_criteria_still_pass(self):
        led = _run_with(lr.artifacts_defect_vacuous)
        self.assertFalse(_axis(led, "2")["pass"],
                         "a test the fault cannot break must RED axis 2 (non-vacuity)")
        # the criteria themselves pass — proving the checker distinguishes
        # "tests are green" from "tests can actually fail".
        self.assertTrue(_axis(led, "1")["pass"])

    def test_out_of_scope_reds_axis4_scope(self):
        led = _run_with(lr.artifacts_defect_out_of_scope)
        self.assertFalse(_axis(led, "4")["pass"],
                         "an out-of-scope write must RED axis 4 (scope-compliance)")

    def test_brake_halts_runner_loop_without_push(self):
        led = _run_with(lr.artifacts_defect_vacuous)
        self.assertTrue(led["halted_by_brake"], "ceiling must halt the runner loop")
        self.assertEqual(led["iterations"], lr.synthetic_goal(".").abort_ceiling)
        # the human gate, not the runner, ships:
        self.assertIn("HUMAN-GATED", led["accept_out"])


if __name__ == "__main__":
    unittest.main()
