# burnctl — Technical Debt Ledger

Single source of truth for deferred / known / partially-resolved work.
Every item has an id, status, priority, file pointer, and a one-line fix.
Edit existing entries in place (status transitions are expected).
New entries append. History prior to 2026-04-24 is preserved verbatim
at the bottom of this file under "Archive".

Status: `open` | `in_progress` | `deferred` | `resolved`
Priority: `P2` (next patch) | `P3` (next minor) | `P4` (nice-to-have)

Last consolidated: 2026-04-24 (v4.5.3 gap-closure session).

---

## Open / Deferred

### TD-01 — load_db() duplication
- **Status:** open
- **Priority:** P3 (ready for v4.6; defer until after pitch)
- **Files:** 10 files each define their own `load_db()`:
  `claudemd_audit.py`, `compact_audit.py`, `fix_rules.py`,
  `subagent_audit.py`, `work_timeline.py`, `fix_apply.py`,
  `fix_scoreboard.py`, `overhead_audit.py`, `variance_profiler.py`,
  `why_limit.py`
- **Fix:** extract to `db.open_local_db()`, replace 10 copies, delete old functions.
- **Added:** auditor 2026-04-24.

### TD-02 — cli.py near size threshold
- **Status:** open
- **Priority:** P3 (v4.6 refactor candidate)
- **Files:** `cli.py` (2,378 LOC)
- **Fix:** split `cmd_*` handlers into a `commands/` package; keep entry
  point thin.
- **Added:** auditor 2026-04-24.

### TD-03 — classify_version extra patch ranges
- **Status:** open
- **Priority:** P3 (fold into v4.6)
- **Files:** `version_check.py:72-88`, `run_version_check:115-141`
- **Fix:** make the description-printer data-driven — one dict keyed
  by version instead of hand-rolled print blocks per entry.
- **Added:** auditor 2026-04-24.

### TD-04 — compact-audit threshold detection
- **Status:** open
- **Priority:** P3 (researcher-recommended)
- **Files:** `compact_audit.py` (152 lines; no threshold logic anywhere)
- **Fix:** detect the Claude Code version / context-size threshold at
  which compact starts firing per project.
- **Added:** researcher 2026-04-23.

### TD-05 — cache-ttl-report not implemented
- **Status:** open
- **Priority:** P3 (researcher-recommended)
- **Files:** none yet — command doesn't exist.
- **Fix:** new CLI command + module to surface cache-write TTL
  utilisation per session.
- **Added:** researcher 2026-04-23.

### TD-06 — reset-window integrity check
- **Status:** open
- **Priority:** P3
- **Files:** none — no integrity-check logic for the 5-hour window.
- **Fix:** `burnctl window --validate` that flags gaps/overlaps in
  `window_burns` rows.
- **Added:** verifier 2026-04-24.

### TD-07 — per-model disaggregation in subagent-audit
- **Status:** open
- **Priority:** P3
- **Files:** `subagent_audit.py` (no `GROUP BY model` anywhere)
- **Fix:** split subagent-audit output per-model so opus-vs-sonnet
  subagent cost is visible.
- **Added:** verifier 2026-04-24.

### TD-08 — ~/.burnctl directory permissions
- **Status:** open (partial)
- **Priority:** P3
- **Files:** `db.py:15-21` hardens `usage.db` + WAL/SHM only.
- **Fix:** extend `_lock_db_file` (or add sibling) to chmod `~/.burnctl/`
  and `~/.burnctl/backups/` to 0700.
- **Added:** verifier 2026-04-24.

### TD-09 — clean-Mac `npx burnctl@latest` audit record
- **Status:** open (pre-pitch prerequisite)
- **Priority:** P2
- **Files:** none (process debt, not code).
- **Fix:** run and record a fresh-install audit (no existing DB, no
  existing `~/.claude/`) before the next public pitch. Capture in
  `audit-reports/` scoped to the first-run onboarding path.
- **Added:** verifier 2026-04-24.

### TD-10 — research-reports/latest.md symlink convention
- **Status:** open
- **Priority:** P4 (cosmetic — M-3 staleness check now handles absence)
- **Files:** `research-reports/` (no `latest.md` present today).
- **Fix:** have `burnctl-researcher` agent write or symlink `latest.md`
  to the newest dated file after each run.
- **Added:** v4.5.3 session 2026-04-24.

### TD-A-04 — F4 saving-attribution model
- **Status:** deferred
- **Priority:** P2 (implementation target v4.7)
- **Files:** `fix_tracker.py:323-515`, `docs/f4-design.md`
- **Fix:** Option B (extend `MIN_SESSIONS_FOR_VERDICT` to gate
  directional branches + add `MIN_DAYS_FOR_VERDICT=2`). Option A
  rolling-median baseline parked — revisit only after 30 days of
  `baseline_readings` data AND a real-world spike-baselined fix.
- **Added:** deferred across v4.3–v4.5; decision recorded
  2026-04-24.

