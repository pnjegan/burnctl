"""Contract test for the LOOP-DRIVER — the give-up-cleanly guard.

The headline property: given an UNREACHABLE goal, the driver STOPS at the cap and
escalates — never loops forever, never burns past budget, never pushes. These
tests prove that plus the router, the caps, the stall high-water mark, and the
DONE AND-gate — all against MOCK goals / a MOCK rule table / injected probes.
No real remedy runs, no deploy, no network.

Module-path invocation only (never discover). Stdlib only.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import loop_driver as ld
import loop_runner as lr


# ─────────────────────────── mock building blocks ───────────────────────────

# A MOCK rule table mirroring the shape of docs/RULE-CLASSIFICATION.md — one rule
# per routing class the driver must distinguish. Not the real doc; the router is
# what's under test, not the parse.
MOCK_RULES = {
    "A14": ld.Rule("A14", "GATE", resolves_by="loop-iteration"),          # agent-judgement
    "A1":  ld.Rule("A1", "GATE", resolves_by="human"),                    # data-integrity, human
    "A12": ld.Rule("A12", "FRICTION", remedy="replace Claudash->burnctl"),# reversible remedy
    "A3":  ld.Rule("A3", "FRICTION", remedy="bash deploy.sh",
                   escalates_to="A9"),                                     # remedy trips a GATE
    "B7":  ld.Rule("B7", "FIXED POLICY"),                                 # category-error probe
}

ALL_PASS = {
    "auditor": lambda a: True,
    "reviewer": lambda a: True,
    "invariants": lambda a: True,
}


def _driver(rule_table=None, done_checks=None, probe=None,
            max_iterations=3, max_tokens=10_000, max_usd=100.0, stall_patience=5):
    return ld.LoopDriver(
        max_iterations=max_iterations, max_tokens=max_tokens, max_usd=max_usd,
        stall_patience=stall_patience,
        budget_probe=probe or (lambda: (0, 0.0)),
        rule_table=rule_table or MOCK_RULES,
        done_checks=done_checks or ALL_PASS,
        budget_source="mock",
    )


def _attempt(green=3, total=6, overall=False, rule=None, inner=1):
    def fn(_iteration, _feedback):
        return ld.AttemptResult(axes_green=green, axes_total=total,
                                overall_green=overall, failure_rule_id=rule,
                                inner_iterations=inner)
    return fn


class _ScriptedProbe:
    """Returns scripted (tokens, usd) values in order; clamps to the last once
    exhausted. First call is the driver's pre-loop baseline."""
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def __call__(self):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v


# ─────────────────────────── STATE-3 assertions ───────────────────────────

