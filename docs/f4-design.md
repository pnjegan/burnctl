# F4 — Saving-Attribution Design Decision

**Status:** decided (v4.5.3) — retain current model, add two bounded
improvements for v4.7. Full rewrite deferred.
**Owner:** Jegan
**Last updated:** 2026-04-24
**Context:** deferred across v4.3–v4.5 as "F4 design doc"; see TECH_DEBT.md
entry TD-A-04.

---

## 1. Problem statement

When burnctl shows "You saved X tokens/session" or "Fix saved $Y/month",
what does "saved" actually mean, and how do we avoid the two failure
modes that keep appearing in user-facing numbers?

### Failure mode A — **zero-floor on empty after-sample**

`fix_tracker.compute_delta()` captures a one-shot baseline at
`fix.created_at`. When re-measured, it diffs against sessions *after* the
fix. If the user records a fix but does no work on the affected project
for days, the after-sample is empty or near-empty, and:

- `total_after` → 0 (no sessions)
- `waste_events.pct_change` → −100 % (zero after a positive before)
- Verdict → **"improving"** (passes `WASTE_IMPROVING_PCT = 20`)
- Token savings → **inflated** (baseline waste tokens − 0)

This is not wrong in a literal mathematical sense, but reads as "the fix
worked" when the truthful answer is "we have no signal yet".

### Failure mode B — **spike-baselined fix**

The inverse. If the baseline window happened to contain one expensive
cost-outlier session, `avg_cost_per_session` baseline is artificially
high. Any subsequent normal activity shows a huge apparent "saving" —
but the real-world steady state never had the inflated cost to save.

### What today's code actually does

Current guards already in place (`fix_tracker.py:82-89, 469-515`):

| Guard | Constant | Behaviour |
|---|---|---|
| Minimum sessions | `MIN_SESSIONS_FOR_VERDICT = 3` | Fallthrough path returns `insufficient_data` when sessions are low AND no threshold was crossed |
| Waste-events directional | `WASTE_IMPROVING_PCT = 20`, `WASTE_WORSENED_PCT = 10` | Threshold must be crossed before verdict flips |
| Window-efficiency directional | `WINDOW_IMPROVING_PCT = 15` | Plan users only |
| Cost directional | `COST_IMPROVING_PCT = 10` | API users only |
| Confirm promotion | `CONFIRM_MIN_DAYS = 7` | "Confirmed" status needs ≥7 days of data |

These partially address failure mode A (via the minimum-sessions fallthrough)
but **do not catch it when the waste_pct threshold actually crosses** —
exactly the scenario above, where `−100 %` trivially beats `−20 %`.

---

## 2. Options considered

### Option A — Rolling-median baseline

Replace the one-shot baseline at `fix.created_at` with a rolling median
of the last 7 days *before* the fix. Spike-resistant; matches
expected-steady-state better.

- **Pros:** naturally handles failure mode B. No verdict-logic change.
- **Cons:** needs 7 days of pre-fix data. Breaks on fresh installs. The
  cached `fix.baseline_json` schema must grow (rolling window snapshots
  instead of single). Migration cost for existing fix rows.

### Option B — Minimum after-sample gate

Refuse to render a directional verdict until the after-sample has
≥N sessions *and* ≥M days (both, not either). Today we have N=3
(`MIN_SESSIONS_FOR_VERDICT`) but only in the fallthrough branch, and no M.

- **Pros:** surgical, cheap, fixes failure mode A directly.
- **Cons:** none material. The number shown on the scoreboard card gets
  a clearer "still measuring" state for low-data fixes.

### Option C — Confidence interval rendering

Show savings as a range (`$15–$42/mo`) rather than a point estimate.
The interval shrinks as after-sample grows.

- **Pros:** most honest representation.
- **Cons:** UI surface change across CLI + dashboard + share-card.
  Users asking "how much did I save" want one number.

### Option D — Do nothing

Accept the current behaviour. Minimum-sessions fallthrough does catch
the worst cases.

- **Pros:** zero effort.
- **Cons:** Failure mode A remains exploitable; it's the literal source
  of the "Fix 12 rendered as improving despite zero sessions" bug that
  v4.4.0-rc.4 fixed indirectly (by running directional checks before
  the sessions gate — which actually made the problem worse, not better).

---

## 3. Decision

**Option B for v4.7, Option A parked, Option C deferred.**

### v4.7 (ship)

1. Extend `MIN_SESSIONS_FOR_VERDICT` to gate the directional branches,
   not just the fallthrough. If after-sample has <3 sessions, render
   `insufficient_data` regardless of threshold crossings.
2. Add `MIN_DAYS_FOR_VERDICT = 2` as a second constant. Both must be
   satisfied. Rationale: a single high-traffic afternoon with 3 sessions
   is not the same as "we measured for 2 days".
3. Show the measurement state explicitly on the scoreboard card:
   "Still measuring — N sessions, D days since apply (need 3 / 2)".

### v4.8 or later (parked, only if data warrants it)

4. Option A rolling-median baseline. Condition for revisit: 30 days of
   baseline_readings data AND evidence of at least 2 spike-baselined
   fix rows in production. If we never see a real-world failure mode B
   case, do not build this.

### Deferred indefinitely

5. Option C confidence interval. Revisit only if multiple users complain
   about range vs point-estimate — today's point estimates are already
   rounded conservatively and we have no report of them being misleading.

---

## 4. Non-goals of this decision

- No migration of historical `fix.baseline_json` rows. Existing records
  stay as-is; the v4.7 gate applies to new `measure_fix` runs only.
- No change to `confirmed` promotion logic (`CONFIRM_MIN_DAYS = 7`).
- No change to the share-card or `fix-scoreboard` CLI output format
  beyond adding the explicit "still measuring" state.

---

## 5. Test plan for v4.7 implementation

When Option B lands:

1. Regression test: replicate the "Fix 12" scenario (waste −100 %,
   sessions=0). Expect `insufficient_data`, not `improving`.
2. Happy path: 3 sessions over 2 days, waste −50 %. Expect `improving`.
3. Boundary: exactly 3 sessions, all within 30 minutes of each other.
   Expect `insufficient_data` (MIN_DAYS_FOR_VERDICT not met).
4. Pre-existing: the current `tests/test_verdict_sessions_gate.py` cases
   must continue to pass.

---

## 6. References

- `fix_tracker.py:323-515` — compute_delta + determine_verdict.
- `fix_measurement.py` — outcome loop (unchanged by this decision).
- `TECH_DEBT.md` entries TD-A-04 and TD-A-07.
- Bug history: Fix 12 (sessions=0 improving), logged in
  `CHANGELOG.md` under v4.4.0-rc.4.
