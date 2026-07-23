# burnctl — The Build Story

*How this was built, day by day, from the first commit to now.*

This is a record, not a pitch. It follows the repo's own history — 335 commits
across 38 working days, 2026-04-11 → 2026-07-23 — and for each thing built it
says **what**, **why**, **how**, and **what value it brought**.

**Evidence rules (so this stays truthful):**
- `what` and `how` are observed from the commit/diff — allowed.
- `why` and `value` are quoted only from recorded sources: commit-message bodies,
  `CHANGELOG.md`, `FOUNDING_DOC.md`, `docs/`, `TECH_DEBT.md`. Every entry cites a
  short SHA (and a doc/line where the *why* came from a doc).
- Where no one wrote down the reason, the entry says **`rationale not recorded`**
  rather than inventing one. A short honest record beats a long invented one.
- Reverted, abandoned, and course-corrected work stays in the story, marked as
  such — a build that only lists wins is a brochure, not a record.
- No competitor names, no positioning. The founding doc contains such comparisons;
  only the neutral problem statement is drawn from it.

---

## Before the first commit — the idea

The project began as a personal answer to one question: *if I code with Claude
every day, where are my tokens actually going?* A subscription tells you roughly
what you may use inside a rolling 5-hour window, but not how much of that window
you have burned, which of your projects is eating the model budget, whether
prompt caching is saving real money, what your subscription would have cost at
pay-per-token rates, or whether your context is compacting or quietly rotting.
The goal was to answer those with numbers, and to unify the two places Claude
gets used — the CLI and the browser — against the same window.
*Evidence: `FOUNDING_DOC.md` lines 3–30, 78–92.*

It was first called **Claudash**, and renamed to **burnctl** on 2026-04-19
(§ Phase 1). The name change is part of the story and appears where it happened.

---

## Phase 1 — The intense build (2026-04-11 → 2026-04-24)

Fourteen working days, ~190 commits, v1.0 → v4.5. The dashboard, the intelligence
layer, the measurement engine, and the rename all land here.

### 2026-04-11 — Inception
- **what:** Initial commit; `.gitignore` for pycache/db/csv. **why:** `rationale
  not recorded` (bootstrap). **evidence:** `19cc220`, `1d73a8f`.

### 2026-04-13 — Claudash v1.0 and the multi-account dashboard
- **Claudash v1.0 — usage intelligence.** *what:* per-project token attribution,
  waste detection, sub-agent cost tracking, model right-sizing, auto-detect of
  `~/.claude/projects/`, auto-opening dashboard. *why/value:* deliver the
  token-visibility gap. *evidence:* `0ee5a74`; `FOUNDING_DOC.md:3–30`.
- **npx entry + Efficiency Score + setup wizard.** *why:* Efficiency Score becomes
  the headline metric; npx for zero-install onboarding. *evidence:* `8dc029d`.
- **"Fix all 30 pre-launch gaps."** *what:* SQL hardening, 1 MB JSONL guard, query
  timeouts, incremental waste detection, cross-platform path detection, cache-hit
  formula fix. *why:* pre-launch hardening. *evidence:* `da00fea`.
- **MCP server (5 read tools), verified in Claude Code.** *why:* let Claude query
  its own usage. *evidence:* `23c4491`.
- **Reliability: auto-restart, `/health`, PM2, connection banner.** *evidence:*
  `4a294cf`. *(PM2 is removed five days later — see 04-18 M06.)*
- **Account-tab correctness fixes** (window-limit falsy-`0` bug, CORS, stale-tab
  data). *evidence:* `cd5eb4b`, `bb948bd`, `90ccc78`, `690dc01`, `5828be0`.

### 2026-04-14 — Hardening + a security pass
- **Security pass; silent auto-update removed.** *what:* constant-time key
  compare, origin check, and removal of the on-every-invocation `git pull`. *why:*
  the launcher auto-ran `git pull` against main; now gated behind `--update`.
  *evidence:* `ba3ed9e`; `CHANGELOG.md:1292`. **↩ reversed:** silent auto-update.
- **Close the remaining pre-launch audit findings** (port-regex, 10k-row flush,
  executor timeout, cross-thread lock). *evidence:* `e1cef76`; `CHANGELOG.md:1280–1290`.
- **Auto-detect plan from `~/.claude/.credentials.json`** to skip the wizard.
  *evidence:* `0c240a9`; `CHANGELOG.md:1302`.