### TD-A-07 — `_MONTHLY_SESSIONS = 30` is a conservative floor
- **Status:** deferred
- **Priority:** P4
- **Files:** `insights.py:683`
- **Fix:** upgrade to per-user session rate once we have enough
  history. Current value documented inline.
- **Added:** v4.5.0.

### TD-H-04 — Stored verdict vs read-time recompute
- **Status:** deferred (existing `auto_measure_pending()` self-corrects
  within 5 minutes of next scan).
- **Priority:** P3 (revisit before next verdict-logic change)
- **Files:** `server.py:515-522` reads stored `verdict`; CLI
  `fix_scoreboard.py:122` recomputes.
- **Fix:** move verdict derivation to read-time, or add
  `verdict_computed_at_version` column and recompute on mismatch.
- **Added:** 2026-04-23.

### TD-H-05 — Zero-session waste_events verdict
- **Status:** deferred (rare — 1 of 8 live fix rows)
- **Priority:** P4
- **Files:** `fix_tracker.py`.
- **Fix:** tag delta with `measurement_confidence`, render faded card;
  or require `sessions_since >= N` before trusting waste_events deltas.
- **Added:** 2026-04-23.

### TD-oauth-01 — oauth_sync.py subprocess hang risk
- **Status:** deferred
- **Priority:** P3
- **Files:** `tools/oauth_sync.py:89-93`
- **Fix:** add `timeout=2.0` to `subprocess.check_output`, catch
  `TimeoutExpired`, return None.
- **Added:** 2026-04-23.

### TD-oauth-02 — $CLAUDE_CONFIG_DIR not respected
- **Status:** deferred (after rc.4 + rc.5 Keychain work)
- **Priority:** P3
- **Files:** `cli.py:339,370`, `tools/oauth_sync.py:52-56`
- **Fix:** env-var-aware path helper replacing hardcoded
  `~/.claude/.credentials.json` references.
- **Added:** 2026-04-23.

### TD-C-05 — Cache-Control — explicit overrides audit
- **Status:** open (partial — global default landed in v4.5.3)
- **Priority:** P4
- **Files:** `server.py:320, 721` (explicit overrides — intentional).
- **Fix (remaining):** audit the two callers still setting Cache-Control
  directly, confirm they're intentional (`:320` max-age=86400 for
  non-JSON, `:721` no-cache on a specific path) and leave as-is.
- **Added:** auditor 2026-04-24; global default closed in v4.5.3.

### TD-11 — daily_qa.py TESTS coverage gap (15 read-only commands)
- **Status:** open
- **Priority:** P3 (next minor — not blocking v4.5.4)
- **Files:** `daily_qa.py:376-396` (TESTS array), `cli.py:2326-2366` (dispatch dict)
- **Context:** TESTS exercises 14 of cli.py's 39 dispatch entries. The
  v4.5.0 `daily` command was missing from TESTS, which is why its
  shim-drift regression went undetected for 5 days post-publish.
  `daily` is being added in v4.5.4 (this hotfix).
- **Fix:** add a TESTS entry per remaining read-only command. Each needs
  scorer selection (score_smoke vs custom); some may need fixture setup
  for thin-data installs. The 14 commands without smoke coverage:
  `show-other`, `stats`, `insights`, `window`, `waste`, `fixes`, `keys`,
  `realstory`, `burnrate`, `loops`, `block`, `statusline`, `claude-ai`,
  `fix-rules`.
- **Acceptance:** all 14 listed commands have a TESTS entry; `daily_qa.py`
  exits 0 with WOW or expected OK for each on a fresh DB.
- **Untestable in this gate (documented, not deferred):** `dashboard`,
  `init`, `sync-daemon`, `backup`, `restore` (server / interactive /
  daemon / mutating); `qa` (recursion); `scoreboard` (alias of
  `fix-scoreboard`); `scan`, `export`, `measure`, `mcp` (state-mutating,
  need isolated harness); `fix` (subcommand router).
- **Added:** v4.5.4 hotfix audit 2026-04-29.

---

## Resolved in v4.5.3 (this session)

### TD-G-03 — Dashboard brief card stale across midnight
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `templates/dashboard.html` — `renderDailyBrief()` now invoked
  inside `refresh()` timer.

### TD-A-06 — Recommendation ranking FIFO
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `daily_report.py:194-205` — saving extraction now includes
  `savings` / `cost` / `cost_usd` aliases.

### TD-E-01 — Per-project CLAUDE.md not scanned
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `baseline_scanner.py:105-168` — scans `BURNCTL_PROJECT_ROOTS`
  env var + default `~/projects ~/code ~/dev ~/src ~/work` parents
  alongside the back-compat `~/.claude/projects/` walk.

### TD-F-03 — classify_version unit tests
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `tests/test_version_check.py` (11 new tests).

### TD-I-02 — Scanner hook integration tests
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `tests/test_scanner_hooks.py` (6 new tests).

### TD-F-09 — DISABLE_UPDATES doc missing from v2.1.119 warning
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `version_check.py:134`.

