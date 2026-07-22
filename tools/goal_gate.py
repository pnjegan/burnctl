#!/usr/bin/env python3
"""goal_gate.py — the DELIBERATE HUMAN step that mints STATE-approval tokens.

Pairs with tools/hooks/state_gate.py (the PreToolUse Write|Edit gate). A goal-run
is authorized ONLY by a human running `goal_gate.py mint`; the agent inherits a
declaration it did not author. This is never a side effect of a run.

Artifacts:
  * `.goal-runs/active.json`  — IN-REPO but GITIGNORED (runtime session state).
    The declaration + approvals[] ledger the hook reads.
  * `~/.burnctl/goal-audit.log` — OUTSIDE the git working tree, APPEND-ONLY.
    Every mint/close is logged here. It lives outside the tree ON PURPOSE:
    loop_runner's rollback is `git reset --hard HEAD~1`, which would discard
    uncommitted appends and rewind committed ones — an audit trail the loop can
    erase is not an audit trail.

Detectability (self-mint cannot be PREVENTED, only SEEN): each approval carries a
`nonce`; `mint` writes the SAME nonce to the audit log. `verify` flags any
approval in active.json whose (goal_id, state, nonce) has no matching MINT line —
i.e. an approval added by editing active.json directly rather than via this CLI.
(A gitignored active.json has no git history, so there is deliberately NO
git-blame cross-check — the audit-log MINT match is the sole detection mechanism.)

Commands:
  mint --goal <path> --state N --by <name>   append a human approval + audit line
  status                                     print the active marker
  verify                                     flag approvals not backed by the log
  close                                      remove active.json + log the close

Stdlib only.
"""
import argparse
import datetime
import json
import os
import secrets
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__ + "/.."))
GOAL_RUNS_DIR = os.path.join(REPO_ROOT, ".goal-runs")
ACTIVE_PATH = os.path.join(GOAL_RUNS_DIR, "active.json")
AUDIT_PATH = os.path.expanduser("~/.burnctl/goal-audit.log")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_append(line, audit_path=AUDIT_PATH):
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    with open(audit_path, "a") as fh:      # append-only
        fh.write(line + "\n")


def mint(goal, state, by, active_path=ACTIVE_PATH, audit_path=AUDIT_PATH, nonce=None):
    """Append a human STATE approval for `goal`. Starts a fresh marker if none is
    active or the active goal differs. Returns the written marker dict."""
    state = int(state)
    nonce = nonce or secrets.token_hex(4)
    os.makedirs(os.path.dirname(active_path), exist_ok=True)

    active = None
    if os.path.exists(active_path):
        try:
            with open(active_path) as fh:
                active = json.load(fh)
        except Exception:
            active = None
    if not isinstance(active, dict) or active.get("goal_id") != goal:
        active = {"goal_id": goal, "issued_by": by, "issued_at": _now_iso(),
                  "approvals": []}

    at = _now_iso()
    active["approvals"].append({"state": state, "at": at, "by": by,
                                "source": "goal-gate-cli", "nonce": nonce})
    active["authorized_state"] = max(a["state"] for a in active["approvals"])
    with open(active_path, "w") as fh:
        json.dump(active, fh, indent=2, sort_keys=True)

    _audit_append(f"{at}\tMINT\tgoal={goal}\tstate={state}\tby={by}\tnonce={nonce}",
                  audit_path)
    return active


def close(active_path=ACTIVE_PATH, audit_path=AUDIT_PATH):
    """End the active goal-run: remove the marker + log the close."""
    goal = None
    if os.path.exists(active_path):
        try:
            with open(active_path) as fh:
                goal = json.load(fh).get("goal_id")
        except Exception:
            goal = "<unreadable>"
        os.remove(active_path)
    _audit_append(f"{_now_iso()}\tCLOSE\tgoal={goal}", audit_path)
    return goal


def _minted_triples(audit_path):
    """Set of (goal_id, state, nonce) that have a real MINT line in the audit log."""
    triples = set()
    if not os.path.exists(audit_path):
        return triples
    with open(audit_path) as fh:
        for line in fh:
            parts = dict(p.split("=", 1) for p in line.strip().split("\t")
                         if "=" in p)
            if "\tMINT\t" in line and "goal" in parts and "state" in parts and "nonce" in parts:
                triples.add((parts["goal"], int(parts["state"]), parts["nonce"]))
    return triples


def verify(active_path=ACTIVE_PATH, audit_path=AUDIT_PATH):
    """Cross-check: every approval in active.json must be backed by a MINT line.
    Returns (ok, flags). An unbacked approval == a probable self-mint (active.json
    edited directly instead of via this CLI). Detection, not prevention."""
    flags = []
    if not os.path.exists(active_path):
        return True, []                    # nothing active -> nothing to verify
    try:
        with open(active_path) as fh:
            active = json.load(fh)
    except Exception as e:
        return False, [f"active.json unreadable: {e}"]

    minted = _minted_triples(audit_path)
    goal_id = active.get("goal_id")
    for a in active.get("approvals", []):
        triple = (goal_id, a.get("state"), a.get("nonce"))
        if triple not in minted:
            flags.append(f"approval state={a.get('state')} nonce={a.get('nonce')} "
                         f"for '{goal_id}' has NO matching MINT in the audit log "
                         "-> possible self-mint (active.json edited directly).")
    return (len(flags) == 0), flags


def _cmd_status(args):
    if not os.path.exists(ACTIVE_PATH):
        print("no active goal-run (gate is out of scope -> writes NOT gated).")
        return 0
    with open(ACTIVE_PATH) as fh:
        print(fh.read())
    return 0


def _cmd_verify(args):
    ok, flags = verify()
    if ok:
        print("verify OK — every approval is backed by an audit-log MINT.")
        return 0
    print("verify FAILED — possible self-mint(s):")
    for f in flags:
        print(f"  * {f}")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="STATE-approval token minting (human step)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mint", help="append a human STATE approval")
    m.add_argument("--goal", required=True)
    m.add_argument("--state", required=True, type=int)
    m.add_argument("--by", required=True)
    sub.add_parser("status", help="print the active marker")
    sub.add_parser("verify", help="flag approvals not backed by the audit log")
    sub.add_parser("close", help="end the active goal-run")
    args = ap.parse_args(argv)

    if args.cmd == "mint":
        marker = mint(args.goal, args.state, args.by)
        print(f"minted STATE-{args.state} approval for {args.goal} "
              f"(authorized_state={marker['authorized_state']}). "
              f"Audit: {AUDIT_PATH}")
        return 0
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "verify":
        return _cmd_verify(args)
    if args.cmd == "close":
        goal = close()
        print(f"closed goal-run {goal}; gate is now out of scope.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