- **Sync daemon + hooks + npm package rename.** *why:* `rationale not recorded`
  beyond the feature list. *evidence:* `b9de8fa`. Also version-from-package.json
  (`657be49`) and v1.0.10–1.0.15 bumps.

### 2026-04-16 — v2.0.0: agentic + intelligence features (F1–F7)
- **F1 lifecycle events**, **F2 context-rot viz**, **F3 bad-compact detector.**
  *why (F3):* detects post-compact quality degradation and ships *silent at 0
  rows* rather than fabricate. *evidence:* `9b38864`, `f46d52c`.
- **F4 fix_generator + `fix generate`** (LLM-backed CLAUDE.md fixes), then
  **F5 bidirectional MCP**, **F6 streaming cost meter (SSE)**, **F7 per-project
  compaction-threshold recs.** *why:* mostly `rationale not recorded` (one-line
  feature commits). *evidence:* `1ca822b`, `33a7645`, `8aa1936`, `53568a9`.
- **Detect→fix→measure loop (P1+P2).** *why:* close the loop; 6 h dedup guards a
  288-rows/day bug (BUG-004). *evidence:* `961e3d5`.
- **Restrict fix generation to Anthropic models.** *why:* the generator translates
  Claude telemetry into Claude rules, so Claude is the right model. *evidence:*
  `17a3aee`. **↩ course-correct:** narrows the generic provider path from `62ff20e`
  added hours earlier.
- **`find_claude_md` fuzzy matching.** *why:* DB project names rarely match on-disk
  dirs; the prior 4-step lookup returned None. *evidence:* `b94981a`.

### 2026-04-17 — v2.0.3–2.0.7: detector correctness
- **Floundering detector rewritten** to 4+ repeats in a 50-call window. *why:* the
  consecutive-match rule found 0 events in 30 days — real sessions interleave
  tools between retries. *value:* 0 → 8 events / $2,323.73 surfaced. *evidence:*
  `52952af`.
- **Rolling 5 h window metrics** replace a broken epoch-modulo. *why:* restores the
  window-risk insight. *evidence:* `08560c5`, `c866bd7`.
- **WAL + 30 s busy_timeout.** *why:* 5 s was insufficient under scanner+poll+API+
  hook contention (transient "database is locked" in logs; 0 after). *evidence:*
  `c9364e1`.
- Also: daily-budget hero card (`03792cc`); orphan-MCP cleanup on startup, shipped
  with an honestly-flagged overstated safety docstring (`249f087`).

### 2026-04-18 — v3.0.0 → v3.3.1: compliance + sub-agent intelligence (five releases)
- **v3.0.0 Architecture Compliance Intelligence** — `compliance_events` (127 rows
  backfilled) + 4 DB-grounded rules. *why:* the pre-flight audit dropped 3 of 4
  proposed rules that would fire on 0 rows; a same-day sibling states the principle
  bluntly — *"a rule that fires on zero rows ships as a lie."* *evidence:* `ad8f748`
  (+ `CHANGELOG.md:1901`); the aphorism is verbatim in `997e5ad`.
- **Sub-agent tool classification (v3.1)** + PID lock via `fcntl.flock`. *why:* the
  lock closes a cron-watchdog duplicate-process race. *evidence:* `46357aa`, `e2a1e61`.
- **`turns_per_tool` guard (v3.2)** — *"the fix for the biggest hallucination risk
  in v3.1."* *value:* Tidify mechanical cost corrected $547.81 → $19.09.
  *evidence:* `bcce189`.
- **Prompt-quality scorer + rule 21**, softened to present correlation, not
  prescribe error. *evidence:* `651df36`. **Rule 22 jit_skill_waste**, threshold
  tuned 40 %→20 % because 40 % fired zero times on real data. *evidence:* `2bbd5b8`.
- **v3.3.0 backup/restore CLI**, and **M06 deletes PM2 support** — *"PID lock is
  canonical, no PM2 needed."* *evidence:* `d4d8f6e`, `71949a0`. **↩ reversed:** the
  04-13 PM2 support.
- **Verdict override** (cost+turns drop beats a ratio trap). *why:* the ratio metric
  misreported real improvements when total tokens shrank faster than waste tokens.
  *evidence:* `6562ee7`. Also a Homebrew formula added here (`1af63c4`) — later
  deleted (see 05-01).

