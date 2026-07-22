"""Contract test for GOAL-FRICTION-REMEDIES — arming ONE wet remedy safely.

Converts loop_driver's DRY_RUN_REMEDY branch from log-only to REAL execution for
exactly the allow-listed FRICTION rules ({A3, A8} = `bash deploy.sh`), behind a
default-deny allow-list, a dirty-tree preflight, and an injected executor. A11's
identical-DB-path proof is built + tested but stays UNARMED; A12 is excluded.

Every wet path here uses a MOCK command_runner — the suite NEVER restarts pm2,
runs deploy.sh, touches the network, or pushes. Module-path invocation only.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import loop_driver as ld


# A MOCK rule table shaped like docs/RULE-CLASSIFICATION.md's FRICTION rows.
WET_RULES = {
    "A3":  ld.Rule("A3", "FRICTION", remedy="bash deploy.sh", escalates_to="A9"),
    "A8":  ld.Rule("A8", "FRICTION", remedy="bash deploy.sh", escalates_to="A9"),
    "A11": ld.Rule("A11", "FRICTION", remedy="replace literal with db.resolved_db_path()"),
    "A12": ld.Rule("A12", "FRICTION", remedy="replace Claudash->burnctl in output"),
}
ALL_PASS = {"auditor": lambda a: True, "reviewer": lambda a: True,
            "invariants": lambda a: True}
ALLOW = frozenset({"A3", "A8"})


class _Runner:
    """Mock command_runner: records every cmd, returns scripted (exit_code, output)."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def _wet_driver(runner, *, allow=ALLOW, tree=lambda: "", done=None,
                max_iterations=5, stall_patience=99, rule_table=None):
    return ld.LoopDriver(
        max_iterations=max_iterations, max_tokens=10_000, max_usd=100.0,
        stall_patience=stall_patience, budget_probe=lambda: (0, 0.0),
        rule_table=rule_table or WET_RULES, done_checks=done or ALL_PASS,
        budget_source="mock", wet=True, wet_allow_list=frozenset(allow),
        command_runner=runner, tree_status=tree)


def _fail(rule):
    return lambda _it, _fb: ld.AttemptResult(3, 6, overall_green=False, failure_rule_id=rule)


def _fail_then_green(rule):
    state = {"i": 0}

    def fn(_it, _fb):
        state["i"] += 1
        if state["i"] == 1:
            return ld.AttemptResult(3, 6, overall_green=False, failure_rule_id=rule)
        return ld.AttemptResult(6, 6, overall_green=True)
    return fn


