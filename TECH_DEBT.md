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
- **Files:** `cli.py` (2,443 LOC as of 2026-07-18 debt-audit; was 2,378)
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
- **Status:** resolved (2026-04-30) by `4475f44`
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
- **Resolution:** Reworded the Pro-only-account stats line in
  `templates/dashboard.html:1157` from "No Claude Code sessions
  — browser tracking only" to "Browser sessions tracked above;
  CLI sessions track separately when active". The new copy
  describes the working state factually instead of framing the
  account by absence. Shipped in `4475f44` (2026-04-30 morning).
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
- **Status:** resolved (2026-04-30)
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
- **Resolution:** Reconciliation completed against Anthropic's
  claude.ai/settings/usage for both Pro and Max accounts. Pro
  weekly matches exactly (8% / 8.0%). Max weekly within 1pp
  polling-time tolerance (11% Anthropic / 10.0% burnctl). Max
  "Current session" (41%) does not align with burnctl's 5h window
  (34.0%) because the metrics are defined differently — Anthropic
  measures time-since-first-message session quota, burnctl
  measures a rolling 5-hour token window. This is a label clarity
  issue, not a math bug; filed as TD-32. Anthropic's Max settings
  also expose a "Sonnet only" weekly sub-quota burnctl doesn't
  currently track; filed as TD-33. Overage is server-computed by
  Anthropic and read directly by burnctl, so it self-reconciles.
  F4 work unblocked — no measurement gap requires re-scoping.

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
- **Status:** closed (2026-05-01) — references excised from `db.py`,
  `why_limit.py`, `server.py`, and `templates/dashboard.html`.
  Endpoints (`/api/browser-chats`, `/api/browser-chats-recent`) and
  schema (`browser_chat_sessions`) retained as live unused capability
  awaiting a future collector. Removal of the unused capability is a
  separate scope decision.
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

### TD-32 — 5h window label clarity (rolling tokens vs session quota)
- **Status:** open
- **Priority:** P3
- **Files:** `templates/dashboard.html` (window-panel render)
- **Context:** burnctl labels the rolling 5-hour token window as
  "5h window" / "5-hour window". Anthropic's settings page shows
  a different metric called "Current session" that measures
  time-since-first-message session quota. Users who compare the
  two will see different numbers and think burnctl is wrong —
  surfaced during TD-18 reconciliation 2026-04-30.
- **Fix:** Annotate the burnctl label to disambiguate. Options:
  "5h tokens", "5h rolling window", or "5-hour window (tokens)".
  Pick whichever reads cleanest; copy-only change.
- **Acceptance:** Label distinguishes burnctl's rolling token
  window from Anthropic's session quota; reasonable user does
  not expect numeric parity between the two.
- **Added:** TD-18 reconciliation 2026-04-30.

### TD-33 — Sonnet-only weekly sub-quota unsurfaced (Max plan)
- **Status:** open
- **Priority:** P3
- **Files:** `tools/mac-sync.py` (poll), `db.py` (schema),
  `server.py` (endpoint), `templates/dashboard.html` (render)
- **Context:** Anthropic's Max plan settings page exposes a
  "Sonnet only" weekly sub-quota separate from "All models".
  burnctl polls and renders only the All-models weekly. Max users
  have an additional bucket they cannot see in burnctl — surfaced
  during TD-18 reconciliation 2026-04-30.
- **Fix:** Extend mac-sync.py to capture the Sonnet-only bucket
  from Anthropic's API response, persist alongside existing
  weekly fields, render as an additional bar on Max account
  panels (gated on `plan === 'max'`).
- **Acceptance:** Max account panel shows both All-models and
  Sonnet-only weekly bars with reconciling values vs Anthropic's
  settings page.
- **Added:** TD-18 reconciliation 2026-04-30.

### TD-34 — daily_snapshots.cache_hit_rate unit drift (CACHE-UNITS)
- **Status:** open
- **Priority:** P2 (silent 100x errors on any window-aggregate read)
- **Files:** `daily_snapshots` table, writers TBD (recent commit
  changed compute-before-insert from percent to fraction).