### TD-N-1 — No default Cache-Control on JSON responses
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `server.py:1563-1573` — `_serve_json` now sets
  `Cache-Control: no-cache, must-revalidate`.

### TD-N-2 — Symlink cycle guard in baseline_scanner
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `baseline_scanner.py:73-89` — `_already_seen` helper with
  realpath-based dedup across all three path-walking scans.

### TD-M-2 — baseline_readings retention policy
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `db.py` + `scanner.py` — `prune_old_baseline_readings(days=90)`
  wired into scanner end-of-run.

### TD-M-3 — Researcher cron staleness not caught
- **Status:** resolved (2026-04-24, v4.5.3)
- **File:** `daily_qa.py` — `check_researcher_staleness()` with fallback
  to newest dated file; DOD >25 h, OK 12-25 h, WOW <12 h.

### TD-M-1 — F4 design doc authored
- **Status:** resolved (doc-level); implementation deferred to v4.7 —
  see **TD-A-04**.
- **File:** `docs/f4-design.md`.

### TD-G-01 — Hardcoded version string in brief card
- **Status:** resolved (2026-04-24, v4.5.2)
- **File:** `templates/dashboard.html:2204` — now uses `{{ VERSION }}`.

### TD-G-02 — Misleading EST. DAILY COST label for plan users
- **Status:** resolved (2026-04-24, v4.5.2)
- **Files:** `daily_report.py:115-145`, `cli.py:2141-2150`,
  `templates/dashboard.html:2227-2237` — Max/Pro/Team users see
  "API EQUIV TODAY" with plan note.

### TD-B-05 / TD-B-06 — subagents/ scanning
- **Status:** resolved (pre-existing, verified 2026-04-24)
- **File:** `scanner.py:230-365` — `_parse_subagent_info`, path detection,
  parent-uuid inheritance.

### TD-H-04-d — _insight_exists_recent dedup
- **Status:** resolved (pre-existing, verified 2026-04-24)
- **File:** `insights.py:43-49` (29 call sites). Note: this is the dedup
  *pattern*; the separate **TD-H-04** verdict-staleness item remains open.

### TD-K-03 — Stashes lingering across sessions
- **Status:** resolved (2026-04-24, v4.5.3)
- **Action:** `stash@{0} session37-done-entry-wip` and
  `stash@{1} ux3-state2-changelog-wip` both contained only CHANGELOG.md
  text about already-shipped work. Dropped after inspection.

---

## Archive — original log (pre-consolidation, 2026-04-23)

### oauth_sync.py — subprocess hang risk
(Now tracked as **TD-oauth-01**.)

`tools/oauth_sync.py:89-93` calls `subprocess.check_output` on the
`security find-generic-password` binary without a `timeout=` kwarg.
If the macOS Keychain is locked when the cron runs, the call prompts
for user password and hangs indefinitely. Fix: add `timeout=2.0`, catch
`subprocess.TimeoutExpired`, return None. Low priority — cron retries
next hour anyway — but blocks any code reuse into interactive paths
like cli.py.

### $CLAUDE_CONFIG_DIR not respected anywhere
(Now tracked as **TD-oauth-02**.)

Zero grep hits repo-wide for `CLAUDE_CONFIG_DIR`. Both
`cli.py:339` and `cli.py:370` hardcode `~/.claude/.credentials.json`.
`tools/oauth_sync.py:52-56` hardcodes three sibling paths. Users with
custom config dirs (e.g. `~/.claude-work/`) get silent tier-1 detection
failure; they currently survive via tier-2 network call. Fix: replace
expanduser calls with env-var-aware helper, update CREDENTIALS_PATHS
in oauth_sync.py. Defer until after rc.4 (Phase 4) and rc.5 (Keychain).

### Zero-session waste_events verdict
(Now tracked as **TD-H-05**.)

fix_measurements rows with sessions_count=0 can still produce
non-trivial delta.waste_events.pct_change because waste events fire
from non-session triggers. Verdict code returns "worsened"/"improving"
based on the numeric delta — but a user reading "worsened" for a
project they haven't touched in weeks may find it misleading. Options:
tag with measurement_confidence, require sessions_since >= N, or
exclude non-session-triggered events. Not urgent — 1 of 8 live rows.

### Verdict staleness on verdict-logic changes
(Now tracked as **TD-H-04**.)

`determine_verdict` output is stored in `fix_measurements.verdict` at
write time. Dashboard reads the stored string via `server.py:515-522`
without recomputing. CLI `fix-scoreboard` correctly recomputes via
`compute_delta` at render time (`fix_scoreboard.py:122`). Impact: any
change to verdict logic creates silent drift — rows measured under old
logic keep their old verdict until re-measured. rc.4 hit this: fix 12
(WikiLoop repeated_reads) still rendered insufficient_data on the
dashboard after rc.4 deployed, because its stored row was written under
rc.3. `auto_measure_pending()` from the scan cron self-corrects within
5 min of next scan; manual kick accelerates. Pick an approach before
the next verdict change.
