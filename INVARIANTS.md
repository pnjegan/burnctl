# burnctl invariants

Standing rules, checked mechanically on every Stop event. Not documentation —
a checklist a script actually reads and enforces. Add a rule here the moment
a new bug class is found; an invariant that isn't checked automatically will
be forgotten the same way the pm2 daemon was forgotten on 2026-07-17.

Each rule has an id, a mechanical check (what a script can verify without
judgment), and the incident that caused it to be written.

---

## I1 — savings can never exceed spend
**Check:** `fix-rules` total monthly savings estimate must not exceed
`stats` total 30-day spend.
**Query:** compare `generate_claude_md_rules()` total against
`SUM(cost_usd) FROM sessions WHERE timestamp > now-30d`.
**Threshold:** fail if savings > spend (ratio > 1.0). Warn if ratio > 0.6.
**Origin:** 2026-07-17 — fix-rules claimed $XX,XXX/mo against $X,XXX actual
spend. Root cause: unwindowed queries + full-session-cost double-counting.
See BUGFIX-token-cost-inflation.md.

## I2 — no session can waste more than it spent
**Check:** for every `session_id`, `SUM(waste_events.token_cost)` must not
exceed that session's real `SUM(sessions.cost_usd)`.
**Threshold:** fail if any session exceeds 1.01x (small float tolerance).
**Origin:** 2026-07-17 — same incident. `_normalize_session_waste()` is
supposed to enforce this in-process; this invariant re-checks it
independently, from the DB, not trusting the code that's supposed to
maintain it.

## I3 — the running process must be on current code
**Check:** for every pm2-managed process reading from this repo, process
uptime (seconds since start) must be less than time-since-last-edit of any
`.py` file it imports, OR the process must have been restarted after the
last edit to those files.
**Threshold:** fail if `pm2 uptime < time since last .py edit` for any
tracked process.
**Origin:** 2026-07-17 — the burnctl pm2 daemon ran 9 days of stale code
after two rounds of manual fixes, silently re-writing bad data every 5
minutes. Neither round of manual testing caught it until a background
cycle was explicitly waited for.

## I4 — waste-pattern detection must be time-windowed
**Check:** every waste-pattern SQL query in `waste_patterns.py` must
include a `WHERE timestamp >= ?` or `WHERE detected_at >= ?` clause bounded
by `WASTE_WINDOW_DAYS`. No detector may scan unbounded history and re-stamp
`detected_at = now` on old sessions.
**Origin:** 2026-07-17 — `deep_no_compact` and `cost_anomaly` had no time
filter; $XX,XXX of the phantom total was stale sessions re-entering the
"recent" window on every rescan.

## I5 — one billed API request = one stored row
**Check:** no `session_id` may have more `sessions` rows than distinct
`request_id` values (excluding legacy NULL rows). Spot-check: total row
count vs total distinct-request count should not diverge by more than a
small legacy-data margin.
**Origin:** 2026-07-17 — 36% of all session rows were duplicates from
Claude Code writing one JSONL line per content block; this also inflated
`burnctl stats`' own "ground truth" number by 2.2x.

---

## How this file is used

- `tools/hooks/check_invariants.py` runs I1, I2, I3, I5 mechanically
  (things a script can verify with a query or a file-mtime comparison) on
  every Stop event, and blocks completion if any fail.
- I4 is structural (a code-review question, not a runtime number) — it's
  the verifier subagent's job to check new/changed detector queries against
  this rule, not the mechanical script's.
- When a new bug class is found, add a rule here BEFORE considering the fix
  complete. A fix without a corresponding invariant is not done — it's a
  patch that will regress silently, the same way this whole incident did.
