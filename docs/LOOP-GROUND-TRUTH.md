# Loop ground truth — PRD Phase 0 output

**Status:** Phase 0 complete. Read-only. No code changes, no schema changes, no writes to `usage.db`
(opened `file:data/usage.db?mode=ro`).
**Read:** 2026-11-05, 18:20 IST. **HEAD:** `6a04a9c` on `v5.0-session-1` (47 files dirty, untouched by this pass).
**Gates:** `docs/burnctl-product-loop-closure-PRD.md:35` — "Phase 0 output: a one-page ground-truth map of the
current loop, committed to `docs/`. Everything downstream references it."

Four of the five PRD assumptions are **wrong in a way that changes the design**. The headline: the reward
signal the PRD sets out to build in Phase 1 partly exists already, but it scores the wrong thing — and the
reason only four waste types close the loop is structural, not a backlog.

---

## 1. The loop as it actually runs

| Stage | Code | Trigger | Notes |
|---|---|---|---|
| detect | `waste_patterns.detect_all` | **auto** — `scanner.py:1402`, every 300s (`scanner.py:1390`) | writes `waste_events` |
| draft | `fix_generator.PROMPTS` (6 patterns) | manual | LLM free text, not a template |
| record | `fix_tracker.record_fix` | manual | coerces unknown pattern → `custom` (`fix_tracker.py:538`) |
| apply | `fix_apply.py`, `POST /api/fixes/:id/apply` | **manual only** | no scheduled caller anywhere |
| measure | `scanner._auto_measure_fixes` | **auto** — `scanner.py:1407`, 6h dedupe per fix | writes `fix_measurements` |
| score | `fix_tracker.determine_verdict` | auto, inside measure | **scores project-wide waste, not the fix's pattern** |
| show | `fix_scoreboard.py`, `cli.py:859`, dashboard | read time | nothing persisted as a scoreboard |
| keep or revert | — | human | no mechanism exists |

So **detect, measure and score already run unattended.** Only *apply* and *keep-or-revert* are human. The
autonomy gap the PRD describes is narrower than it assumes.

---

## 2. The five assumptions

### A1 — "a fix scoreboard exists … where is it stored, what does *improving* mean?" → **CORRECTED**

Storage is **two tables, not one scoreboard**: `fixes` (16 cols, incl. `baseline_json`, `waste_event_id`,
`applied_to_path`, `baseline_corrupted`) and `fix_measurements` (`id, fix_id, measured_at, metrics_json,
delta_json, verdict`). `fix_scoreboard.py` computes the display at read time; nothing is stored. A third
table, `burnctl_fix_measurements` (different shape, 7 cols), is vestigial and unused by this path.

The PRD's "8 fixes, 2 improving" is stale. Live: **8 fixes, 127 measurements — 116 `improving`, 8 `worsened`,
3 `insufficient_data`.**

**What `improving` means mechanically** (`fix_tracker.determine_verdict`, `fix_tracker.py:488-534`):

```
waste_pct = delta["waste_events"]["pct_change"]     # PROJECT-WIDE event count
if waste_pct <= -20: return "improving"             # WASTE_IMPROVING_PCT
if waste_pct >= +10: return "worsened"              # WASTE_WORSENED_PCT
# then a plan-aware cost/window check, then: sessions < 3 -> insufficient_data, else neutral
```

The **targeted-pattern** delta *is* computed one function above — `pattern_before`, `pattern_after`,
`pattern_pct_change` at `fix_tracker.py:473-478` — stored in `delta_json`, and rendered in the fixes list
(`fix_tracker.py:715-737`). **`determine_verdict` never reads it.** The verdict is a project-wide proxy.

This is the exact failure PRD §2 forbids: *"measuring total tokens would drown the signal in session-size
noise and let the loop take credit for randomness."* Two corroborating facts: **91%** of all measurements
(116/127) came back `improving`, and **5 of 8** fixes carry `baseline_corrupted = 1`. A baseline captured
during a waste spike regresses to the mean and scores `improving` for free.

Also worth recording: the thresholds are asymmetric (−20 to improve, +10 to worsen),
`MIN_SESSIONS_FOR_VERDICT = 3`, `CONFIRM_MIN_DAYS = 7`.

### A2 — "`analyzer.py` produces per-pattern attribution … stable identifier?" → **CORRECTED**

Attribution carrying a token/$ figure lives in **`waste_events.token_cost`**, written by `waste_patterns.py`.
`analyzer.py` detects a *different* set (`file_reread`, `retry_error`, `compaction_thrash`, `dead_end`,
`browser_wall`, `oververbose_tool`) and **never writes**. The PRD's assumed taxonomy — redundant reads,
tool-output bloat, CLAUDE.md/skill overhead, context-mixing, model misroute — matches **no** vocabulary in
the repo.

A stable identifier exists (`waste_events.id`, and `fixes.waste_event_id` to carry it) but is **used by only
2 of 8 fixes**.

**Three vocabularies that do not reconcile:**

| Vocabulary | Count | Role |
|---|---|---|
| `fix_tracker.WASTE_PATTERNS` | 8 | the gate on *recording* a fix |
| `fix_generator.PROMPTS` | 6 | the only patterns that can be *drafted* |
| `fix_rules.py` templates | 9 | display only (`burnctl fix-rules`) |
| live `waste_events.pattern_type` | **4** | what actually exists as data |

