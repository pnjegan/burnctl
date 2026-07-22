#!/usr/bin/env python3
"""state_gate.py — PreToolUse Write|Edit gate for goal STATE approval.

Makes the STATE-approval gate the same KIND of mechanical thing I3 is: a hook,
not prose. The earlier failure this fixes: a runner reasoned that a STATE-3 write
was "safe by construction" and proceeded past an explicit human STOP. Prose loses
to reasoning; a PreToolUse deny does not (and, unlike a Stop hook, has no
block-cap — it denies EVERY matching call).

── HONEST SCOPE LIMIT (do not oversell) ──────────────────────────────────────
This is NOT a security boundary. An agent with shell access can write
`.goal-runs/active.json` via Bash, or bypass this Write|Edit hook entirely with a
Bash redirect. What it buys: a bypass stops being a judgement call buried in a
reasoning chain and becomes an explicit, auditable, DELIBERATE act — and a
self-minted token is DETECTABLE (see goal_gate.py `verify`). Fail-closed +
auditable, not unbreakable.

── SCOPING (so ordinary work is possible) ────────────────────────────────────
The gate is scoped to DECLARED goal-runs. With no `.goal-runs/active.json`, there
is no goal-run, so the gate FAILS OPEN (allows) — ordinary work is never gated.
RESIDUAL: because out-of-scope fails open, the gate protects only runs that were
declared. Forgetting to `goal_gate.py mint` means no gate. That is the documented
trade-off of not gating every write in the project.

── DECISION ──────────────────────────────────────────────────────────────────
  * write target inside `.goal-runs/**`      -> BLOCK (a run must never write its
                                                 own authorization via Write|Edit;
                                                 mint is a human Bash step)
  * no active.json (out of scope)            -> ALLOW  (fail-OPEN, ordinary work)
  * active.json malformed (in scope)         -> BLOCK  (fail-CLOSED)
  * no STATE-3 human approval (in scope)     -> BLOCK  (fail-CLOSED; the red-team
                                                 case + wrong-state token)
  * valid STATE-3 approval present           -> ALLOW

Communicates via the hook JSON body (PreToolUse permissionDecision), exit 0.
Stdlib only. Mirrors tools/hooks/check_invariants.py idioms.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__ + "/../.."))
GOAL_RUNS_DIR = os.path.join(REPO_ROOT, ".goal-runs")


def _allow():
    return {}


def _block(reason):
    # PreToolUse contract: deny via hookSpecificOutput; keep legacy top-level
    # decision/reason too so older Claude Code builds still honour the block.
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "decision": "block",
        "reason": reason,
    }


def _within(target, directory):
    """True if `target` resolves inside `directory` (self-mint hardening)."""
    if not target:
        return False
    try:
        t = os.path.realpath(os.path.join(REPO_ROOT, target)) if not os.path.isabs(target) \
            else os.path.realpath(target)
        d = os.path.realpath(directory)
        return t == d or t.startswith(d + os.sep)
    except Exception:
        return False


def decide(tool_input, goal_runs_dir=GOAL_RUNS_DIR):
    """PURE over (tool_input, goal_runs_dir contents): identical inputs -> identical
    allow/block decision. Returns {} to allow or a block dict to deny."""
    target = (tool_input or {}).get("file_path", "")

    # (1) Self-mint hardening: the token dir is never writable via Write|Edit,
    #     in or out of scope. The legitimate mint uses goal_gate.py (Bash), which
    #     does not pass through this hook — so this costs nothing legitimate.
    if _within(target, goal_runs_dir):
        return _block(f"'{target}' is inside the STATE-gate token dir (.goal-runs/); "
                      "it is not writable via Write|Edit. Mint approvals with "
                      "goal_gate.py (a deliberate human step).")

    active_path = os.path.join(goal_runs_dir, "active.json")

    # (2) Out of scope: no declared goal-run -> FAIL OPEN. This branch is first
    #     among the non-token-dir cases and exception-free, so an absent marker can
    #     never brick ordinary writes.
    if not os.path.exists(active_path):
        return _allow()

    # (3) In scope -> FAIL CLOSED from here.
    try:
        with open(active_path) as fh:
            active = json.load(fh)
        if not isinstance(active, dict) or not active.get("goal_id"):
            raise ValueError("missing goal_id")
    except Exception as e:
        return _block(f"active goal-run marker is malformed ({e}); STATE gate "
                      "fails CLOSED — no writes until a valid token exists.")

    goal_id = active.get("goal_id")
    approvals = active.get("approvals")
    if not isinstance(approvals, list) or not any(
            isinstance(a, dict) and a.get("state") == 3 for a in approvals):
        return _block(f"goal-run '{goal_id}' has NO STATE-3 human approval token. "
                      "STATE 1/2 are read-only; a STATE-3 write requires an explicit "
                      "`goal_gate.py mint --state 3` by a human. Blocked (fail-closed).")

    return _allow()


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    result = decide(data.get("tool_input", {}))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