class TestLoopDriver(unittest.TestCase):

    # -- structural money-furnace guard (precondition of assertion 2) --
    def test_caps_are_required_no_default_infinite(self):
        for missing in ("max_iterations", "max_tokens", "max_usd", "stall_patience"):
            kw = dict(max_iterations=3, max_tokens=1, max_usd=1.0, stall_patience=2,
                      budget_probe=lambda: (0, 0.0), rule_table=MOCK_RULES,
                      done_checks=ALL_PASS)
            kw[missing] = None
            with self.assertRaises(ValueError, msg=f"{missing} must be required"):
                ld.LoopDriver(**kw)

    # -- 1. IMPOSSIBLE-GOAL: unreachable -> stop at max_iterations, escalate, no push --
    def test_1_impossible_goal_stops_at_iteration_cap_no_infinite_loop(self):
        # A loop-iteration GATE that never clears + flat partial green. stall_patience
        # high so the ITERATION cap is what binds (isolating assertion 1 from 3).
        drv = _driver(max_iterations=3, stall_patience=99)
        res = drv.run(_attempt(green=3, overall=False, rule="A14"))
        self.assertEqual(res["stopped_by"], "cap-iterations")
        self.assertFalse(res["done"])
        self.assertFalse(res["pushed"])
        self.assertLessEqual(res["outer_iterations_used"], 3)
        self.assertEqual(res["outer_iterations_used"], 3)  # ran right up to the cap

    # -- 2. BUDGET: token cap breach MID-RUN -> stop+escalate, not continue --
    def test_2_budget_token_breach_mid_run_halts(self):
        # baseline (0,0); iter0 top (0,0) ok; iter1 top (5000,0.5) -> >= max_tokens 4000.
        probe = _ScriptedProbe([(0, 0.0), (0, 0.0), (5000, 0.5), (9999, 9.9)])
        drv = _driver(max_iterations=10, max_tokens=4000, stall_patience=99, probe=probe)
        res = drv.run(_attempt(green=3, overall=False, rule="A14"))
        self.assertEqual(res["stopped_by"], "cap-tokens")
        self.assertLess(res["outer_iterations_used"], 10)   # halted mid-run, not at cap
        self.assertGreaterEqual(res["budget"]["tokens_used"], 4000)
        self.assertFalse(res["pushed"])

    def test_2b_budget_usd_breach_mid_run_halts(self):
        probe = _ScriptedProbe([(0, 0.0), (0, 0.0), (10, 50.0)])
        drv = _driver(max_iterations=10, max_usd=25.0, stall_patience=99, probe=probe)
        res = drv.run(_attempt(green=3, overall=False, rule="A14"))
        self.assertEqual(res["stopped_by"], "cap-usd")
        self.assertLess(res["outer_iterations_used"], 10)

    # -- 3. STALL: best-green flat N iters (under iteration cap) -> stop+escalate --
    def test_3_stall_on_flat_high_water_mark(self):
        drv = _driver(max_iterations=99, stall_patience=2)
        res = drv.run(_attempt(green=3, overall=False, rule="A14"))
        self.assertEqual(res["stopped_by"], "stall")
        self.assertLess(res["outer_iterations_used"], 99)
        self.assertEqual(res["best_green"], 3)

    def test_3b_stall_uses_high_water_mark_not_current_flat(self):
        # Oscillating 5->3->5->3: current-count-flat would be fooled by each change;
        # the high-water mark stays 5 and never improves -> MUST still stall.
        seq = [5, 3, 5, 3, 5, 3, 5, 3]
        calls = {"i": 0}

        def fn(_it, _fb):
            g = seq[min(calls["i"], len(seq) - 1)]
            calls["i"] += 1
            return ld.AttemptResult(axes_green=g, axes_total=6, overall_green=False,
                                    failure_rule_id="A14")
        drv = _driver(max_iterations=99, stall_patience=3)
        res = drv.run(fn)
        self.assertEqual(res["stopped_by"], "stall")
        self.assertEqual(res["best_green"], 5)  # never exceeded -> correctly stalled

    # -- 4. ROUTING-friction: FRICTION -> remedy dry-run LOGGED then re-run --
    def test_4_friction_remedy_is_dry_run_logged_then_reruns(self):
        # iter0: friction failure (A12); iter1: green -> DONE. Proves re-run happened
        # and the remedy was logged, never executed.
        calls = {"i": 0}

        def fn(_it, _fb):
            calls["i"] += 1
            if calls["i"] == 1:
                return ld.AttemptResult(3, 6, overall_green=False, failure_rule_id="A12")
            return ld.AttemptResult(6, 6, overall_green=True)
        drv = _driver(max_iterations=5, stall_patience=99)
        res = drv.run(fn)
        self.assertEqual(res["stopped_by"], "done")
        self.assertEqual(res["outer_iterations_used"], 2)          # re-run attempted
        self.assertEqual(len(res["dry_run_remedies"]), 1)
        self.assertTrue(res["dry_run_remedies"][0].startswith("I would run: "))
        self.assertIn("replace Claudash->burnctl", res["dry_run_remedies"][0])

    # -- 5. ROUTING-human: human GATE -> immediate stop, ZERO retries --
    def test_5_human_gate_escalates_immediately_zero_retries(self):
        drv = _driver(max_iterations=9, stall_patience=99)
        res = drv.run(_attempt(green=3, overall=False, rule="A1"))
        self.assertEqual(res["stopped_by"], "gate-human")
        self.assertEqual(res["outer_iterations_used"], 1)   # one attempt, no retry
        self.assertEqual(res["rule_id"], "A1")
        self.assertFalse(res["pushed"])

    # -- 6. ROUTING-judgement: agent-judgement GATE -> feed back + iterate --
    def test_6_loop_iteration_gate_feeds_back_and_iterates(self):
        seen_feedback = []

        def fn(_it, feedback):
            seen_feedback.append(feedback)
            if len(seen_feedback) == 1:
                return ld.AttemptResult(4, 6, overall_green=False, failure_rule_id="A14")
            return ld.AttemptResult(6, 6, overall_green=True)
        drv = _driver(max_iterations=5, stall_patience=99)
        res = drv.run(fn)
        self.assertEqual(res["stopped_by"], "done")
        self.assertEqual(res["outer_iterations_used"], 2)        # iterated
        self.assertIsNone(seen_feedback[0])                      # first pass: no feedback
        self.assertIsNotNone(seen_feedback[1])                   # second: fed back
        self.assertIn("A14", seen_feedback[1])

    # -- 7. ESCALATE-ON-GATE-REMEDY: A3 (deploy.sh) -> A9 -> escalate, NOT retry --
    def test_7_friction_remedy_that_trips_a_gate_escalates_not_retries(self):
        drv = _driver(max_iterations=9, stall_patience=99)
        res = drv.run(_attempt(green=3, overall=False, rule="A3"))
        self.assertEqual(res["stopped_by"], "gate-remedy-escalation")
        self.assertEqual(res["escalate_to"], "A9")
        self.assertEqual(res["outer_iterations_used"], 1)   # escalated, no retry
        self.assertEqual(len(res["dry_run_remedies"]), 0)   # remedy NOT even dry-run logged

    def test_7b_fixed_policy_routed_is_category_error_escalates(self):
        drv = _driver(max_iterations=9, stall_patience=99)
        res = drv.run(_attempt(green=3, overall=False, rule="B7"))
        self.assertEqual(res["stopped_by"], "gate-human")
        self.assertIn("category error", res["decision_reason"])

    # -- 8. NO-PUSH: pushed stays False across every branch --
    def test_8_no_push_on_any_branch(self):
        branches = [
            _driver(max_iterations=3, stall_patience=99).run(_attempt(rule="A14")),          # cap
            _driver(max_iterations=9, stall_patience=99).run(_attempt(rule="A1")),           # human gate
            _driver(max_iterations=9, stall_patience=99).run(_attempt(rule="A3")),           # gate-remedy
            _driver(max_iterations=99, stall_patience=2).run(_attempt(rule="A14")),          # stall
            _driver(max_iterations=5, stall_patience=99).run(_attempt(green=6, overall=True)),  # done
        ]
        for res in branches:
            self.assertFalse(res["pushed"], res["stopped_by"])
        # and there is no push/publish code path in the driver source at all:
        with open(os.path.join(os.path.dirname(lr.__file__), "loop_driver.py")) as fh:
            src = fh.read()
        for banned in ("git push", "git_push", "npm publish", "subprocess", "os.system"):
            self.assertNotIn(banned, src, f"driver must contain no {banned!r}")

    # -- 9. Determinism: same mocked inputs -> same decisions --
    def test_9_determinism_same_inputs_same_record(self):
        def build():
            probe = _ScriptedProbe([(0, 0.0), (0, 0.0), (5000, 0.5), (9999, 9.9)])
            return _driver(max_iterations=10, max_tokens=4000, stall_patience=99, probe=probe)
        r1 = build().run(_attempt(green=3, overall=False, rule="A14"))
        r2 = build().run(_attempt(green=3, overall=False, rule="A14"))
        self.assertEqual(r1, r2)
        # and route() itself is pure:
        self.assertEqual(ld.route("A3", MOCK_RULES), ld.route("A3", MOCK_RULES))

    # -- DONE requires all four (AND-gate closes in the passing direction) --
    def test_done_requires_green_and_all_checks(self):
        drv = _driver(max_iterations=5, stall_patience=99)
        res = drv.run(_attempt(green=6, overall=True))
        self.assertEqual(res["stopped_by"], "done")
        self.assertTrue(res["done"])

    # ── ADDITION 1: exercise the REAL probe SQL against a seeded sessions table ──
    def test_addition1_real_budget_probe_sql_sums_post_run_start_only(self):
        d = tempfile.mkdtemp(prefix="drv-probe-")
        try:
            db_path = os.path.join(d, "usage.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE sessions (timestamp INTEGER, input_tokens INTEGER, "
                "output_tokens INTEGER, cost_usd REAL)")
            run_start = 1_000_000
            # Rows straddling run_start: two BEFORE (excluded), two AT/AFTER (included).
            rows = [
                (run_start - 500, 100, 100, 1.00),   # before  -> excluded
                (run_start - 1,   999, 999, 9.99),   # before  -> excluded
                (run_start,       10,  20,  0.30),   # at      -> included (>=)
                (run_start + 42,  30,  40,  0.70),   # after   -> included
            ]
            conn.executemany("INSERT INTO sessions VALUES (?,?,?,?)", rows)
            conn.commit()
            conn.close()

            factory = lambda: sqlite3.connect(db_path)
            tok, usd = ld.telemetry_budget_probe(run_start, conn_factory=factory)
            # exactly the post-run_start sum: (10+20)+(30+40)=100 tokens, 0.30+0.70=1.00
            self.assertEqual(tok, 100)
            self.assertAlmostEqual(usd, 1.00, places=6)

            # make_telemetry_probe binds the same real SQL into the zero-arg shape:
            probe = ld.make_telemetry_probe(run_start, conn_factory=factory)
            self.assertEqual(probe(), (100, 1.00))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_addition1b_real_probe_returns_zero_when_no_db(self):
        # None conn (no DB yet) must read as nothing-spent, never crash.
        self.assertEqual(ld.telemetry_budget_probe(0, conn_factory=lambda: None), (0, 0.0))

    # ── ADDITION 2: NEGATIVE done — a failing DONE-check blocks DONE ──
    def test_addition2_negative_done_reviewer_block_prevents_done(self):
        # Every attempt is fully green (6/6) AND overall_green, but the reviewer
        # DONE-check returns False (a block). The AND-gate must NOT declare done;
        # it iterates on the reviewer GATE (A15-style) until the iteration cap.
        checks = {"auditor": lambda a: True,
                  "reviewer": lambda a: False,        # BLOCK
                  "invariants": lambda a: True}

        def fn(_it, _fb):
            # green, but carries the loop-iteration reviewer GATE as the blocker
            return ld.AttemptResult(6, 6, overall_green=True, failure_rule_id="A14")
        drv = _driver(rule_table=MOCK_RULES, done_checks=checks,
                      max_iterations=3, stall_patience=99)
        res = drv.run(fn)
        self.assertNotEqual(res["stopped_by"], "done")     # AND-gate blocked it
        self.assertFalse(res["done"])
        self.assertEqual(res["stopped_by"], "cap-iterations")
        self.assertFalse(res["pushed"])


# ── grounding: the driver drives the REAL loop_runner.run_loop to DONE ──
class TestDriverExtendsRunLoop(unittest.TestCase):
    def test_driver_over_real_run_loop_reaches_done(self):
        wd = lr._new_repo()
        try:
            goal = lr.synthetic_goal(wd)
            drv = _driver(max_iterations=3, stall_patience=99)
            res = drv.run(lambda _it, _fb: ld.attempt_from_run_loop(goal, lr.artifacts_clean))
            self.assertEqual(res["stopped_by"], "done")
            self.assertTrue(res["done"])
            self.assertFalse(res["pushed"])
            self.assertEqual(res["last_green"], 6)          # all six real axes green
            self.assertGreaterEqual(res["inner_iterations_total"], 1)
        finally:
            shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