- `cache_spike`, `model_waste`, `compaction_late` are recordable but have **never** appeared in `waste_events`.
- `oververbose_tool`, `four_tier_compaction`, `long_session`, `fragmented_topic`, `consecutive_peak` have a
  concrete template but **cannot be recorded at all**.
- `bad_compact` and `rewind_heavy` can be drafted but not recorded.

**`recordable ∩ draftable` = `{floundering, repeated_reads, deep_no_compact, cost_outlier}` — exactly the four
closed loops.** The number four is a consequence of the vocabulary mismatch, not of unfinished work.

The mechanism that makes it silent: `record_fix` coerces any unrecognised pattern to `"custom"`
(`fix_tracker.py:538-539`). A fix for `oververbose_tool` is filed as `custom`, the pattern lookup against
`waste_events` finds nothing, `pattern_before` is `None`, and the pattern delta stays null forever.

### A3 — "`daily_qa.py` … is the natural place to hang the measurement step" → **CORRECTED (unnecessary)**

Confirmed: it runs on cron, scores WOW/OK/DOD, and exits 2 / 1 / 0 (`daily_qa.py:956-959`). But measurement
**already runs automatically elsewhere** — `scanner.py:1407`. `daily_qa.py` contains no measurement call; it
only *parses* `fix_improving_count` out of command output as a trend metric (`daily_qa.py:635, 784`).

Phase 1 should not hang measurement on `daily_qa`. The hook point exists in the scanner.

One correction to `CLAUDE.md` while here: all four cron lines run on **local IST**, not UTC. Every time in
that file is off by 5½ hours.

### A4 — "today a human writes the CLAUDE.md rule; nothing auto-applies" → **CONFIRMED**

Apply is reachable only from `burnctl fix apply <n>` (`fix_apply.py`) or `POST /api/fixes/:id/apply`. No
scheduled or hook-driven caller. The scanner auto-measures but never auto-applies, and never auto-*generates*
either (no `fix_generator` import in `scanner.py`).

How little has actually been applied: **1 of 8** fixes is `status = applied`; **2 of 8** carry an
`applied_to_path`; **6 of 8** were `generated_by = human`. Both applied paths still exist on disk
(`/root/wikiloop/.claude/CLAUDE.md`, `/root/projects/Tidify15/.claude/CLAUDE.md`).

### A5 — "fix template, or free text?" → **CORRECTED: both, and disconnected**

What gets **recorded** is LLM free text. `fix_generator.PROMPTS` (6 patterns) builds a prompt — *"write a
single targeted CLAUDE.md rule"* (`fix_generator.py:80`) — and the model's reply lands in `fixes.fix_detail`
and `generation_response`. Unstructured.

Concrete, deterministic templates **do exist** — `fix_rules.py`, 9 patterns, each a real rule — but they are a
**display surface only** and never write a `fixes` row.

The only structure on an applied change is `fixes.fix_type`, a 5-value enum: `claude_md`, `settings_json`,
`prompt`, `architecture`, `other`.

So the structured artifact Phase 3 needs for an ADD-only managed block already exists, in the wrong module,
feeding nothing.

---

## 3. What this changes downstream

1. **Phase 1 is a replacement, not a build.** The pattern-scoped inputs are already computed at
   `fix_tracker.py:473-478`. The work is making `determine_verdict` score *them* instead of project-wide
   waste. Smaller than specified — and higher value, because the current verdict is actively misleading.
2. **Vocabulary unification is a prerequisite the PRD does not list.** No reward signal generalises past four
   types until `WASTE_PATTERNS`, `PROMPTS` and `fix_rules.py` share one keyset, and `record_fix` stops
   silently coercing to `custom`.
3. **The 127 existing measurements cannot serve as the Phase 1 backtest corpus.** 5 of 8 baselines are flagged
   corrupted, and every stored verdict was produced by the proxy. The backtest must recompute from raw
   sessions, not replay `fix_measurements`.
4. **Phase 2 is mostly built.** Detect, measure and score already run unattended; staging is the thin part.
5. **Phase 3's managed-block target needs `fix_rules.py` wired into recording** before auto-apply has anything
   structured and revertible to write.

## 4. Relationship to `feat/loop-close`

Branch `feat/loop-close` (`3bcfd34`, committed, unpushed, clean tree) already hardens the verdict for the same
four types: a `_target_signal` helper, zero-baseline handling, and a `(low confidence)` qualifier now carried
on seven surfaces that print a verdict. It is effectively **a partial Phase 1, for four types, written before
Phase 0 ran.** Phase 0 does not supersede it — it explains why four is the ceiling until the vocabularies
merge, and it means that branch's `COST_TOLERANCE_PCT` ruling is a Phase 1 decision, not a loose end.

## 5. Scope limits of this pass

- No code, schema or data changes. `usage.db` opened read-only.
- Did not re-derive the per-waste-type coverage grid; that is session `4c5172fa` and it agrees with this.
- Did not verify that the two applied CLAUDE.md files still *contain* the rules that were written to them —
  only that the files exist.
- Verdict counts are a point-in-time read; `scanner.py:1407` can add measurements at any 300s tick.
