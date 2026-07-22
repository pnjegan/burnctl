"""Contract test for MECHANICAL-GATES — the STATE-3 write gate.

Makes the STATE-approval gate a mechanical PreToolUse Write|Edit deny (like I3 is
a hook), not prose. The headline (assertion 1) reproduces the exact failure that
motivated the goal: a STATE-3 write with NO approval token must BLOCK.

Fail-CLOSED within a declared goal-run; fail-OPEN outside one (so ordinary work
is never gated). Detection of a self-minted token is via the audit-log MINT
cross-check (goal_gate.verify) — the sole mechanism, since active.json is
gitignored and has no git history. Module-path invocation only. Stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "hooks"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import state_gate  # noqa: E402
import goal_gate    # noqa: E402

GOAL = "docs/goals/MECHANICAL-GATES.md"


def _is_block(res):
    return (res.get("decision") == "block"
            or res.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")


def _write_active(run_dir, approvals, goal_id=GOAL):
    os.makedirs(run_dir, exist_ok=True)
    marker = {"goal_id": goal_id, "issued_by": "human", "issued_at": "2026-07-22T00:00:00Z",
              "approvals": approvals}
    if approvals:
        marker["authorized_state"] = max(a["state"] for a in approvals)
    with open(os.path.join(run_dir, "active.json"), "w") as fh:
        json.dump(marker, fh)


def _appr(state, nonce="n"):
    return {"state": state, "at": "2026-07-22T00:00:00Z", "by": "human",
            "source": "goal-gate-cli", "nonce": nonce}


class TestStateGate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="stategate-")
        self.run_dir = os.path.join(self.d, ".goal-runs")
        self.target = os.path.join(self.d, "prod_code.py")   # a normal write target

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _decide(self, target=None):
        return state_gate.decide({"file_path": target or self.target}, self.run_dir)

    # -- 1. RED-TEAM (headline): STATE-3 write with NO token -> BLOCK --
    def test_1_redteam_state3_write_without_token_blocks(self):
        # A goal-run is declared but NOT approved to STATE 3 (exactly the earlier case).
        _write_active(self.run_dir, [_appr(1), _appr(2)])
        self.assertTrue(_is_block(self._decide()),
                        "a STATE-3 write with no STATE-3 approval MUST block")

    # -- 2. APPROVED PATH: valid STATE-3 token -> ALLOW --
    def test_2_approved_state3_allows(self):
        _write_active(self.run_dir, [_appr(1), _appr(2), _appr(3)])
        self.assertEqual(self._decide(), {})

    # -- 3. FAIL-CLOSED: malformed / empty / corrupt marker -> BLOCK --
    def test_3_malformed_marker_blocks(self):
        os.makedirs(self.run_dir, exist_ok=True)
        for bad in ("", "{not json", "[]", '{"no":"goal_id"}'):
            with open(os.path.join(self.run_dir, "active.json"), "w") as fh:
                fh.write(bad)
            self.assertTrue(_is_block(self._decide()), f"malformed {bad!r} must block")

    # -- 4. WRONG-STATE TOKEN: a STATE-2 token does NOT authorize a STATE-3 write --
    def test_4_state2_token_does_not_authorize_state3(self):
        _write_active(self.run_dir, [_appr(1), _appr(2)])
        self.assertTrue(_is_block(self._decide()))
        # add the real STATE-3 approval -> now allowed
        _write_active(self.run_dir, [_appr(1), _appr(2), _appr(3)])
        self.assertEqual(self._decide(), {})

    # -- 5. DETECTABILITY: an approval not backed by an audit MINT is flagged --
    def test_5_selfmint_detected_by_verify(self):
        active_path = os.path.join(self.run_dir, "active.json")
        audit_path = os.path.join(self.d, "goal-audit.log")
        # legitimate mint via the CLI: writes BOTH active.json and the audit line
        goal_gate.mint(GOAL, 3, "human", active_path=active_path, audit_path=audit_path,
                       nonce="legit")
        ok, flags = goal_gate.verify(active_path=active_path, audit_path=audit_path)
        self.assertTrue(ok, flags)
        # self-mint: append a STATE-3 approval to active.json WITHOUT an audit line
        with open(active_path) as fh:
            marker = json.load(fh)
        marker["approvals"].append(_appr(3, nonce="forged"))
        with open(active_path, "w") as fh:
            json.dump(marker, fh)
        ok, flags = goal_gate.verify(active_path=active_path, audit_path=audit_path)
        self.assertFalse(ok, "a forged approval must be flagged")
        self.assertTrue(any("forged" in f for f in flags))

    # -- 6. NO REGRESSION: settings.json valid + prior hooks intact; invariants exit 0 --
    def test_6_no_regression_to_existing_hooks(self):
        # .claude/settings.json is gitignored (local wiring, same as the I3 Stop
        # hook). Assert on it when present; skip on a fresh clone that lacks it.
        settings_path = os.path.join(REPO, ".claude", "settings.json")
        if not os.path.exists(settings_path):
            self.skipTest(".claude/settings.json not present (gitignored local wiring)")
        with open(settings_path) as fh:
            settings = json.load(fh)                              # must stay valid JSON
        # the Stop hook (check_invariants = I1/I2/I3/I5) must still be wired:
        stop_cmds = json.dumps(settings["hooks"]["Stop"])
        self.assertIn("check_invariants.py", stop_cmds)
        # the new gate must be a SEPARATE PreToolUse Write|Edit entry:
        pre = json.dumps(settings["hooks"].get("PreToolUse", []))
        self.assertIn("state_gate.py", pre)
        self.assertIn("Write|Edit", pre)
        # check_invariants --report still exits 0 (report mode never fails the run):
        r = subprocess.run([sys.executable, "tools/hooks/check_invariants.py", "--report"],
                           cwd=REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    # -- 7. DETERMINISM: same inputs -> same decision --
    def test_7_determinism(self):
        _write_active(self.run_dir, [_appr(1), _appr(2)])
        self.assertEqual(self._decide(), self._decide())
        _write_active(self.run_dir, [_appr(1), _appr(2), _appr(3)])
        self.assertEqual(self._decide(), self._decide())

    # -- OUT-OF-SCOPE ALLOW: no active.json -> ALLOW (ordinary work not bricked) --
    def test_out_of_scope_allows_ordinary_writes(self):
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "active.json")))
        self.assertEqual(self._decide(), {})           # fail-OPEN when no goal-run

    # -- SELF-MINT PATH BLOCKED: Write|Edit into .goal-runs/** -> BLOCK (in or out of scope) --
    def test_selfmint_write_into_token_dir_blocks(self):
        token_file = os.path.join(self.run_dir, "active.json")
        # out of scope (no marker yet) — still blocked:
        self.assertTrue(_is_block(self._decide(target=token_file)))
        # in scope, even fully approved — the token dir itself stays unwritable:
        _write_active(self.run_dir, [_appr(1), _appr(2), _appr(3)])
        self.assertTrue(_is_block(self._decide(target=token_file)))

    # -- hook stdin smoke: the wired command path emits valid hook JSON --
    def test_hook_stdin_contract(self):
        _write_active(self.run_dir, [_appr(1), _appr(2)])   # not state-3 -> block
        # drive decide() through the same shape main() would, asserting JSON-serialisable:
        res = state_gate.decide({"file_path": self.target}, self.run_dir)
        json.dumps(res)                                     # must serialise
        self.assertTrue(_is_block(res))


class TestGoalGateCli(unittest.TestCase):
    def test_mint_close_roundtrip(self):
        d = tempfile.mkdtemp(prefix="goalgate-")
        try:
            active = os.path.join(d, ".goal-runs", "active.json")
            audit = os.path.join(d, "audit.log")
            m = goal_gate.mint(GOAL, 1, "human", active_path=active, audit_path=audit)
            self.assertEqual(m["authorized_state"], 1)
            m = goal_gate.mint(GOAL, 2, "human", active_path=active, audit_path=audit)
            m = goal_gate.mint(GOAL, 3, "human", active_path=active, audit_path=audit)
            self.assertEqual(m["authorized_state"], 3)
            self.assertEqual(len(m["approvals"]), 3)
            ok, flags = goal_gate.verify(active_path=active, audit_path=audit)
            self.assertTrue(ok, flags)
            goal_gate.close(active_path=active, audit_path=audit)
            self.assertFalse(os.path.exists(active))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