### 2026-04-19 — v4.0.0: the rename Claudash → burnctl
- **burnctl v4.0.0.** *what:* rename claudash→burnctl; `analyzer.py` nine waste
  bins derived from research over 9,667 sessions; a causal `measure.py` with a
  10-session minimum; `CLAUDASH_VPS_IP` back-compat aliases kept. *why:* the rename
  *motivation itself is `rationale not recorded`* — the body states the rename as
  fact. *evidence:* `b1d2b3f`. **✎ rename.**
- **v4.0.1 subcommand routing + tighter npm `files`.** *why:* excludes
  credential-extraction and personal-VPS sync tools *"that were shipping by
  accident under the old tools/ glob."* *evidence:* `951fd58`. **↩ removed:**
  accidental credential-tool shipping.
- **v4.0.2 `resolve_db_path()`** with a friendly no-DB message. *why:* fixes npx
  invocation from any cwd. *evidence:* `f17c18b`.
- **v4.0.4 peak-hour / version-check / resume-audit / variance profiler.** *why:*
  version_check flags Claude Code 2.1.69–2.1.89 (GH #34629/#38335/#42749).
  *evidence:* `c476dfe`; hotfix `56baebc` adds them to the shim set v4.0.4 forgot.

### 2026-04-20 — v4.0.6 → v4.1.0: path discipline, audits, the QA suite
- **v4.0.6 clean error paths; removed hardcoded maintainer DB path** from the
  variance profiler. *why:* that path worked only on the maintainer's VPS.
  *evidence:* `12daf27`.
- **v4.0.7 subagent/overhead/compact/fix-scoreboard audits**, built against the
  real DB schema (overhead via `MAX(cache_creation_tokens)`, not a 2–6-token
  first-turn input). *evidence:* `cd51216`.
- **v4.0.8 `fix apply <id>` + `measure --auto`.** *why:* closes manual copy-paste
  in the loop — but **Module-6 hooks were deliberately NOT shipped** because the
  doc's "PostSession" is not a real Claude Code event and would silently never
  fire. *evidence:* `28ef913`. **⊘ abandoned:** the hooks module.
- **v4.0.10 QA-cycle 9 bugs** — incl. a maintainer-path leak (BUG-1) in
  work_timeline. *why:* findings from the tester agent. *evidence:* `acfd62c`.
- **v4.0.11 `daily_qa.py` + `burnctl qa`; v4.0.12 `qa --trend`.** *what:* a
  WOW/OK/DOD regression suite run from a fresh `/tmp`. *why:* guard known
  regression classes (path leak, noise, branding, 404). *evidence:* `89b7abe`,
  `b347d1c`. *(This QA gate becomes load-bearing for every later publish.)*
- **v4.1.0 claudemd-audit + mcp-audit + 5 dashboard fixes** (cost-share vs
  token-share; subagent-inflated waste). *evidence:* `1802c5f`. Also stale-Claudash
  docs removed, back-compat contracts preserved (`2805a86`).

### 2026-04-21 — v4.2.0 → v4.3.0: why-limit, fix-rules, browser sessions
- **`why-limit`** — a 5-hour breakdown that masks private project names by default.
  *evidence:* `a6c787e`.
- **`fix-rules`** — deterministic CLAUDE.md rules from real waste data; only
  DB-present patterns render, headline suppressed under 7 days of data. *why:*
  truth-first — *"never show an unbackable number,"* unseen patterns *"never
  fabricated."* *evidence:* `d453fb1`.
- **v4.3.0 browser session intelligence** — plateau-based session detection from
  browser snapshots; all costs labeled "est." because the source API rounds to
  10k tokens / 1 %. *evidence:* `4c0314a` (+`ecce7ac` ships the module in the
  tarball).

### 2026-04-22 — Browser chat-title tracking (server side) + a history rewrite
- **`browser_chat_sessions` table + ingest/recent endpoints.** *why:* until then
  there was no way to answer *"which claude.ai chat was the 92-minute session?"* —
  the detector saw the shape, not the identity. *evidence:* `3f5a95a`;
  `CHANGELOG.md:2419–2448`.
- **Security notice: git history rewritten 2026-04-22.** *why:* follows the
  operator-file leak untracking of 04-21 (`681216a`); the commit is a docs marker,
  *`rationale not recorded`* in the body. *evidence:* `ee683ee`.

### 2026-04-23 — v4.4.0-rc: the measurement-engine bug hunt
- **Fix-apply unification + measurement stability.** *why:* the headline ROI on
  fix #14 drifted $1,616 → $0 over 6 h from live re-capture against a frozen
  baseline. *evidence:* `e503c59`, `10d755e`.
- **UX-3: pattern-scoped observation replaces per-fix ROI claims.** *why:* a
  project-scoped baseline made five fixes render byte-identical deltas with false
  causation — *"honest display now reveals that several historical fixes did not
  achieve their stated goal. This is signal, not noise."* *evidence:* `bf0c955`
  (+`e1d145c` strips a "verified $1,708/mo" README claim). **↩ course-correct:**
  causal ROI claims → observational framing.
- **BH-class scanner/apply fixes** (string/negative-token coercion, phantom-DB
  guard via URI-mode open, re-apply rejection), each citing
  `audit-reports/2026-04-22-*.md`. *evidence:* `7c5b8b7`, `8889125`, `f043f4b`.

### 2026-04-24 — v4.5.0 Intelligence Layer
- **Baseline scanner + daily brief.** *what:* `baseline_scanner.py` tokenises
  context-overhead sources (tiktoken w/ char fallback); `cmd_daily` + `/api/daily`
  + a dashboard brief card; business logic centralised in `daily_report.py` as the
  single source of truth. *evidence:* `1f54358`, `8ad098c`.
- **v4.5.1 flag Claude Code 2.1.118/2.1.119** (issues #52578/#52345/#52307).
  *evidence:* `4acf995`. **v4.5.2 plan-aware "API EQUIV TODAY"** label — for
  flat-fee plans *"that amount is NOT real spend."* *evidence:* `3bd2fc4`.
- **v4.5.3 P2 gap closure** — ranking-key aliases (rules emitted savings/cost keys
  the ranker didn't read, so recs showed $0), 90-day baseline retention, TECH_DEBT
  consolidated to a single TD-N scheme. *evidence:* `d954617`.

---

## Phase 2 — Hardening, truth, and the v5 seam (2026-04-29 → 2026-05-26)

The pace drops; the work turns to making it correct for someone who isn't the
author — cold-start installs, encryption, and honest empty states.

### 2026-04-29 — Cold-start npx failures
- **v4.5.4 shim passthrough.** *why:* the hardcoded subcommand allow-list was last
  updated at v4.3 and *silently dropped v4.5.0's `daily` command* from npx builds.
  *evidence:* `07f7268`.
- **v4.5.5 `get_conn()` returns None when no DB.** *why:* an unconditional
  `sqlite3.connect()` auto-created an empty schemaless file at the npx dir, making
  seven later commands traceback on missing tables. *evidence:* `8ef7f21`. *(This
  is the seam that BLOCKER-1 rides on 90 days later — see Phase 4, 07-23.)*

### 2026-04-30 — Browser-panel truthfulness (TD-16/27/29)
- **Render metered overage** from already-polled data (`541c3c0`); **show browser
  activity without title-sync** — the widget previously showed "0 sessions" and
  told users to run a non-shipped script (`fd7ec08`, which files TD-31); **clarify
  Pro-panel copy** that *"read as 'tracking is broken'"* over working data
  (`4475f44`). **Close TD-18:** burnctl vs claude.ai/settings reconciled — Pro
  8 %/8.0 %, Max 11 %/10.0 %, *"no bugs found, definitions differ."* *evidence:*
  `543b6ec`.

### 2026-05-01 — Hygiene batch
- **Excise references to a non-existent `chat_title_sync.py` (TD-31).** *why:* a
  CLI hint told users to run a script that does not exist. *evidence:* `8815ce9`.
  *(Rebuilt three days later — see 05-04.)*
- **Delete the orphaned Homebrew formula (CA-09).** *why:* 17 versions stale,
  pointing at a tap repo *"never created… dead code that looked live."* *evidence:*
  `b749070`. **⊘ abandoned:** the Homebrew install path.
- **Union `.burnctlignore` with default leak patterns (BH-23).** *why:* the loader
  returned file *or* defaults, never both, so creating the file silently lost
  path-leak detection. *evidence:* `5ed4ef0`.

### 2026-05-02 — Correctness + security
- **Full-path read-collision key (CORR-09)** — basename collisions had counted
  unrelated files together (`20e0559`). **Bind origin allow-list to the actual
  bound port (SEC-012)** — a hardcoded 8080 caused 403s on every write for any
  non-default port (`cb94a96`). **Scan-state orphan pruning** — 31 % of live rows
  were orphans (`79e38f4`).

### 2026-05-04 — SEC-001 encryption staging begins
- **Stage 2: master-key env injection** at `/etc/burnctl.env` (root:root 0600).
  *why:* prepares the key for stages 3–4, with an explicit sequencing rule — *the
  backup-path bug stays unfixed until encryption lands, because fixing it first
  would repeat the April-incident class.* *evidence:* `45e41d0`. *(This rule is
  still load-bearing in Phase 4 — see 07-23 publish-readiness.)*
- **Stage 3a: `crypto.py`** (AES-256-CBC + HMAC, stdlib/openssl); `get_setting`
  decrypts `v1:` values, legacy plaintext passes through. *evidence:* `f712774`.
- **DASH-028: rebuild the `chat_title_sync` collector.** *why:* `rationale not
  recorded` (one-line). *evidence:* `8775e8f`. **↩ course-correct:** reverses the
  05-01 excision.

### 2026-05-05 — Recent Browser Sessions + rename follow-through
- **DASH-030: drop Duration/Flag columns.** *why:* Chrome records one visit-event
  per SPA URL load, so `duration_min` is *structurally always 0*. *evidence:*
  `8b8b825`. **↩ removed.**
- **CORR-01b: extend the Claudash→burnctl rename to downstream tables** — 63 stale
  rows in lifecycle_events/waste_events, 4 stale insights, a defensive remap. *why:*
  CORR-01 (04-23) missed three downstream tables, so `/api/insights` still emitted
  "Claudash." *evidence:* `01637f0`. **✎ rename follow-through.**

### 2026-05-07 — Auth + message correctness
- **SEC-001: enforce `X-Sync-Token` on `/api/browser-chats`.** *why:* the endpoint
  had been auth-free since DASH-028 — *"anyone with localhost access could spoof
  arbitrary rows."* *evidence:* `926434f`. Plus cost-outliers showing session date
  not detection date (`198a043`), and a repeated-reads message that said "in 7d"
  on the 30d branch (`ec8819f`).

### 2026-05-08 — Tarball hygiene + baseline allow-list
- **TD-36: explicit `tools/` allow-list** replacing the glob. *why:* the glob had
  been *shipping `tools/get-derived-keys.py`, a macOS keychain helper, to all npm
  installs since v4.5.4.* *evidence:* `f9bf36b`. **⊘ abandoned:** a `.npmignore`
  denylist approach, reverted inside the same commit for an allow-list.
- **INV2: baseline project allow-list** via `tracked_projects`. *why:* closes an
  unfiltered `os.listdir` leak that surfaced stale dirs (Tidify14, Tidify12-backup)
  in CLAUDE.md insights. *evidence:* `76b9994`.

### 2026-05-09 — Fix scoreboard ordering
- **Order by `applied_at`, not `created_at`.** *why:* the scoreboard should reflect
  when fixes took effect, not insert order. *evidence:* `8e106bf`.

### 2026-05-10 — Phantom-savings guard
- **Zero savings when `sessions_count == 0`.** *why:* a worsened verdict paired with
  $316.79 of phantom savings on fix #12, because attribution math depended on
  session presence while waste_events do not. *evidence:* `8de43b8`; root cause
  filed BURNCTL-DATA-1 (`e1a8dd9`).

### 2026-05-25 — v4.5.8: local-first naming
- **Rename `VPS_*` → `BURNCTL_*`** across config/cli/tools, legacy names honored.
  *why:* `rationale not recorded` beyond the mechanical rename. *evidence:*
  `e09eeb6`. **✎ rename.** Plus a remote-host warning (`3859043`, safety intent
  implied but not stated) and the accounts-panel half of TD-29 (`8ed9540`).

### 2026-05-26 — v5.0 Session 1: the extension seam
- **Extension ingest schema (forward-only migration).** *what:* `init_db()` adds
  `extension_connections` (token-hash only), `browser_samples`, `browser_chat_daily`,
  `account_emails`, `account_ignore_list`, and 4 account columns. *why:* forward-only,
  no down-migration framework, per session decision; verified idempotent + prod
  apply over 44,813 sessions with a pre-apply backup. *evidence:* `c53cdf4`.
- **Connect/revoke endpoints with Bearer auth + `util/redact.py`.** *what:* store
  only `sha256(token)`, return the raw token once; redact tokens/PII from logs; 11
  redact tests. *evidence:* `01b4650`.
- **Move `chat_title_sync.py` to `legacy/`, drop from npm.** *evidence:* `6f59bec`.
  **⊘ retired:** the browser chat-title collector (rebuilt 05-04) is pulled from
  the shipped package here.

---

## Phase 3 — The verification harness (2026-06-20 → 2026-06-27)

The project turns its instruments on itself: gates, committed criteria, and a
loop that grades whether a claimed "done" is real.

### 2026-06-20
- **Auto daily backup.** *what:* a scheduled backup commit. *why:* `rationale not
  recorded` (automated). *evidence:* `669d5e4`.

### 2026-06-22 — The G5 gate and the credential surface
- **G5 banned-string enforcement gate.** *what:* `check_banned_strings.py` fails if
  a claude.ai credential string (`sessionKey`/`Cookie:`/`claude.ai/api`, incl.
  snake-case) reappears in a prod path; wired into `daily_qa.py` (DOD) and a
  pre-commit hook. *why:* lift the credential rule from trust to a mechanical gate;
  a GitHub Action would never trigger on this npm/VPS repo. *evidence:* `2121f29`.
  *(This gate runs on every commit through Phase 4.)*
- **Remove the claude.ai credential-solicitation UI + dead browser panels.** *why:*
  the backend was hardened but the frontend still instructed users to paste a
  `sessionKey` cookie — the sole banned-string hit in a prod path. *evidence:*
  `990fefc`. **↩ removed.**
- **`cost_anomaly` spend detector (surface-only).** *what:* flags a session on
  robust median+8·MAD (≥$300), a week-over-week spike, or spend-without-output;
  reports insufficient-baseline instead of guessing. *why:* plain "3× median"
  flagged 27.8 % of real history (bimodal costs) vs 3.6 % here. *value:* backtest on
  363 sessions → 13 flags, 350 quiet. *evidence:* `4880d7d`. **Hard line:**
  detect-not-enforce — it never throttles spend.
- **Seed `docs/SESSION-STATE.md`** (persistent harness memory) and the **org_id
  harvested-identifier wipe** — 2 stale claude.ai org UUIDs NULL-wiped, atomic with
  read-back. *evidence:* `84799cf`, `844462f`.

### 2026-06-23 — Committed criteria replace by-construction claims
- **Lock the cost_anomaly detector contract (V1–V3)** and a **committed runaway
  fixture** — burnctl's live DB has no genuine phantom-billing incident, so the
  catch-path was only proven structurally; the fixture manufactures the signature.
  *why:* *"'done' for the detector is now a file, not a prompt-time backtest."*
  *evidence:* `012e9cd`, `3aed2d6`.
- **`daily_qa` self-brakes on a live cost_anomaly runaway** (withholds burnctl's own
  publish, never a user session). *evidence:* `c1f8ca8`.
- **Committed org_id-wipe criterion** and the **waste_events write-path contract
  (V4/V5)** — proving idempotent UPSERT / rowid read-back re-runnably, each with an
  injected-fault red. *evidence:* `ed59f33`, `6a1233f`. Plus **UNVALIDATED_AUDIT**
  classifying every "done" claim as verifiable/judgment/sensitive (`06d7e62`).

### 2026-06-25 — The six-axis frame and the loop runner
- **Pin the six-axis checker frame** — the dimensions a *stateless* checker grades
  each worker run on (criteria-pass, non-vacuity, real-code binding, scope, STATE+
  budget discipline, ledger/reproducibility). *evidence:* `6e1258e`.
- **Stateless worker→checker loop runner.** *what:* runs a goal under STATE 1→2→3
  with a post-write assert + `git reset --hard` auto-rollback; the checker grades
  all six axes from concrete signals, never the worker's say-so; an abort ceiling
  brakes only the runner, never Claude Code; no autonomous push; a human holds the
  accept-out. *evidence:* `e968ed6`.
- **Lock the V6 core-clean scan contract** on a real scanner path (`cf3dc0d`).
- **Project-aware live context gauge** for the statusline — real `used_percentage`,
  a project-history nudge from the compaction log, graceful degrade on unknown
  projects, TTL-cached so warm ticks make 0 DB connections. *evidence:* `5b7de04`.
- **Dashboard display-integrity pass** (over-limit bar state, delta anchors; no
  computed value changed) (`584c9e8`), **PROJECT_MAP attribution** re-tagging the
  Other bucket −7,534 with an honest "Digivault 0 moved, its JSONL is deleted"
  caveat (`90548b7`), and a **test-package collision fix** that made the suite
  runnable again (`8e7b90b`).

### 2026-06-26 — Statusline verbs + a NO-BUILD decision
- **4-tier statusline action verbs** (calm / ⚠ wrap soon / 🔴 /clear / 🛑 now),
  display-only. *evidence:* `301d147`.
- **Skill-relevance engine: researched, then NOT built.** *why:* a per-project
  relevance signal isn't computable non-hallucinatorily on the available data;
  native scoping already ships. *value:* a recorded decision to *not* build, with
  the stats-only archiver shipped instead. *evidence:* `7e8f515`, `7895d69`.
  **⊘ deliberately unbuilt** (and honestly recorded).

### 2026-06-27
- **`coach` — in-workflow habit teaching.** *what:* a session-end one-liner pairing
  a recurring waste pattern with a grounded teaching, celebration-first, on
  patterns (≥3 sessions/30d) not instances; no LLM, ~3.5 ms. *evidence:* `25d185d`.

---

## Phase 4 — Launch-readiness (2026-07-13 → 2026-07-23)

The final stretch: fix the numbers, make the anomaly flag trustworthy, describe
the guardrails so a loop can run inside them, and find the blockers a stranger
would hit.

### 2026-07-13
- **Remove a cross-project read grant (HC4)** to the PHI-walled Tidify15, and
  untrack `settings.local.json`. *evidence:* `bfc6db3`, `41d9794`. **↩ removed.**

### 2026-07-17
- **Resolve `BURNCTL_DIR` relative to the script, not a hardcoded HOME** (`e65ec21`).
- **Fix `waste_events` token_cost inflation** (attributed waste, dedup ingestion,
  stale-session gate). *evidence:* `ed5746d`.

### 2026-07-18 — Review pass + timestamp discipline
- **TD-46..53 review + auto-loop findings** (`9d322c4`): **redact spend figures from
  `INVARIANTS.md`** (`a13af83`), **emit `sampled_at` as UTC-aware** to avoid the
  local-time-read-as-UTC skew of TD-47 (`586fa37`), and gitignore stray session zips
  (`8364667`).

### 2026-07-19 — npm discoverability + loop-detection correctness
- **`detect_loops()` counts distinct sessions, not turns.** *why:* multi-turn
  sessions produced false HIGH alerts. *evidence:* `285c9c4`. Plus TD-55..57 Codex
  adapter status + a logged long-context pricing gap (`b072872`), `gpt-5.6-sol`
  pricing (`def73d6`), npm keywords/description (`dac920d`), and the v4.5.9 release.

### 2026-07-20 — The proactive brief + the rule map
- **`burnctl brief` — proactive cross-day per-project usage brief.** *what:* groups
  per-project-day snapshots, builds a robust median+MAD baseline from prior days,
  flags a genuine anomaly, attributes a heuristic cause; pure and deterministic
  (`today` is passed in). *evidence:* `b2cee50`.
- **Classify every blocking rule as GATE / FRICTION / FIXED POLICY.** *what:* all 30
  rules enumerated so an autonomous loop can automate through FRICTION and hard-stop
  at every GATE; read-only, wires no remedy. *evidence:* `e5f029c`.

### 2026-07-21 — Grounding the threshold + the outer loop
- **`brief --calibrate` (read-only).** *why:* remove the blind `BRIEF_MAD_K=5.0` by
  measuring what it actually flags before launch; suggests only, mutates nothing.
  *value:* over 310 real project-days even k=8 flagged 11.3 % — the tool correctly
  refused an in-band k and said "consider k>8," exposing the untuned-threshold risk.
  *evidence:* `40088a2`.
- **`loop_driver` — autonomous outer control layer (dry-run).** *what:* a router +
  hard budget caps + stall detector over the loop runner; remedies are logged, never
  executed, this goal. *evidence:* `ab9c27f`.

### 2026-07-22 — The threshold fix + the write gate + a live remedy
- **Log-scale `robust_score` (FIX-DETECTOR).** *why:* raw (cost−median)/MAD left a
  fat tail no k could threshold; a STATE-1 diagnostic *refuted* the idle-day
  hypothesis and found right-skew (multiplicative cost) as the cause. *value:*
  `brief --calibrate` now lands k=5 at 4.2 % and k=6 at 2.6 %, both in the 2–5 %
  band; p99 116.7 → 7.19. *evidence:* `327a3f4`. **↩ course-correct:** the raw
  anomaly-threshold approach is superseded by log-scaling.
- **Mechanical STATE-3 write gate** (PreToolUse Write|Edit) — makes the /goal
  approval gate a hook, not prose, after a runner once reasoned past a human STOP.
  *evidence:* `8904a88`.
- **Arm ONE wet remedy** (`deploy.sh` for A3/A8) behind a default-deny allow-list;
  everything else stays dry-run. *evidence:* `00ce505`.

### 2026-07-23 — Reframe, audit, and the first-run fix
- **Descriptive-first brief reframe.** *what:* sort by today's burn, add "×N vs
  typical" movement, demote the (now-trustworthy) anomaly flag to an annotation.
  *why:* a flag-led brief was useful only on the rare anomalous day; a descriptive
  core answers "where did my tokens go?" every day. *evidence:* `a4ad0b7`.
- **Publish-readiness audit + fresh-env smoke test.** *what:* an evidence-based
  inventory of every place burnctl assumes this machine, classified
  BLOCKER/DEGRADED/DEV-ONLY, plus a hermetic smoke test. *why:* the gap between
  "works for me" and "works for anyone" is the last unbuilt thing before launch.
  *evidence:* `181a923`; `docs/PUBLISH-READINESS.md`.
- **Graceful no-data on a fresh install (BLOCKER-1).** *what:* `brief` on a no-DB
  machine now exits 0 with "run `burnctl scan`" instead of a traceback, while a
  corrupt DB names the path and fails loudly. *why:* the worst first moment a public
  CLI can have. *evidence:* `0b8bfa9`. *(This closes the seam opened at v4.5.5,
  04-29.)*

---

## Course-corrections, reversals, and things deliberately not built

A record of where the build changed its mind — each kept because the reversal is
itself part of how it was built.

| what | added | undone / decided | why |
|------|-------|------------------|-----|
| Silent auto-update (`git pull` on launch) | `4a294cf`-era | removed `ba3ed9e` | security; gated behind `--update` |
| PM2 process support | `4a294cf` (04-13) | removed M06 `71949a0` (04-18) | fcntl PID lock is canonical |
| Homebrew install path | `1af63c4` (04-18) | deleted CA-09 `b749070` (05-01) | tap repo never created; dead code |
| Generic OpenAI-compat fix provider | `62ff20e` (04-16) | narrowed to Anthropic `17a3aee` | Claude telemetry → Claude rules |
| Module-6 "PostSession" hooks | planned | not shipped `28ef913` (04-20) | not a real Claude Code event |
| Causal per-fix ROI claims | early v4 | → observational `bf0c955` (04-23) | project-baseline caused false causation |
| `chat_title_sync` collector | `8775e8f` (05-04) | excised `8815ce9` then retired `6f59bec` (05-26) | referenced-not-shipped, then pulled from npm |
| Duration/Flag browser columns | earlier | removed DASH-030 `8b8b825` (05-05) | SPA history has no time-on-page |
| claude.ai credential-solicitation UI | earlier | removed `990fefc` (06-22) | credential surface in a prod path |
| Skill-relevance engine | researched | NOT built `7e8f515` (06-26) | not computable non-hallucinatorily |
| Raw anomaly threshold (median+K·MAD on raw cost) | `b2cee50` (07-20) | → log-scaling `327a3f4` (07-22) | fat tail, no k in the 2–5% band |
| Claudash name | `19cc220` | → **burnctl** `b1d2b3f` (04-19) | rename motivation *not recorded* |

---

## Coverage ledger (every commit-day accounted for)

All 38 distinct commit-days appear above. Days whose commits were only chores /
version bumps / doc logs with no feature work are folded into their date's entry
rather than omitted. Commit-days with **no recorded rationale** for their notable
work (flagged `rationale not recorded` in-line): **04-11** (inception), the
one-line **F1/F4–F7** feature commits of **04-16**, the **04-19 rename motivation**,
the **04-22** history-rewrite notice, the **05-04** collector rebuild, and the
**05-25** `VPS_*→BURNCTL_*` rename and remote-host warning.

## Method & determinism

- Spine: `git log --date=short` over the full range (335 commits, 38 days).
- Primary evidence: commit-message bodies; `why`/`value` cross-checked against
  `CHANGELOG.md`, `FOUNDING_DOC.md`, `docs/`, `TECH_DEBT.md`.
- The same repo state reproduces the same story — every claim is anchored to an
  immutable SHA or a cited file/line.
- No competitor names or positioning language: the founding doc's tool comparisons
  are excluded by design; only its neutral problem statement is used.