- **Severity:** real bug, reproducible, has evidence.
- **Surfaced during:** DASH-001 reproducibility check 2026-05-08
  (DASH-001 itself closed wontfix — see Rule #24 evidence pack).
- **Symptom:** Same column `daily_snapshots.cache_hit_rate` stores
  values in two different units depending on row date:

  | date       | account      | project | cache_hit_rate | unit            |
  |------------|--------------|---------|----------------|-----------------|
  | 2026-05-08 | personal_max | burnctl | 0.9008         | fraction (0-1)  |
  | 2026-05-07 | personal_max | burnctl | 0.9445         | fraction (0-1)  |
  | 2026-05-07 | personal_max | Tidify  | 0.8799         | fraction (0-1)  |
  | 2026-05-07 | personal_max | Other   | 0.9067         | fraction (0-1)  |
  | 2026-05-06 | personal_max | Other   | 88.2           | percent (0-100) |
  | 2026-05-06 | personal_max | burnctl | 61.2           | percent (0-100) |
  | 2026-05-05 | personal_max | Tidify  | 92.6           | percent (0-100) |

- **Reproducibility:** Confirmed via SQL pull on 2026-05-08 ~10:00 IST.
  Pattern: rows written from 2026-05-07 onward use fraction; rows from
  2026-05-06 and earlier use percent. Inflection point falls within
  the May 7 spike day where 547 sessions were recorded.
- **Likely cause:** A recent commit changed how `cache_hit_rate` is
  computed before insert into `daily_snapshots`, switching from
  percentage to fraction. Backfill of older rows did not happen.
- **Impact:** Downstream consumers reading
  `daily_snapshots.cache_hit_rate` receive 100x discrepancy between
  old and new rows. Any aggregate over a window straddling
  2026-05-06 / 2026-05-07 boundary produces nonsense. Currently
  `/api/projects` appears to compute freshly from `sessions` table
  (Formula A) rather than reading from `daily_snapshots`, so
  dashboard headline is unaffected — but any future feature that
  reads `daily_snapshots` directly will break silently.
- **Fix shape candidates (operator decides):**
  1. Backfill: re-run aggregation with consistent unit for all
     historical rows. Pick fraction or percent, apply uniformly.
  2. Forward-only: leave history as-is, document the boundary,
     coerce on read in any consumer that reads this column.
  3. Schema fix: add `cache_hit_rate_unit TEXT` column ('fraction'
     vs 'percent') and require explicit conversion at read.
- **Acceptance:** All rows in `daily_snapshots.cache_hit_rate` use
  one declared unit (or the unit is explicit per row), and at least
  one downstream consumer reads safely across the May 6/7 boundary.
- **Added:** 2026-05-08, surfaced during DASH-001 inventory.

### TD-35 — Two cache_hit formulas in codebase (CACHE-FORMULA-DRIFT)
- **Status:** open
- **Priority:** P3 (cosmetic today; real bug if either path becomes the headline source)
- **Files:**
  - Formula A (4-term denom): `analyzer.py:64`, `analyzer.py:255`,
    `fix_tracker.py:159` — `cache_read / (cache_read + cache_create + input + output) * 100`
  - Formula B (2-term denom): `server.py:550`, `cli.py:1416` —
    `cr / max(cr + in_tok, 1) * 100`
  - Subtitle on dashboard claims Formula B but reads Formula A:
    `templates/dashboard.html:1092` — sub: "cache reads / (cache reads + input)"
- **Symptom:** Two different cache_hit definitions exist. On the
  same data, A produces 84-98%, B produces 99.996% (when input is
  small vs cache_read). Live `/api/projects` returns Formula A.
  Dashboard subtitle describes Formula B. Mismatch is cosmetic
  today — but if any future feature surfaces Formula B as the
  headline, two answers become user-visible for "cache hit rate".
- **Fix shape:** Pick one canonical formula, document it once in
  `docs/schema.md`, replace the other in all 5 call sites, fix the
  dashboard subtitle to match.
- **Added:** 2026-05-08, surfaced during DASH-001 inventory (paired
  with TD-34).

### TD-36 — npm tarball leaks `tools/get-derived-keys.py`
- **Status:** resolved (f9bf36b, 2026-05-08)
- **Resolved by:** commit f9bf36b — replace tools/*.py glob with
  explicit allowlist in package.json files. Acceptance verified:
  npm pack --dry-run | grep get-derived-keys returns empty.
- **Priority:** P2 (ship-blocker — leaks maintainer-only tool to npm users on next publish)
- **Files:** `package.json` `files` array OR `.npmignore`
- **Severity:** real bug, reproducible, has evidence.
- **Surfaced during:** burnctl-auditor smoke test 2026-05-08
  (Check 5 npm hygiene). Verified independently via Rule #24
  reproducibility check.
- **Evidence:** `npm pack --dry-run` from project root includes:
  ```
  npm notice 3.7kB   tools/get-derived-keys.py
  ```
  This file is a maintainer-only utility for deriving local OAuth
  keys; it must not ship to npm users.
- **Standing rule violated:** *"npm pack --dry-run before every
  publish — no .env, no usage.db, no CLAUDE.md in tarball"*
  (rules/burnctl.md). `tools/get-derived-keys.py` is implicitly
  in the same forbidden category — auditor agent's check 5 lists
  it explicitly.
- **Fix shape (operator decides):**
  1. Add `tools/get-derived-keys.py` to `.npmignore`.
  2. Remove `tools/` from `package.json` `files` array and
     explicitly enumerate the user-facing files
     (`tools/chat_title_sync.py`, `tools/mac-sync.py`,
     `tools/oauth_sync.py`, `tools/sync-daemon.py`,
     `tools/hooks/post-session.sh`,
     `tools/hooks/prevent_repeated_reads.py`).
  3. Move `tools/get-derived-keys.py` outside the `tools/`
     directory if it should never have been there.
- **Acceptance:** `npm pack --dry-run | grep get-derived-keys`
  returns empty before next `npm publish`.
- **Added:** 2026-05-08, surfaced during auditor smoke test
  + Rule #24 reproducibility check (filed as B4 in
  `audit-reports/2026-05-08-auditor-blocker-triage.md`).

### TD-37 — burnctl-auditor checks 2 and 4 produce false-positive blockers
- **Status:** open
- **Priority:** P3 (auditor will keep firing NO-GO nightly until refined; tolerable noise but degrades signal quality)
- **Files:** `~/.claude/agents/burnctl-auditor.md`
- **Severity:** agent-quality bug, reproducible, has evidence.
- **Surfaced during:** Rule #24 triage of auditor smoke-test
  blockers 2026-05-08. 3 of 4 auditor blockers (B1, B3 fully
  WONTFIX as false positives; B2 WONTFIX-DEFERRED) were not real
  ship-blockers.
- **Symptom 1 (Check 2 — Hardcoded paths):** The grep
  `grep -rn "projects/burnctl\|/root/projects" *.py bin/` flags:
  - Canonical multi-path fallback list candidates (legitimate per
    `overhead_audit.py::load_db()` pattern)
  - The leak detector itself (`daily_qa.py:90-91`
    `_DEFAULT_LEAK_PATTERNS` literal strings used to *detect*
    leaks, not produce them)
  - Maintainer-only files not in the npm tarball
    (`burnctl_test_runner.py`, confirmed absent from
    `npm pack --dry-run` output)
- **Symptom 2 (Check 4 — Schema drift):** The grep
  `grep -rn "token_cost\|start_time\|waste_type\|fix_id" *.py`
  flags:
  - `waste_events.token_cost` (real schema column in `db.py:267`,
    distinct from `sessions.cost_usd`)
  - `fix_measurements.fix_id` (real FK column in `db.py:295`,
    references `fixes.id`)
  - `start_time` used as in-memory dict keys in
    `browser_sessions.py` (not a DB column reference at all)
- **Root cause:** Both checks grep symbol names without
  discriminating: which *table* the column belongs to, whether
  the symbol is a DB column or a Python identifier, or whether
  the file is shipped to users. Schema-guard agent has the
  table-aware logic; auditor's check 4 should defer to it.
- **Fix shape candidates (operator decides):**
  1. Refine check 2 to exclude (a) fallback-list candidate
     contexts, (b) `_DEFAULT_LEAK_PATTERNS` and similar
     leak-detector tuples, (c) files not in `npm pack --dry-run`
     output.
  2. Replace check 4 with a call to schema-guard's drift report
     (read-only consume), instead of a coarse grep.
  3. Tighten the agent's verdict logic so partial-evidence checks
     emit WARN not BLOCKER.
- **Acceptance:** A clean codebase day produces a `GO` verdict
  from the auditor (today's smoke test produces NO-GO with 1
  real blocker B4 — once B4 is fixed, the auditor should return
  GO, not continue flagging B1+B3).
- **Added:** 2026-05-08, surfaced during Rule #24 triage of
  auditor smoke-test (filed as triage matrix at
  `audit-reports/2026-05-08-auditor-blocker-triage.md`).

### BURNCTL-DATA-1 — Orphan waste_events with no matching sessions row
- **Status:** open
- **Priority:** P3 (data integrity; user-visible symptom currently masked
  by the savings-gate in 8de43b8 — investigate before next verdict-logic
  change)
- **Files:** `fix_tracker.py:115-257` (`capture_baseline` — two
  independent project/time queries with no JOIN); scanner write path
  for `waste_events` and `sessions` (callers TBD).
- **Severity:** medium (data integrity; user-visible symptom currently
  masked by the savings-gate in 8de43b8).
- **Surfaced during:** Fix F follow-up session 2026-05-09 — diagnostic
  trace of fix #12 (WikiLoop) revealed the orphan condition while
  investigating phantom $316.79/mo savings.
- **Symptom (now suppressed):** `compute_delta` produced
  `tokens_saved=1,352,873` and `api_equivalent_savings_monthly=$316.79`
  on a `worsened` verdict, because the attribution math reads
  per-turn token averages (`avg_tokens_per_turn`,
  `avg_cache_read_per_turn`) computed from the `sessions` query while
  `waste_events` counts come from a parallel query with no JOIN.
  When the post-fix sessions window is empty, the per-turn averages
  collapse to 0 and `current.tokens_wasted_*` evaluates to 0 — making
  `baseline - current` a baseline echo, not a measured reduction.
  Suppressed by 8de43b8 (savings-gate) at the user-visible layer; the
  underlying data inconsistency in `waste_events` vs `sessions` remains.
- **Reproducibility:** Fix #12 (WikiLoop). 7 `waste_events` rows exist
  in the post-fix window starting `detected_at >= 1776350376`; the
  `session_id`s those events reference are not present in `sessions`
  for `project='WikiLoop' AND timestamp >= 1776350376` (0 rows). The
  most recent WikiLoop `sessions` row (`timestamp=1775917148`)
  predates the fix by ~5 days. All 7 orphan events were emitted in a
  single scanner run at `detected_at=1776412123`.
- **Hypotheses to investigate:**
  1. Timing — scanner persists `waste_events` before the corresponding
     `sessions` rows are written.
  2. Pruning — `sessions` rows pruned/rotated independently of
     `waste_events` for the same `session_id`.
  3. Predicate mismatch — `capture_baseline`'s sessions query and
     waste_events query use slightly different project/time predicates.
- **Diagnostic starting points:**
  - `fix_tracker.py:115-257` — the two independent queries (sessions
    L130-144, waste_events L168-194). No JOIN, no shared session_id
    predicate.
  - Scanner write path — confirm `waste_events` insert order relative
    to `sessions` insert; check if either path is reachable without
    the other.
  - SQL check on fix #12's WikiLoop:
    ```sql
    SELECT session_id, detected_at FROM waste_events
    WHERE project='WikiLoop' AND detected_at >= 1776350376;
    SELECT session_id, timestamp FROM sessions
    WHERE project='WikiLoop' AND timestamp >= 1776350376;
    ```
    Confirm session_id sets do not intersect (already verified once on
    2026-05-09; rerun before any fix).
- **Decision required before fix:** Should orphan `waste_events` be
  discarded at scan time, or should `capture_baseline` JOIN
  `waste_events` to `sessions` to only count events that have a paired
  session row? Defer this design choice to the investigation session.
- **Fix shape candidates (operator decides):**
  1. Scan-time: drop `waste_events` whose `session_id` has no row in
     `sessions` for the same project/timestamp.
  2. Read-time: rewrite `capture_baseline`'s waste query as `INNER
     JOIN sessions ON session_id` so attribution and counts share a
     single source of truth.
  3. Schema-level: add a NOT NULL FK from `waste_events.session_id`
     to `sessions.session_id` (cascading delete) and treat the current
     orphans as a one-off cleanup.
- **Related commits:**
  - `8de43b8` — savings-gate (suppresses symptom; does not fix root
    cause)
  - `24f7b79` — directional verdict checks (correct; not affected by
    this bug)
- **Related TD entries:** TD-H-05 — Zero-session waste_events verdict
  (UX/verdict-correctness layer; same input data condition surfaces
  there from a different angle).
- **Acceptance:** For every `fix_measurements` row produced by
  `compute_delta`, either (a) `current.sessions_count > 0` AND every
  `waste_events.session_id` in the window has a paired `sessions`
  row, or (b) the gate fires and savings are zeroed with
  `savings_unreliable_reason` set. No silent attribution-collapse
  paths remain.
- **Added:** 2026-05-09, filed during the Fix F follow-up session
  (commits 8e106bf + 8de43b8).

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

### TD-38 — TD-31 reconciliation (`chat_title_sync.py` now exists and ships)
- **Status:** open
- **Priority:** P3 (documentation/ledger drift; no user-facing failure)
- **Files:** `tools/chat_title_sync.py` (now exists), `TECH_DEBT.md`
  (TD-31 entry, lines 551-583), `package.json` (`files[]` array).
- **Context:** TD-31 was marked closed 2026-05-01 on the premise that
  `chat_title_sync.py` "does not exist" and that its references were
  excised (resolution path (b)). That premise no longer holds: the
  file was created 2026-05-04 (`tools/chat_title_sync.py`, 652 lines)
  and is shipped to npm users via `package.json` `files[]` (v4.5.7+).
  In other words, resolution path (a) ("build and ship the Mac
  collector") is what actually occurred, but TD-31's closure narrative
  still describes path (b). The two are contradictory. This is also the
  file an EDR product flagged during 2026-05 triage, so the ledger
  should reflect reality for any future security review.
- **Fix (pick one):** reopen TD-31 and rewrite its resolution to record
  that the collector was built and shipped (path a), OR — if shipping
  the collector was unintended — remove it from `files[]` and re-close
  TD-31 under path (b). Operator decides.
- **Acceptance:** TD-31's status and narrative match the actual state of
  `chat_title_sync.py` (exists + shipped, or removed); no contradiction
  between the ledger and `package.json` `files[]`.
- **Added:** v4.5.8 (2026-05-25).

### TD-39 — `daily_qa.py` false-positives in the VPS sandbox
- **Status:** open
- **Priority:** P2
- **Files:** `daily_qa.py`, possibly `qa-reports/` schema.
- **Context:** `daily_qa.py` exits 2 on a clean release because 15 npx
  commands (`audit`, `daily`, `resume-audit`, `peak-hours`,
  `version-check`, `variance`, `subagent-audit`, `overhead-audit`,
  `compact-audit`, `fix-scoreboard`, `work-timeline` ×2,
  `claudemd-audit`, `mcp-audit`, `why-limit`) crash with exit 1 in the
  VPS sandbox, where npm-registry access for `npx burnctl@latest` is
  unavailable. This has been pre-existing as of at least 2026-05-24:
  the v4.5.7 baseline (`qa-reports/2026-05-24-18.md`) shows the same 15
  DOD (`4 WOW · 1 OK · 15 DOD`). The gate cannot distinguish a real
  "release defect" from a "sandbox network limit", forcing a manual
  waiver on every release — which erodes the gate's value.
- **Fix (pick one):** (a) detect the sandbox (no registry) and skip
  npx-dependent checks with an explicit SKIP status; (b) test the local
  install path (`npm pack` → install the tarball) instead of
  `npx burnctl@latest`; or (c) split checks into "blocking" vs
  "advisory" so environmental noise downgrades to advisory.
- **Acceptance:** a clean release on a network-isolated host produces a
  gate result that is not a false DOD — either a clean exit or an
  explicit SKIP that does not force exit 2.
- **Added:** v4.5.8 (2026-05-25).

### TD-41 — `oauth_sync.py` / `mac-sync.py` ToS audit before broad rollout
- **Status:** open
- **Priority:** P1
- **Context:** Anthropic Consumer Terms Section 3.7 (unchanged since
  Feb 2024) restricts OAuth token use to "Claude Code and Claude.ai
  only." January 2026 enforcement banned tools like OpenClaw/OpenCode
  that routed Pro/Max OAuth tokens through third-party clients.
  burnctl's `oauth_sync.py` reads `~/.claude/.credentials.json` and
  calls `/api/account` + `/api/organizations/{org_id}/usage` with the
  user's Claude Code OAuth token. Arguably in scope (reading own
  usage), arguably not (third-party tool routing). Audit needed before
  sharing burnctl with colleagues at scale — single-user is likely
  fine, multi-user rollout risks ToS enforcement.
- **Files:** `tools/oauth_sync.py`, `oauth_lookup.py`, `tools/mac-sync.py`
- **Resolution paths:**
  a) Confirm acceptable use with Anthropic legal/policy
  b) Migrate to user-pasted usage data (no token reuse)
  c) Restrict to single-user / personal deployment only
  d) Accept risk for limited rollout
- **Added:** v4.5.8 (2026-05-25).

### TD-42 — v5.0 Chrome extension for chat title tracking
- **Status:** open
- **Priority:** P2
- **Context:** `chat_title_sync.py` is removed from the npm tarball in
  v4.5.8 (TD-38 effectively closed by removal, not refactor). The
  killer feature (per-conversation token attribution) must come back
  via an EDR-safe + ToS-safe path. Architecture decided: a Chrome
  extension that reads `document.title` on claude.ai pages and POSTs
  to the localhost burnctl dashboard via a shared connection token.
- **Files (new):** `extension/manifest.json`,
  `extension/content_script.js`, `extension/background.js`,
  `extension/popup.html`, `extension/popup.js`, `extension/icons/`
- **Files (changed):** `server.py` (new `/api/extension-titles` +
  `/api/extension-token` endpoints), `db.py` (new
  `extension_connections` table), `templates/dashboard.html` (new
  `/settings/extension` UI)
- **Plan:** 3 CC sessions (dashboard, extension scaffold, integration)
  + Chrome Web Store submission. Developer-mode testing first, Web
  Store submission after end-to-end works.
- **Added:** v4.5.8 (2026-05-25).

### TD-43 — Auto-detect project ownership (personal vs work/enterprise)
- **Status:** open
- **Priority:** P1 (blocks single-Mac multi-context users from getting
  useful per-context dashboards)
- **Context:** A single Mac may have multiple Claude Code OAuth accounts
  in rotation (e.g. personal Max account + Confluent-issued Max/Team
  OAuth). Today burnctl groups all sessions under one account and one
  bucket ("Other"). For users wanting to see Confluent-only vs
  personal-only views, manual maintained project-name lists are
  fragile. Better: detect OAuth subscription type at scan time and
  auto-tag sessions by tier. Heuristic — Enterprise/Team plan =
  work/company; Pro/Max = personal. User can override.
- **Design questions:**
  a) Does JSONL contain OAuth subscription metadata? Earlier audit
     showed keys (`parentUuid`, `isSidechain`, `userType`, `cwd`,
     `sessionId`, `version`, `gitBranch`, `agentId`, `slug`, `type`) —
     no clear plan field.
  b) If not, can `~/.claude/.credentials.json` `subscriptionType` be
     captured at scan time and attached to subsequent sessions?
  c) Multi-OAuth detection: if user runs two terminals with two OAuths
     in the same `~/.claude/` dir, can we distinguish at all?
  d) Fallback: user-driven tagging UI in dashboard for sessions where
     auto-detection fails.
- **Files (likely):** `scanner.py`, `db.py` (new tag column on
  `sessions`), `server.py` (new tagging endpoint), `templates/`
  (filter UI)
- **Plan:** v4.6 release. 2-3 CC sessions estimated.
- **Added:** v4.5.8 (2026-05-26).

### TD-45 — Non-canonical DB path candidates in duplicated load_db() copies
- **Status:** open
- **Priority:** P3 (fold into TD-01 consolidation)
- **Files:** `browser_sessions.py:64`, `fix_rules.py:30`
- **Context:** Both embed a maintainer-specific fallback
  `~/projects/burnctl/data/usage.db` in their candidate lists, rather than
  the canonical `overhead_audit.py::load_db()` pair
  (`data/usage.db` + `~/.burnctl/data/usage.db`). Flagged NO-GO (B2) by the
  pre-session auditor on 2026-05-26.
- **Why deferred:** ruled out-of-scope for v5.0 Session 1 —
  `browser_sessions.py` is removed in Session 3, `fix_rules.py` is CLI-side
  and untouched this session. New v5.0 code uses the canonical pattern, so no
  new instances are introduced.
- **Fix:** drop the maintainer fallback; converge on the canonical pair as
  part of the TD-01 `db.open_local_db()` extraction.
- **Added:** v5.0 S1 pre-session audit (2026-05-26).

### TD-46 — Session-resume cold-cache replay burn (upstream #71659); staged gate awaiting approval
- **Status:** in_progress (dry-run fix staged, human approval + VERIFY pending)
- **Priority:** P2 (single cold resume of a multi-MB transcript burns ~45%
  of a 5h window vs 8% baseline)
- **Files:** `pxpipe-multiturn-harness.sh:56` (only local `--resume`
  invoker); staged diff at
  `/tmp/claude-0/-root-projects-burnctl/a7b9447d-dc6c-4ddc-90ef-1a2cfb044509/scratchpad/staged-fix-session-resume.diff`
  (scratchpad is session-scoped — re-stage from the audit record if expired)
- **Context:** 2026-07-18 usage audit correlated the FR3 `session-resume`
  anomaly (45% vs 8% baseline) to open upstream issue
  anthropics/claude-code#71659: `--resume` re-sends the entire prior
  transcript once the ~5-min prompt cache is cold. Multi-MB transcripts
  (narthex 6.7 MB ≈ 1.7M est. tokens) were resumed the same day. Full
  record: `audit-reports/2026-07-18-usage-audit-session-resume.md`.
- **Fix:** (1) human reviews/applies staged `resume_gate` diff; (2) run
  VERIFY — re-run a session-resume task, compare against the mid-session
  8% baseline; (3) file the prepared corroboration comment on #71659
  (draft in the audit record). Behavioral: `/compact` before ending
  sessions that will be resumed; avoid resuming multi-MB stale sessions.
- **Acceptance:** gate applied (or consciously rejected), VERIFY run
  against mid-session baseline, corroboration comment filed; audit
  closable as `resolved` or `waiting-on-upstream`.
- **Added:** usage-audit session 2026-07-18.

### TD-47 — FR3 anomaly timestamps are timezone-naive
- **Status:** open
- **Priority:** P3 (data-integrity; skews boundary-type classification)
- **Files:** FR3 anomaly-detector emit path (module TBD — wherever the
  burn-rate deviation event is recorded)
- **Context:** The 2026-07-18 audit received anomaly timestamp
  `2026-07-18T14:00:00Z` while the system clock read 13:33Z — the "Z"
  suffix was attached to a local (IST) wall-clock reading. Boundary-type
  classification (mid-session vs reset/deadline-boundary) depends on
  accurate UTC timestamps; a 5.5h skew could misclassify near-boundary
  anomalies.
- **Fix:** emit anomaly timestamps from a UTC clock
  (`datetime.now(timezone.utc)`), never `datetime.now()` + "Z" suffix;
  add a test asserting the emitted timestamp is within tolerance of UTC
  now.
- **Acceptance:** anomaly timestamps match UTC wall-clock at emit time.
- **Update (2026-07-18 debt-audit):** swept live source three ways for a
  Z-suffix-on-localtime emitter (grep `FR3`; py `isoformat`/`strftime`/`"Z"`
  patterns; sh `date` formats) — none exists in tracked code. Only correct
  UTC use found (`mcp_server.py:148` uses `time.gmtime`). The emit path is
  therefore in gitignored audit tooling or a cron outside this repo —
  needs operator knowledge to pin down. Adjacent naive-timestamp emit in
  `burn_rate.py:90` (`sampled_at`) fixed as TD-50.
- **Added:** usage-audit session 2026-07-18.

### TD-48 — pxpipe harness cost cross-check silently void on subscription plans
- **Status:** open
- **Priority:** P3 (observability — the harness's own I1-style
  cross-check discipline is defeated)
- **Files:** `pxpipe-multiturn-harness.sh:66-75, 99-113`
- **Context:** The 2026-07-17 run logged `cost_usd: 0` for all 10 turns
  (both arms) — Claude Code reports zero `total_cost_usd` on
  subscription plans — so the "baseline vs pxpipe total cost" comparison
  the harness exists for summed 0 vs 0 and proved nothing, without
  warning. Found while checking harness runs during the 2026-07-18
  usage audit.
- **Fix:** capture `usage.input_tokens` / `cache_read_input_tokens` /
  `output_tokens` per turn into the JSONL and compare token totals per
  arm; warn loudly (or abort) when every `cost_usd` is 0.
- **Acceptance:** a subscription-mode run either compares token totals
  or explicitly reports "cost comparison unavailable" instead of $0 vs $0.
- **Added:** usage-audit session 2026-07-18.

### TD-49 — /audit command Tier-2 definition drifts from PRD §4
- **Status:** open
- **Priority:** P4 (docs/process consistency)
- **Files:** `.claude/commands/audit` command prompt (Tier table),
  `.claude/commands/burnctl-usage-audit-prd.md` §4
- **Context:** PRD §4 defines Tier 2 as "repro steps + maintainer
  reply"; the /audit command's inline table relaxes it to "GitHub w/
  repro". The 2026-07-18 audit hit this exactly (#71659 has repro but
  no maintainer reply) and had to score under a stated deviation.
- **Fix:** pick one definition and align both files; if keeping the
  strict PRD version, add an explicit sub-tier (e.g. 0.6 for
  repro-without-maintainer-reply) so scoring isn't ad hoc.
- **Acceptance:** command table and PRD §4 agree; no deviation note
  needed for the repro-without-reply case.
- **Added:** usage-audit session 2026-07-18.

### TD-50 — burn_rate sampled_at was timezone-naive local time
- **Status:** resolved
- **Priority:** P3 (same failure class as TD-47)
- **Files:** `burn_rate.py:90` (import at line 19)
- **Context:** `get_burn_rate()` stamped `sampled_at` with naive local
  `datetime.now().isoformat()` — a local wall-clock reading in an ISO
  field, inviting the exact local-read-as-UTC skew recorded in TD-47.
  Grep confirmed zero external consumers parse `sampled_at`, so the
  format change (`+00:00` offset) is safe.
- **Fix:** `datetime.now(timezone.utc)`. Committed on branch
  `debt-loop-2026-07-18` as `7a5b671` [auto-loop, reviewed]; 142/142
  pytest + G5 banned-string gate pass after change.
- **Added + resolved:** debt-audit loop 2026-07-18.

### TD-51 — deprecated claude_ai_usage table awaiting v5.x drop migration
- **Status:** open
- **Priority:** P3 (fold into a v5.0 schema migration batch)
- **Files:** `db.py:103-107`
- **Context:** Schema DDL carries `-- DEPRECATED: claude_ai_usage is
  superseded by claude_ai_snapshots` and an inline TODO to remove it in
  v5.x with a migration step that drops the table. Not previously in
  this ledger. v5.0 S1 decision (forward-only migrations) applies.
- **Fix:** forward-only migration that drops `claude_ai_usage` after
  verifying `claude_ai_snapshots` fully covers reads; remove the DDL
  block and inline TODO. Medium effort — schema change, so run under
  the state-gate discipline (dry-run → backup → assert), not an
  unattended loop.
- **Added:** debt-audit loop 2026-07-18.

### TD-52 — verification layer live but untracked; INVARIANTS.md blocks on privacy rule
- **Status:** held-for-review (structural blocklist: billing-adjacent content)
- **Priority:** P2 (npm tarball/source skew is real: `package.json`
  `files` includes `tools/hooks/`, so a publish would ship
  `check_invariants.py` at whatever untracked state it happens to be in)
- **Files:** `INVARIANTS.md`, `tools/hooks/check_invariants.py`,
  `.claude/agents/verifier.md` (all untracked);
  `install-verification-layer.sh:64` (the never-executed "add these to
  git" step)
- **Context:** The 2026-07-17 verification layer is installed and live
  (Stop hook + verifier agent) but its files were never committed.
  The loop did NOT auto-commit them: INVARIANTS.md quotes real
  maintainer spend figures ($30,645 / $8,913 / $21,733), and
  `daily_qa.py:87-89` documents the standing rule that maintainer
  dollar amounts never enter source control. Held-for-review reason,
  verbatim from the loop: "committing INVARIANTS.md as-is puts
  maintainer billing figures into a repo with a public GitHub remote;
  redact-vs-keep-untracked is the operator's call, not the loop's."
- **Fix (operator decision):** either (a) redact the dollar figures in
  INVARIANTS.md (rule ids + mechanics stay) and commit all three files,
  or (b) keep INVARIANTS.md untracked and commit only
  `tools/hooks/check_invariants.py` + verifier agent, or (c) exclude
  `tools/hooks/check_invariants.py` from the npm `files` glob if it is
  operator-only. Any option closes the tarball/source skew.
- **Added:** debt-audit loop 2026-07-18.

### TD-53 — root-level session artifacts from 2026-07-16/17 debugging burst
- **Status:** open (gitignore guard committed; cleanup is operator's)
- **Priority:** P4 (hygiene; no runtime impact)
- **Files:** `tools_hooks_check_invariants.py` (byte-identical duplicate
  of `tools/hooks/check_invariants.py` — verified with `diff`),
  `claude_agents_verifier.md`, `claude_settings.json`,
  `install-verification-layer.sh` (one-shot installer, already applied),
  `self-audit.sh`, `fix-burnctl-phantom-savings.sh`,
  `verify-agent-best-practices.sh`, `burnctl.zip`, `files.zip`
- **Context:** Leftover installer sources and one-shot scripts from the
  token-cost-inflation incident. All untracked, so deletion is
  irreversible — the unattended loop does not delete them. The pxpipe
  harness cluster (`harness.sh`, `burnctl-vs-pxpipe-harness.sh`,
  `pxpipe-multiturn-harness.sh`, `analyze-results.py`) is NOT in this
  list — it is live evidence for TD-46/TD-48.
- **Fix:** operator moves the installer sources + one-shot scripts to
  `ARCHIVE/` (or deletes) once satisfied the verification layer works.
  Guard committed meanwhile: `.gitignore` `/*.zip` (`743b2d1`) so the
  blobs can't be committed accidentally.
- **Added:** debt-audit loop 2026-07-18.

---

## Debt-audit pass 2026-07-18 — ruled-out log (do not re-investigate)

Checked and cleared, with the verification step used:
- `cli.py:1432` `/root/backups/claudash` — documented rebrand-continuity
  default, env-overridable (`BURNCTL_BACKUP_DIR`/`CLAUDASH_BACKUP_DIR`);
  backup-path area additionally frozen pending SEC-001 Stage 5.
- `daily_qa.py:91` `/root/projects/burnctl` — leak-DETECTION pattern,
  intrinsic per its own comment; not a hardcoded-path bug.
- "Claudash" hits in `config.py:134`, `server.py:50`, `why_limit.py:63`,
  `daily_qa.py` — rebrand mapping tables, leak detectors, and historical
  project-name data; none user-visible output.
- Dependency staleness — zero-pip-dep by design (`requirements.txt`);
  `tiktoken` optional with fallback. No `pip list --outdated` noise run.
- Version drift — `_version.py` reads `package.json` at import; single
  source of truth, no drift possible.
- Test suite — real runner is pytest (142 tests, all green at baseline
  and after each fix); `npm start` is just the CLI shim, not a test.
- `ARCHIVE/` — deliberate, has README; tracked on purpose.
- `tools/legacy/chat_title_sync.py` TODO block — legacy module, removed
  from npm in v4.5.8, replacement direction already decided; deferred.
- `mcp_server.py:148` Z-suffix timestamp — uses `time.gmtime`, correct.
- `gh issue list --state open` — returned no open issues.
- Root `*.bak-*` clutter — already gitignored by pattern; local hygiene,
  not repo debt.

TD-54  baseline_scanner.py timestamp field is naive local time (same failure class as TD-47/TD-50)   data-integrity   baseline_scanner.py:480   open   P3
  - Discovered during TD-47 grep sweep 2026-07-18. `timestamp` field in
    baseline snapshot output uses datetime.datetime.now() instead of a
    UTC-aware call. Distinct subsystem from burn_rate.py (baseline
    scanning, not burn-rate/anomaly emission) — separate ticket, not a
    TD-47 duplicate.

TD-55  detect_loops() counted rows, not distinct sessions -- false HIGH alerts on any multi-turn session   bug/correctness   burn_rate.py   resolved   P2
  - Found live 2026-07-19: a 9-turn Narthex session and a 21-turn "Other"
    session both triggered false HIGH retry-loop alerts. Root cause: the
    query selected (project, timestamp, cost_usd) without session_id, so
    turns within one session were indistinguishable from separate
    sessions. Fixed by grouping on session_id, using MIN(timestamp) as
    session start. Verified: same data that produced the false alarm now
    correctly shows zero loops. 142/142 tests still pass.

TD-56  FR8 Codex adapter (codex_scanner.py) -- first real session ingested and honestly priced, not yet operationalized   feature   codex_scanner.py   open   P3
  - Real Codex rollout JSONL (~/.codex/sessions/.../rollout-*.jsonl)
    parsed and inserted into the same `sessions` table Claude Code uses,
    via the existing insert_session() pipeline -- no parallel schema.
    gpt-5.6-sol priced at $5/$30/M in+out (verified against multiple
    independent sources 2026-07-19), added to MODEL_PRICING in config.py.
    Adapter deliberately SKIPS (does not insert with cost_usd=0) any
    session whose model has no real MODEL_PRICING entry -- avoids
    repeating the TD-48 phantom-cost pattern.
  - Still open: (a) not wired into any scheduled scan -- currently a
    manual `python3 codex_scanner.py` run; (b) account="codex" is
    unified into the same burn-rate/loop queries as Claude data by
    default -- confirm this is the desired behavior, or add an account
    filter if Claude and Codex usage should be viewed separately; (c)
    codex_scanner.py currently lives at repo root, not under the
    adapters/ structure the PRD's FR8 design specifies -- fine for a
    single proof-of-concept file, worth restructuring before a second
    adapter (e.g. Cursor, Gemini CLI) gets added.

TD-57  gpt-5.6-sol long-context pricing tier not implemented in compute_codex_cost()   bug/cost-accuracy   codex_scanner.py   open   P3
  - OpenAI charges 2x input / 1.5x output for the ENTIRE request when
    input exceeds 272K tokens, not just the overage. compute_codex_cost()
    always uses the standard rate -- will UNDERCOUNT cost on any large
    Codex session. Not yet hit in practice (only session ingested so far
    was ~12.8K input tokens), but will silently misprice the first large
    session once one occurs.
