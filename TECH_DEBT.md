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

### TD-12 — daily_qa.py exit code on DOD inconsistent with documented contract
- **Status:** open
- **Priority:** P3 (gate semantics — affects pre-publish guard reliability)
- **Files:** `daily_qa.py` (the post-`run_all_tests` exit logic)
- **Context:** CLAUDE.md states "Exit 0 (all WOW) → safe; Exit 1 (any
  OK) → review; Exit 2 (any DOD) → STOP. Do not publish." Observed in
  v4.5.4 hotfix: pre-publish run with `dod_count=1` exited 0 (should
  be 2); post-publish run with `dod_count=9` correctly exited 2. The
  contract holds for the DOD>1 case but appears soft for DOD=1.
- **Fix:** audit the exit-code mapping in `daily_qa.py`. Likely cause:
  the WOW count is checked first and the DOD branch is gated on a
  condition that's silently false in some configurations. Confirm by
  running `python3 daily_qa.py; echo $?` against a synthetic DOD-only
  state. Document the actual semantics in CLAUDE.md if the contract
  is intentionally weaker than documented.
- **Acceptance:** any run with `dod_count > 0` exits 2; any run with
  `ok_count > 0` and `dod_count == 0` exits 1; clean run exits 0.
- **Added:** v4.5.4 hotfix audit 2026-04-29.

### TD-13 — db.py:get_conn() phase-2 caller hardening + path-discipline
- **Status:** open (Phase 1 closed in v4.5.5)
- **Priority:** P2 for Phase 2 (108 caller sites still traceback on
  None); P3 for Phase 3 (path consolidation per TD-01)
- **Files:** `db.py:get_conn`, plus 109 caller sites across `server.py`,
  `cli.py`, `mcp_server.py`, `claude_ai_tracker.py`, `daily_report.py`
  (Phase 1 done), `insights.py:59`, `fix_generator.py:703`,
  `waste_patterns.py:359`.
- **Context:** v4.5.4's daily_qa post-publish run exposed a cascade —
  cmd_daily's daily_report.get_conn() was auto-creating an empty DB
  at the npx install dir, then 7 subsequent commands' load_db() found
  that empty file and tracebacked on missing tables. v4.5.5 fixes the
  root by making get_conn() existence-check + return None, and adds
  a None-guard to daily_report.build_daily_brief() so the headline
  v4.5.0 command renders a graceful "no data yet" brief instead of
  tracebacking. The remaining caller sites still traceback on None
  (AttributeError instead of OperationalError) — a clean DB-boundary
  failure but still a bad UX for fresh-install users.
- **Acceptance (Phase 1, closed in v4.5.5):** db.get_conn() returns
  None when no DB exists; init_db() preserves auto-create via
  `_open_or_create` helper. daily_report.build_daily_brief() handles
  None gracefully (returns minimal-shaped brief; cmd_daily printer
  renders all standard headers via existing available=False branches).
- **Acceptance (Phase 2, deferred to v4.5.6):** every other caller of
  db.get_conn() handles None gracefully — graceful "no data yet"
  placeholders instead of tracebacks. Note: most cli.py cmd_* handlers
  call init_db() before get_conn(), which auto-creates, so they're
  already safe in practice. The risk surface is the no-init-db
  callers: `daily_report.py` (Phase 1 done), `insights.py:59`,
  `fix_generator.py:703`, `waste_patterns.py:359`, plus any of the
  ~70 server.py sites that don't go through init_db on the request
  path. Audit each, add None-guards, ship v4.5.6.
- **Acceptance (Phase 3, deferred to v4.6.0):** consolidate the
  load_db / get_conn duplication per TD-01. Today, 10 modules each
  define their own `load_db()` plus `db.get_conn()` exists separately.
  After Phase 3, single canonical `db.open_local_db()` (or similar)
  used everywhere, with a clear "create vs read-only" semantic.
- **Added:** v4.5.4 post-publish smoke 2026-04-29.

### TD-14 — unittest test pollution into ~/.burnctl/data/usage.db
- **Status:** open
- **Priority:** P3 (test isolation hygiene; not user-facing)
- **Files:** unknown — needs `find tests/ -name "*.py" -exec grep -l "init_db\|get_conn\|DB_PATH" {} \;`
  to identify the source
