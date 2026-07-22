# STATE gate — mechanical STATE-3 write approval

Makes the `/goal` STATE-approval gate a **mechanical hook** (like the I3 invariant),
not prose. Prose loses to reasoning: a runner once concluded a STATE-3 write was
"safe by construction" and proceeded past an explicit human STOP. A PreToolUse
`Write|Edit` deny does not lose that argument — and, unlike a Stop hook, it has
**no block-cap** (a Stop hook only blocks `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` times,
which is what let the earlier bypass through).

## Parts
- `tools/hooks/state_gate.py` — PreToolUse `Write|Edit` hook (wired in
  `.claude/settings.json`). Decides allow/block.
- `tools/goal_gate.py` — the **deliberate human step** that mints approval tokens.
- `.goal-runs/active.json` — the declaration + `approvals[]` ledger. **Gitignored**
  (runtime session state).
- `~/.burnctl/goal-audit.log` — append-only audit trail, **outside the git tree**
  on purpose: `loop_runner`'s `git reset --hard HEAD~1` rollback would otherwise
  erase or rewind MINT records — an audit trail the loop can erase is not one.

## Decision logic
| condition | result |
|---|---|
| write target inside `.goal-runs/**` | **BLOCK** (a run may never write its own authorization via Write/Edit) |
| no `active.json` (no declared goal-run) | **ALLOW** — fail-OPEN, ordinary work is never gated |
| `active.json` malformed (in scope) | **BLOCK** — fail-CLOSED |
| no STATE-3 approval for the active goal | **BLOCK** — fail-CLOSED (the red-team case + wrong-state token) |
| valid STATE-3 approval present | **ALLOW** |

## Honest scope limit — read this
This is **NOT a security boundary.** An agent with shell access can write
`active.json` via Bash, or bypass a `Write|Edit` hook entirely with a Bash
redirect (the gate deliberately does **not** match `Bash` — that would collide
with the user-level Bash PreToolUse hooks, over-block legitimate shell, and tempt
false trust). What the gate buys: a bypass stops being a judgement call buried in
a reasoning chain and becomes an explicit, auditable, **deliberate** act.

**Detectability (not prevention):** each approval carries a `nonce`; `mint` writes
the same nonce to the audit log. `goal_gate.py verify` flags any approval in
`active.json` whose `(goal_id, state, nonce)` has no matching MINT line — i.e. an
approval added by editing `active.json` directly. Because `active.json` is
gitignored (no git history), the audit-log MINT match is the **sole** detection
mechanism; there is no git-blame cross-check.

## Residual you must know
Because out-of-scope **fails OPEN**, the gate protects only runs that were
**declared**. **Forgetting to `mint` means no gate.** That is the deliberate
trade-off of scoping (the alternative — gating every write in the project — makes
ordinary work impossible).

## `## Run` block convention for goal files
A gated goal launch is a human step. Add the mint to the goal file's `## Run`:

```
# 1. Human declares the run + approves STATE 1 (read-only):
python3 tools/goal_gate.py mint --goal docs/goals/<GOAL>.md --state 1 --by <you>
claude "Execute docs/goals/<GOAL>.md. STATE 1 ONLY — read-only. Then STOP."

# 2. Human approves each subsequent STATE only after reviewing the prior one:
python3 tools/goal_gate.py mint --goal docs/goals/<GOAL>.md --state 2 --by <you>   # after STATE 1 report
python3 tools/goal_gate.py mint --goal docs/goals/<GOAL>.md --state 3 --by <you>   # after STATE 2 plan
#   ^ only now can the run's Write|Edit calls proceed.

# 3. On completion:
python3 tools/goal_gate.py verify     # confirm no self-minted approvals
python3 tools/goal_gate.py close      # end the run; gate returns to out-of-scope
```