class TestFrictionRemedies(unittest.TestCase):

    # -- wet REQUIRES an explicit executor + tree probe (default-deny) --
    def test_wet_requires_injected_runner_and_tree(self):
        base = dict(max_iterations=3, max_tokens=1, max_usd=1.0, stall_patience=2,
                    budget_probe=lambda: (0, 0.0), rule_table=WET_RULES,
                    done_checks=ALL_PASS, wet=True, wet_allow_list=ALLOW)
        with self.assertRaises(ValueError):   # no command_runner
            ld.LoopDriver(**base, tree_status=lambda: "")
        with self.assertRaises(ValueError):   # no tree_status
            ld.LoopDriver(**base, command_runner=_Runner([(0, "")]))

    # -- 1. PREFLIGHT: dirty tree + wet -> STOP before anything runs --
    def test_1_dirty_tree_preflight_halts_before_execution(self):
        runner = _Runner([(0, "")])
        drv = _wet_driver(runner, tree=lambda: " M some_file.py\n")
        res = drv.run(_fail("A3"))
        self.assertEqual(res["stopped_by"], "dirty-tree")
        self.assertEqual(runner.calls, [])            # nothing executed
        self.assertEqual(res["outer_iterations_used"], 0)   # no attempt even started
        self.assertFalse(res["pushed"])

    # -- 2. ALLOW-LIST DEFAULT-DENY: a non-listed FRICTION rule never executes --
    def test_2_non_allowlisted_rule_never_executes(self):
        runner = _Runner([(0, "")])
        drv = _wet_driver(runner)                      # allow = {A3, A8}
        res = drv.run(_fail("A11"))                    # A11 NOT on the list
        self.assertEqual(res["stopped_by"], "remedy-not-armed")
        self.assertEqual(runner.calls, [])             # assert NO subprocess ran
        self.assertEqual(len(res["dry_run_remedies"]), 1)   # logged, not run
        self.assertEqual(res["wet_executions"], [])

    # -- 3. A3 WET SUCCESS: allow-listed + exit 0 -> executes, re-runs, done --
    def test_3_a3_wet_success_executes_and_continues(self):
        runner = _Runner([(0, "Deploy OK")])
        drv = _wet_driver(runner)
        res = drv.run(_fail_then_green("A3"))
        self.assertEqual(res["stopped_by"], "done")
        self.assertEqual(runner.calls, ["bash deploy.sh"])   # ran exactly the remedy
        self.assertEqual(res["wet_executions"],
                         [{"rule_id": "A3", "cmd": "bash deploy.sh", "exit_code": 0}])
        self.assertEqual(res["outer_iterations_used"], 2)    # ran, re-ran to green
        self.assertFalse(res["pushed"])

    # -- 4. A3 WET FAILURE -> A9 escalate, ZERO retries --
    def test_4_a3_wet_failure_escalates_to_a9_zero_retries(self):
        runner = _Runner([(1, "Version mismatch")])
        drv = _wet_driver(runner)
        res = drv.run(_fail("A3"))
        self.assertEqual(res["stopped_by"], "gate-remedy-escalation")
        self.assertEqual(res["escalate_to"], "A9")
        self.assertEqual(len(runner.calls), 1)        # executed ONCE, no retry
        self.assertEqual(res["wet_executions"][0]["exit_code"], 1)
        self.assertFalse(res["pushed"])

    # -- 5. A11 identical-path proof: catches a changed path; A11 stays unarmed --
    def test_5_a11_path_proof_catches_change_and_is_unarmed(self):
        same = ld.verify_identical_db_path("/x/data/usage.db",
                                           resolver=lambda: "/x/data/usage.db")
        moved = ld.verify_identical_db_path("/x/data/usage.db",
                                            resolver=lambda: "/DIFFERENT/usage.db")
        self.assertTrue(same)
        self.assertFalse(moved, "a changed resolved path must fail the proof (-> reclassify GATE)")
        self.assertNotIn("A11", ALLOW)                # never armed this goal
        # and it truly binds to the single-source resolver:
        import db
        self.assertTrue(ld.verify_identical_db_path(db.resolved_db_path()))

    # -- 6. A12 EXCLUDED: cannot execute; not on the allow-list --
    def test_6_a12_cannot_execute(self):
        self.assertNotIn("A12", ALLOW)
        runner = _Runner([(0, "")])
        drv = _wet_driver(runner)
        res = drv.run(_fail("A12"))
        self.assertEqual(res["stopped_by"], "remedy-not-armed")
        self.assertEqual(runner.calls, [])            # A12 never runs
        # source guard: loop_driver holds no Claudash/output-rewrite remedy path
        with open(os.path.join(os.path.dirname(ld.__file__), "loop_driver.py")) as fh:
            src = fh.read()
        self.assertNotIn("Claudash", src)

    # -- 7. INVARIANTS survive: dry-run is DEFAULT; caps still bind; no push --
    def test_7a_dry_run_is_the_default_no_executor_needed(self):
        # Build WITHOUT wet -> command_runner not required, nothing can execute.
        drv = ld.LoopDriver(max_iterations=5, max_tokens=10_000, max_usd=100.0,
                            stall_patience=99, budget_probe=lambda: (0, 0.0),
                            rule_table=WET_RULES, done_checks=ALL_PASS)
        self.assertFalse(drv.wet)
        res = drv.run(_fail("A3"))                    # A3 escalates_to A9 in dry-run
        self.assertEqual(res["stopped_by"], "gate-remedy-escalation")
        self.assertEqual(res["wet_executions"], [])
        self.assertFalse(res["pushed"])

    def test_7b_caps_still_bind_in_wet_mode(self):
        # A loop-iteration GATE that never clears, wet mode, tiny iteration cap.
        rt = dict(WET_RULES); rt["A14"] = ld.Rule("A14", "GATE", resolves_by="loop-iteration")
        runner = _Runner([(0, "")])
        drv = _wet_driver(runner, rule_table=rt, max_iterations=3, stall_patience=99)
        res = drv.run(_fail("A14"))
        self.assertEqual(res["stopped_by"], "cap-iterations")
        self.assertEqual(res["outer_iterations_used"], 3)
        self.assertEqual(runner.calls, [])            # A14 is a GATE, not a remedy

    def test_7c_no_push_across_wet_branches(self):
        branches = [
            _wet_driver(_Runner([(0, "")]), tree=lambda: " M x").run(_fail("A3")),   # dirty
            _wet_driver(_Runner([(1, "")])).run(_fail("A3")),                        # fail->A9
            _wet_driver(_Runner([(0, "")])).run(_fail("A11")),                       # not-armed
            _wet_driver(_Runner([(0, "")])).run(_fail_then_green("A3")),             # success->done
        ]
        for res in branches:
            self.assertFalse(res["pushed"], res["stopped_by"])
        # driver source contains no push/publish/subprocess (executor is external):
        with open(os.path.join(os.path.dirname(ld.__file__), "loop_driver.py")) as fh:
            src = fh.read()
        for banned in ("git push", "npm publish", "subprocess", "os.system"):
            self.assertNotIn(banned, src, f"driver must contain no {banned!r}")

    # -- 8. DETERMINISM: route() + a full wet run are reproducible --
    def test_8_determinism(self):
        self.assertEqual(ld.route("A3", WET_RULES, wet=True, allow_list=ALLOW),
                         ld.route("A3", WET_RULES, wet=True, allow_list=ALLOW))
        r1 = _wet_driver(_Runner([(0, "ok")])).run(_fail_then_green("A3"))
        r2 = _wet_driver(_Runner([(0, "ok")])).run(_fail_then_green("A3"))
        self.assertEqual(r1, r2)

    # -- routing reconciliation: default (non-wet) A3 still escalates (LOOP-DRIVER inv) --
    def test_route_default_still_escalates_a3(self):
        d = ld.route("A3", WET_RULES)                 # wet defaults False
        self.assertEqual(d.action, "ESCALATE")
        self.assertEqual(d.escalate_to, "A9")
        # armed only when BOTH wet AND allow-listed:
        self.assertEqual(ld.route("A3", WET_RULES, wet=True, allow_list=ALLOW).action,
                         "WET_EXECUTE")
        self.assertEqual(ld.route("A3", WET_RULES, wet=True, allow_list=frozenset()).action,
                         "ESCALATE")


# ── wet_exec.py real wrappers: exercised with HARMLESS commands (never deploy) ──
class TestWetExecWrappers(unittest.TestCase):
    def test_real_command_runner_captures_exit_codes(self):
        import wet_exec
        self.assertEqual(wet_exec.real_command_runner("true")[0], 0)
        self.assertNotEqual(wet_exec.real_command_runner("false")[0], 0)
        code, out = wet_exec.real_command_runner("echo hello")
        self.assertEqual(code, 0)
        self.assertIn("hello", out)

    def test_real_tree_status_reads_porcelain(self):
        import wet_exec
        d = tempfile.mkdtemp(prefix="wetexec-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=d)
            self.assertEqual(wet_exec.real_tree_status(cwd=d), "")   # clean
            with open(os.path.join(d, "f.txt"), "w") as fh:
                fh.write("x")
            self.assertIn("f.txt", wet_exec.real_tree_status(cwd=d))  # dirty
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