- **Context:** During v4.5.5 hotfix validation, an empty
  `~/.burnctl/data/usage.db` (4096 bytes, no tables, mtime ~11:12 UTC)
  appeared after `python3 -m unittest discover -s tests -v`
  completed. The file persisted across the test run, polluting
  subsequent integration tests that depend on the user-fallback
  path being absent. Pre-existing — not introduced by v4.5.5.
- **Fix:** identify which test fixture creates the leak. Likely
  a test that calls `init_db()` without monkey-patching DB_PATH
  to a tempdir — letting init_db pick the second candidate from
  get_conn's tuple (`~/.burnctl/data/usage.db`) when DB_PATH's
  local data dir doesn't exist. Add proper isolation:
  monkey-patch DB_PATH in setUp, restore in tearDown.
- **Acceptance:** running the full test suite from a fresh
  environment leaves no files in `~/.burnctl/`.
- **Added:** v4.5.5 hotfix validation 2026-04-29.

### TD-15 — Pro account panel reads as "tracking broken" not "CLI not used"
- **Status:** open
- **Priority:** P2 (UX clarity for new Pro users)
- **Files:** dashboard account-panel renderer (`templates/dashboard.html`
  or whichever JS/template emits the per-account section)
- **Context:** Pro account panel shows
  `"No Claude Code sessions — browser tracking only"` while the
  immediately preceding rows show browser tracking IS working
  (5h window 8.0%, 7d window 8.0%). A user reading cold can
  interpret the bottom message as "tracking is broken" rather
  than "this account type has no CLI usage, only browser
  sessions."
- **Fix:** reword. Candidates:
  1. `"Browser-only account — no CLI sessions on this plan"`
  2. `"Pro plan: browser sessions tracked above; no CLI sessions
     on this account"`
  3. Remove the "No Claude Code sessions" line entirely when
     browser data is present in the same panel.
- **Acceptance:** a Pro user reading the panel cold can tell
  that tracking is working and that the absence of CLI sessions
  is a plan property, not a tooling failure.
- **Added:** dashboard smoke 2026-04-29.

### TD-16 — "Recent Browser Sessions" widget gates on chat titles, not data
- **Status:** resolved (2026-04-30)
- **Priority:** P2 (data invisibility — real sessions read as zero)
- **Files:** `server.py` (`/api/browser-chats-recent` handler),
  `templates/dashboard.html` (`renderBrowserChats`)
- **Context:** Widget showed `0` with red counter when
  `chat_title_sync.py` hadn't been run, even when underlying
  browser session data existed in `claude_ai_snapshots`. The
  empty-state was gated on chat-title presence rather than on
  session-data presence — real data was invisible until a separate
  sync step ran. User reported "I have three sessions opened"
  when widget showed 0.
- **Fix:** show session counts and IDs even when titles are
  missing, OR change the empty-state copy to explicitly say
  `"no chat titles synced — run chat_title_sync.py"` instead of
  a bare `0`.
- **Acceptance:** the widget never shows `0` when there is
  actual browser session data in the DB. A `0` reading means
  "no session data," not "no titles."
- **Added:** dashboard smoke 2026-04-29.
- **Resolution:** Backend `/api/browser-chats-recent` now falls
  back to `browser_sessions.detect_browser_sessions` when titled
  rows are empty for the 3-day window. Each row carries a
  `source` field (`'title'` | `'snapshot'`); snapshot-derived rows
  render with an italic "browser session" label instead of the
  titled-row format. Empty-state copy rewritten to "No browser
  activity in the last 3 days." — no longer references the
  unshipped `chat_title_sync.py`. Either/or semantics (no
  partial-coverage merge); follow-up work tracked as TD-31.
  Resolved by this commit (see git blame).

### TD-17 — Insights table missing upsert key; duplicates accumulate per scan
- **Status:** resolved (misdiagnosed) (2026-04-30)
- **Priority:** P2 (original framing — see Resolution)
- **Files:** `insights.py` (`insert_insight` call sites — every
  rule), `db.py` (`insights` table schema), migration if a UNIQUE
  constraint is added retroactively
- **Context:** Each scan inserts new insight rows instead of
  upserting on `(insight_type, target, content_hash)`. Example
  observed today: `"Tidify uses Opus but avg response is 533 
  tokens — Sonnet saves ~$4170.91/mo"` at 01:34 PM and 
  `"... avg response is 520 tokens — Sonnet saves ~$4075.31/mo"` 
  at 01:31 AM (~12 hours apart). Same rule, same project, slightly 
  drifting numbers, two rows. Result: dashboard shows ~45 insights 
  when ~15-20 unique findings exist. Affects browser-derived 
  insights (cost spikes, sub-agent unbounded scope) and CLI-derived 
  insights equally. Likely the highest-ROI quality fix — kills the 
  "messy report" perception.
- **Fix:** add an upsert key. Options:
  1. UNIQUE constraint on `(insight_type, target, hash(message))`
     plus `INSERT OR REPLACE` in `insert_insight`.
  2. Application-level dedup: before insert, check for an
     existing row matching `(insight_type, project)` within the
     last N hours and update in place.
  3. Periodic dedup pass at end of scan (lower-effort, less
     correct under concurrent scanners).
  Option 1 is preferred — single source of truth at the DB level.
- **Acceptance:** running two consecutive scans on the same data
  does not increase the insight count for unchanged findings.
  Dashboard insight count reflects unique findings, not
  scan-event count.
- **Added:** dashboard smoke 2026-04-29.
- **Resolution (2026-04-30):** Investigation showed the framing
  was wrong. Two existing dedup layers handle this correctly:
  - **Write-side**: `_insight_exists_recent` (insights.py:46,
    12h default window with per-rule overrides 6h/24h/48h/168h)
    skips re-emit while a finding is fresh.
  - **Read-side**: `get_insights` (db.py:1451) collapses on key
    `(insight_type, project, message)` — `message` deliberately
    included so window_risk snapshots that differ only by
    numeric text ("48%" vs "39%") survive as distinct cards.

  Both work as designed. Duplicates exist because: 12h debounce
  + multi-day TTL retention + intentionally-drifting metric
  values (Tidify model_waste: 265 → 533 → 551 tokens across
  13 days, $3266 → $4170 → $4273 projected savings) means each
  message-distinct row is preserved on purpose — the system is
  surfacing real metric change, not duplicating findings.

  Original proposed fix (UNIQUE on `(insight_type, project,
  hash(message))`) would not collapse drifting-message rows;
  proposed `(insight_type, project)`-only collapse at the read
  path would hide intentional observations.

  No code shipped. Two follow-up TDs filed:
  - **TD-25** — rule debounce windows hardcoded across 26 call
    sites (rule 1 violation: config-as-data).
  - **TD-26** — dashboard renders related observations as N
    separate cards; group-by-(type,project) at render layer is
    the real "messy report" fix.

### TD-18 — Reconcile burnctl windows + costs against Anthropic settings (verification gate)
- **Status:** open
- **Priority:** P1 (verification gate before F4 measurement work)
- **Files:** `mac-sync.py` (window definitions), server-side
  `claude_ai_tracker.py` poll path, `cli.py` account labelling,
  dashboard account-panel renderer
- **Context:** 2026-04-29 ~14:00 IST smoke test compared burnctl
  dashboard account panels against Anthropic settings page in
  user's browser. Findings:
  - Pro account 7d window: burnctl 8.0% / Anthropic
    "Weekly all models 8%" — **MATCHES**.
  - Pro account metered overage: Anthropic shows
    `"$21.36 of $50 extra usage (43%)"`. burnctl does NOT
    surface this anywhere on the Pro panel — **GAP**.
  - Max account 5h browser 80% / 7d browser 40%: Anthropic
    settings NOT YET COMPARED for Max — needed.
  - Account labelling: burnctl labels accounts "Personal (Max)"
    and "Personal (Pro)" but the Pro account is actually
    Confluent-managed (Anthropic shows
    `"Claude is only approved for use via your Confluent id"`).
    User confirmed pnjegan = work account. Labels in burnctl 
    therefore mislabel the work account as personal.
  Filed as P1 verification gate before F4 because F4 builds on
  the measurement layer. If burnctl's window calculations don't
  match Anthropic's truth, downstream measurement work builds on 
  suspect ground.
- **Fix:** tomorrow morning before F4 (~15 min):
  1. Compare Max account Anthropic settings against burnctl panel.
  2. Read the 5h/7d window definitions in `mac-sync.py` and the
     server-side claude_ai poll path; compare units (rolling vs
     calendar, all-models vs Opus-only, weekly reset boundary).
  3. Verify account label source — should differentiate Confluent-
     managed from personal accounts.
  4. Decide: file precise sub-TDs with reproduction, OR close
     this as "checked, definitions differ as documented, no
     bug" with the explanation surfaced in panel labels.
- **Acceptance:** F4 work proceeds once one of these holds. If 
  reconciliation completes cleanly, no further action; F4 starts 
  as planned. If a gap is found, file precise sub-TDs and re-scope 
  F4 around the finding.
- **Added:** Anthropic settings comparison 2026-04-29 ~14:00 IST. 
  NOT a confirmed bug — a verification gate.

### TD-25 — Rule debounce windows hardcoded across 26 call sites
- **Status:** open
- **Priority:** P2 (rule 1 violation — config-as-data principle)
- **Files:** `insights.py` (~26 call sites with hardcoded
  `hours=N` values), `insights.py:46`
  (`_insight_exists_recent` default)
- **Context:** Each rule passes a debounce window inline to
  `_insight_exists_recent(conn, type, project, hours=N)`.
  Current spread: 6h (2 budget rules), 12h (default — 15
  rules), 24h (5 rules), 48h (2 rules), 168h (3 rules).
  Tuning dashboard noise level (e.g., "model_waste once a
  week, window_risk every hour") requires a code edit across
  26 lines instead of a config flip. Violates standing rule 1
  (no hardcoding for values that change semantically over
  time). Surfaced during TD-17 investigation 2026-04-30.
- **Fix:** Move per-rule windows to config — a dict in
  `config.py` keyed by `insight_type`, with 12h default
  fallback. Adjust `_insight_exists_recent` to look up the
  window from config when `hours` is not passed explicitly.
  Backward-compatible: existing inline `hours=` overrides
  still work; remove them in a follow-up cleanup.
- **Acceptance:** A user can change any rule's debounce window
  by editing one config value with no code edit. The 26 inline
  `hours=` overrides are either removed or documented as
  legacy.
- **Added:** TD-17 investigation 2026-04-30.

### TD-26 — Dashboard renders related observations as N separate cards
- **Status:** open
- **Priority:** P3 (F4-adjacent — surface noise reduction)
- **Files:** dashboard insights renderer
  (`templates/dashboard.html` or the JS that lays out insight
  cards), possibly `/api/insights` response shape if grouping
  is server-side
- **Context:** When the same `(insight_type, project)` emits
  multiple observations over time with drifting metrics
  (model_waste: 265 → 533 → 551 tokens; window_risk: 39% →
  48% → 60% throughout a day), the dashboard renders each as
  an independent card. Visually reads as "messy report" /
  duplicate findings to users, even though each card is
  intentionally distinct (TD-17 investigation confirmed the
  data layer is correct). 16 of the current ~50 visible cards
  are members of multi-observation groups.
- **Fix:** Group-by-`(insight_type, project)` at the dashboard
  render layer. Show one card per group with the most-recent
  observation prominent and N older observations stacked /
  collapsible. Server-side `get_insights` stays unchanged
  (preserves the documented design that message-distinct rows
  are kept queryable).
- **Acceptance:** Dashboard shows one card per active finding
  with timeline drill-in. Visible card count drops from ~50
  (LIMIT 50 with message-distinct dedup) to ~16-20 unique
  findings. Grouped cards show latest values prominently with
  expand-for-history.
- **Added:** TD-17 investigation 2026-04-30.

### TD-27 — Account labels are user-supplied at config time, no auto-derivation
- **Status:** open
- **Priority:** P3 (cosmetic, but affects work account labeling)
- **Files:** `tools/mac-sync.py:_verify_with_claude` (~L240),
  `claude_ai_tracker.py:fetch_org_id` (~L81), `accounts` table
  schema, dashboard account-panel renderer
- **Context:** `accounts.label` is purely user-supplied via
  `/accounts` UI (cli.py:531). The Anthropic `/api/account`
  membership response includes `organization.name` and
  organization metadata that would let us auto-derive
  accurate labels (e.g., "Confluent (Work, Pro)" instead of
  "Personal (Pro)" for Confluent-managed accounts).
  Currently discarded at `tools/mac-sync.py:240-264` — the
  organization object is read for UUID only; name and
  managed-by are dropped. Surfaced during TD-18 investigation
  2026-04-30.
- **Fix:** Capture `organization.name` (and any managed-by
  indicator) from `/api/account` memberships in
  `_verify_with_claude`. Add `organization_name` column to
  `claude_ai_accounts` schema. Surface in dashboard label
  when present, fall back to user-supplied label when not.
  ~30 lines across 3 files plus a migration.
- **Acceptance:** Work-managed accounts auto-display their
  organization name; users can still override via `/accounts`
  UI. No hardcoded "Confluent" or org-specific strings
  anywhere in the codebase.
- **Added:** TD-18 investigation 2026-04-30.

### TD-28 — Hero card "Browser-only account" headline reads as negative status
- **Status:** open
- **Priority:** P3 (cosmetic, narrow trigger condition)
- **Files:** `templates/dashboard.html:994-1001` (hero card
  fallback for browser-only accounts when a specific account
  is selected)
- **Context:** When a user selects a specific account on the
  dashboard and that account has zero CLI sessions but active
  browser tracking, the hero card replaces the normal
  metrics card with a stub that headlines "Browser-only
  account". The body text ("No Claude Code sessions tracked.
  Window usage comes from claude.ai browser.") reads as a
  reasonable explanation, but the headline frames the
  account by absence rather than by what it IS. A user
  looking at their working Pro account sees the headline
  and reads "something is missing here."
- **Fix:** Reframe the headline to lead with what the
  account does (e.g., "claude.ai browser tracking" or
  "Browser sessions") rather than what it lacks. Consider
  showing the actual 5h/7d window numbers in the hero card
  instead of the stub — gives the user useful data instead
  of a status message.
- **Acceptance:** A user selecting a browser-only account
  sees usable window data in the hero card, not a "this
  account is missing CLI" stub.
- **Added:** TD-15 fix 2026-04-30.

### TD-31 — `chat_title_sync.py` referenced but not shipped
- **Status:** open
- **Priority:** P3 (documentation/consistency drift, no user-facing
  failure now that TD-16 is resolved)
- **Files:** `chat_title_sync.py` (does not exist); referenced from
  `server.py:930`, `server.py:1338`, `db.py:414`, `why_limit.py:406`,
  `why_limit.py:453`, `templates/dashboard.html:1219` (header
  comment), `TECH_DEBT.md` (this entry + TD-16 historical context),
  `CHANGELOG.md` (multiple entries), and `README.md` (none yet —
  but missing where it should be).
- **Context:** A Mac-side collector named `chat_title_sync.py` is
  referenced in 11+ places across the codebase as the populator of
  `browser_chat_sessions`. The script has never been committed to
  the repo. Until TD-16, the dashboard empty-state instructed users
  to run a script they had no way to obtain. TD-16 removed the
  user-facing reference; the in-code references remain.
- **Fix (pick one):**
  (a) Build and ship the Mac collector — Chrome/Vivaldi history.sqlite
      reader that POSTs to `/api/browser-chats`. The endpoint
      contract is already implemented at `server.py:1342–1405`.
  (b) Excise all references — drop the comments in `server.py`,
      `db.py`, `why_limit.py`, and the dashboard template; keep
      `/api/browser-chats` for any future implementation but stop
      advertising a script that doesn't exist.
- **Acceptance:** zero references in shipped code to a script that
  doesn't exist in the repo; either the file is committed and
  documented in README, or the references are gone.
- **Added:** TD-16 fix 2026-04-30.

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
