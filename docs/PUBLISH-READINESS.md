# burnctl — Publish-Readiness Audit

**Status: audit-only.** This document is an evidence-based inventory of every
place burnctl assumes *this* machine, plus a fresh-environment smoke test
(`tests/test_publish_smoke.py`). It **fixes nothing** and **publishes nothing**.
Each fix is sized as a follow-on goal from the BLOCKER list below.

Produced for `docs/goals/PUBLISH-READY.md`. Evidence is `file:line` from static
read + one hermetic smoke run; no production code was changed to create it.

---

## 0. Headline — what a stranger meets on first run

A fresh `npm i -g burnctl` ships **no DB** (`data/` is excluded from the tarball),
no history, no pm2. In that state, run in genuine isolation (temp `HOME`, temp
`cwd`, only the shipped files):

| command | fresh-install behaviour | verdict |
|---------|------------------------|---------|
| `burnctl brief` | **tracebacks** `AttributeError: 'NoneType' object has no attribute 'execute'` | **BLOCKER-1** |
| `burnctl brief --calibrate` | graceful: `No burnctl DB found. Run \`burnctl scan\` first.` (exit 0) | OK ✓ |
| `burnctl statusline` | graceful `No burnctl database found. Run: burnctl scan first` (exit 0) | OK ✓ |
| `burnctl scan` | exits 0, ingests 0 rows, but prints maintainer project-name warnings | DEGRADED |

`brief` is the one user-facing command that crashes instead of guiding the user
to `scan`. `calibrate` and `statusline` already handle the no-DB case gracefully —
`brief` simply lacks the same guard (see BLOCKER-1). **This is an honest red:**
`tests/test_publish_smoke.py::test_fresh_brief_is_graceful` pins the *desired*
graceful behaviour as an `expectedFailure` (xfail) and
`test_fresh_brief_current_behaviour_is_blocker_1` captures the *current*
traceback as a hard-passing regression. When BLOCKER-1 is fixed the xfail flips
to an unexpected success and the capture test fails — both say "update me".

### Smoke-test isolation (STATE-3 #5)

The smoke test is hermetic and proven so **structurally**: the isolated
subprocess's `db.DB_PATH` always resolves *inside* the temp install and
`db.resolved_db_path()` returns `None` — it can never open the real DB. A naive
"real DB byte-identical before/after" checksum would **race the maintainer's live
pm2 daemon**, whose scanner rewrites `data/usage.db` on its own timer (observed:
`e312fdc…` → `8c6b005…` between two reads, with no test in between). So the byte
check is daemon-aware: it asserts equality, and if the real DB moved it verifies a
live `pm2 burnctl` exists (proving the change was the daemon, not the test) before
skipping. Real DB is never referenced by path from inside the sandbox.

---

## 1. Classification rubric

- **BLOCKER** — a fresh install is broken, misleading, or unsafe.
- **DEGRADED** — it works, but worse or confusing for a new user.
- **DEV-ONLY** — never on the user-facing path (`bin/burnctl.js` → `cli.py`);
  document and leave alone.

Every coupling enumerated in STATE 1 appears below exactly once.

---

## 2. BLOCKERs

| id | finding | evidence | why it blocks |
|----|---------|----------|---------------|
| **B1** | `brief` tracebacks on a no-DB machine | `cli.py:2213` `get_conn()` → `None` (`db.py:58-68`); `cli.py:2215` passes it to `compute_daily_snapshots`; crash at `analyzer.py:36` | The primary command crashes on first run instead of a "run `scan` first" hint. Root enabler = the `get_conn()`→None seam (TD-13) with `brief` as the one unguarded caller. **Fix ≈ 5 lines**, mirror `calibrate`'s guard. |
| **B2** | DB path is package-local, unwritable on a global install | `db.py:11` `DB_PATH = <pkg>/data/usage.db`; `init_db()` `db.py:84` creates it there; `bin/burnctl.js` runs python from the package dir; the `~/.burnctl` clone path is only reached when `cli.py` is *absent* (never for npm). | `npm i -g` installs to a **root-owned** prefix on the common Linux default; a non-root user's first `scan`/`init` hits `PermissionError` creating `data/`. Conditional on prefix ownership, but the default case breaks. |
| **B3** | Default backup dir is a maintainer absolute path | `cli.py:1436` `_default_backup_dir()` returns `/root/backups/claudash`; `cmd_backup` `cli.py:1509,1516` `os.makedirs` it then `sys.exit(1)` on failure | `burnctl backup` (a documented command) fails for any non-root user, leaks the maintainer path, and surfaces the old "claudash" brand in the error string. **⚠ Remediation is SEQUENCED behind SEC-001** — see §6. |
| **B4** | Shipped `PROJECT_MAP` is pre-populated with the maintainer's projects | `config.py:69-78` maps `WealthOS/Narthex/Digivault/SocialLearn` to personal keywords, though the comment at `config.py:56` claims "Empty on a fresh install" | A stranger's projects match none of these → everything buckets to `"Other"` (`config.py:80`), silently breaking per-project attribution (a core feature), and the tarball ships the maintainer's private project names. |

---

## 3. DEGRADED

| id | finding | evidence |
|----|---------|----------|
| **D1** | `BRIEF_MAD_K = 5.0` tuned on the maintainer's 310-day history | `brief.py:23`; calibration note `brief.py:66-68` — a stranger's anomaly rate will differ (see §5, per-user calibration) |
| **D2** | `BRIEF_MIN_COST_FLOOR = 1.0` absolute-dollar floor | `brief.py:25` — a <$1/day user never gets a brief; a heavy user gets noise |
| **D3** | Model pricing is version-blind; non-Claude mispriced | `config.py:96-100` MODEL_PRICING (opus/sonnet/haiku, version-agnostic); `scanner.py:75-83` `normalize_model` collapses to 3 families, default **sonnet** (`scanner.py:98`); `config.py:152-157` `gpt-5.6-sol` entry is dead for the cost path → real GPT/Codex sessions priced as Claude Sonnet; prices silently stale across model generations |
| **D4** | Two inconsistent DB resolvers | `db.py:45-55` `resolved_db_path()` (script-dir order) vs `burn_rate.py:28-46` `resolve_db_path()` (**cwd-relative first**). The cwd-relative fallback makes `statusline` attach to *any* stray `data/usage.db` near the cwd → a stale non-zero line in a non-fresh-but-DB-adjacent dir |
| **D5** | No `BURNCTL_DB` env override for the DB path | grep of shipped `.py` — only `BURNCTL_MASTER_KEY` (`db.py:1759`), `BURNCTL_BACKUP_DIR` (`cli.py:1433`), host/port (`config.py`). No escape hatch when the package dir is unwritable (compounds B2) |
| **D6** | `get_conn()` → `None` seam, per-caller handling incomplete | `db.py:58-68` (TD-13). `calibrate`/`statusline` guard it; `brief` does not (= B1). Listed as the shared root cause |
| **D7** | Maintainer project names shipped in source (masked, not shown) | `why_limit.py:62-64` `_DEFAULT_PRIVATE_NAMES`; `config.py:121-150` `COMPACT_INSTRUCTIONS` keys; `fix_generator.py:221-269` aliases + personal dir-layout guesses; `insights.py:680` calibration comment. Privacy footprint + dead weight for a stranger |
| **D8** | Single-account assumption `personal_max` | `config.py:37-49` ACCOUNTS (one account, $100/mo drives ROI math); `scanner.py:1376` hardcodes `'personal_max'` for `fix_regressing` rows → orphaned rows if renamed |
| **D9** | `statusline` blocks on `sys.stdin.read()` for a non-tty with no EOF | `cli.py:2385-2391` — a manual invocation with an open non-tty stdin hangs (surfaced in the smoke harness; benign from a terminal or the Claude Code hook, which closes stdin) |
| **D10** | `_validate_data_paths` allows `/root` (VPS assumption) | `db.py:849-864` `allowed_roots = [home, "/root"]` — permissive, not broken; a stranger's `$HOME` is already allowed |

---

## 4. DEV-ONLY (document & leave)

| id | finding | evidence |
|----|---------|----------|
| **V1** | Invariants I1/I2/I3/I5 are dev-only | `INVARIANTS.md`; wired only via `.claude/settings.json` Stop hook (`.claude/` **not shipped**); `tools/hooks/check_invariants.py:36,41-137` ships (blanket `tools/hooks/` in `files`) but is **inert/unwired** — no `cli.py` command runs it; I3 fails-open when pm2 is absent |
| **V2** | `deploy.sh`, `ecosystem.config.js`, pm2 | not in `files`; `deploy.sh` also in `.npmignore`; pm2 is **not** a package.json dependency. Maintainer daemon infra only (`deploy.sh:19,31` `/root/...`, `/etc/burnctl.env`) |
| **V3** | `/api/health` | `server.py:403,1034` — a route inside the dashboard server; reachable only while `burnctl dashboard` runs. `deploy.sh`'s always-on assumption is the VPS, not the user path |
| **V4** | Legacy `CLAUDASH_*` env | `config.py:14-20` (`CLAUDASH_VPS_IP/_PORT` → sane `localhost:8080` defaults), `cli.py:1433` `CLAUDASH_BACKUP_DIR`. Harmless upgrader compat; comment says "remove next major" |
| **V5** | `_PROJECT_DISPLAY_REMAP {Claudash→burnctl}` | `server.py:50-51` — *protective*, actively prevents the old brand reaching user-visible output |
| **V6** | `daily_qa.py` leak patterns / self-audit | `daily_qa.py:90-137` — a dev/QA command; the maintainer paths there are redaction *patterns*, never emitted |
| **V7** | `tools/hooks/` scripts ship but are opt-in/unwired | `post-session.sh` (assumes localhost:8080 dashboard), `state_gate.py`, `prevent_repeated_reads.py` — tarball weight, not breakage; none auto-installed |
| **V8** | "Claudash" residue in internal identifiers/comments | `cli.py:1429-1454` legacy backup filename regex; `config.py:134` COMPACT key; `why_limit.py:63` mask entry; `server.py:782` comment. Internal/masked — **not** user-visible output |

---

## 5. Packaging truth (STATE-3 #4)

`package.json` `files` is an **allow-list**, so the tarball = exactly those paths
(plus auto-included `package.json`/`README`/`LICENSE`). Derived from `files` +
`.npmignore`, not assumed.

**Ships:** 37 `.py` modules + `util/{__init__,redact}.py`, `bin/burnctl.js`,
`templates/*.html`, the whole `tools/hooks/` dir, `CONTRIBUTING.md`, `LICENSE`,
`README.md`.

**Does NOT ship** (verified absent from the allow-list; also `.npmignore`):
`data/` and all `*.db`/`*.db-wal`/`*.db-shm`, `*.log`, `deploy.sh`,
`ecosystem.config.js`, `.claude/`, `ARCHIVE/`, `audit-reports/`, `qa-reports/`,
`research-reports/`, `CLAUDE.md`, `MEMORY.md`, `*.bak*`, `claudash.db`,
`claudash.log`.

**Imports clean:** every shipped module's top-level imports resolve to stdlib or
another shipped module. The only third-party names are **guarded/optional** —
`boto3` (`try:` at `fix_generator.py:569`, opt-in Bedrock) and `tiktoken`
(`try:` at `baseline_scanner.py:37-38`, char-approx fallback).

**Nothing credential-bearing ships.** No secrets, API keys, session tokens, or
real DB. Grep of shipped files for keys/cookies/emails → none. Note the DB stores
secrets **plaintext at rest** (`db.py:1768` `set_setting` does not encrypt;
SEC-001 encrypt-on-write not yet shipped) — but the DB is **not** in the tarball,
so no plaintext secret ships.

**Honest caveat — personal data does ship (names only):** maintainer *project
names* are baked into shipped source (`config.py` PROJECT_MAP + COMPACT_INSTRUCTIONS,
`why_limit.py:62-64`, `fix_generator.py:221-269`, `insights.py:680`). These are
taxonomy/masking data, not credentials, but they are a real personal-data
footprint (B4 + D7). The public author name "Jegan Nagarajan" and GitHub handle
`pnjegan` in `package.json` are expected/public.

---

## 6. Per-user calibration (proposal only — do NOT implement here)

`BRIEF_MAD_K = 5.0` was calibrated on the maintainer's 310-day history. A stranger
must calibrate `k` off **their** history, never inherit this machine's tuning.

Proposed shape (sized as a follow-on goal, not built here):
- Ship a sane default `k` (5.0 today; calibrate suggests 6.0 on this machine —
  the choice is per-user, not global).
- Make `burnctl brief --calibrate` a documented onboarding step: first-run flow
  `scan → calibrate → (optionally) set k`. `--calibrate` already *suggests only*
  and mutates nothing, so it is safe as onboarding.
- Never bake a k derived from one machine's distribution into a stranger's config.

---

## 7. Follow-on goal sizing (from the BLOCKER/DEGRADED list)

| goal (proposed) | covers | size | notes |
|-----------------|--------|------|-------|
| FIX-FRESH-BRIEF | B1 | **S** | None-guard in `cmd_brief` mirroring `calibrate`; flips the smoke xfail green |
| FIX-DB-LOCATION | B2, D4, D5 | **M** | Default DB to a user-writable `~/.burnctl/data/usage.db`; add `BURNCTL_DB` override; **unify** the two resolvers. Subject to the A11 identical-DB-path proof obligation |
| FIX-BACKUP-PATH | B3 | **S** | Default backup dir to `~/.burnctl/backups` / XDG. **⚠ GATED: do NOT ship until SEC-001 closes** — a working backup of a plaintext-secret DB replicates secrets, the same leak-vector principle as the Drive-backup sequencing rule. Verify `git log \| grep "SEC-001.*Stage 5"` before touching |
| FIX-PROJECT-MAP | B4 | **S** | Ship `PROJECT_MAP` empty (match the comment); derive projects from scan; move personal taxonomy out of shipped source |
| GENERICIZE-PRICING | D3 | **M** | Version-aware pricing; correct handling of non-Claude models instead of sonnet fallback |
| STRIP-PERSONAL-NAMES | D7, D8 | **S–M** | Remove maintainer project names from shipped source; generalize the account model |
| PER-USER-CALIBRATION-ONBOARDING | D1, D2 | **M** | The §6 onboarding flow |

Out of scope for every one of these until its own goal: this document only
inventories. **No BLOCKER is fixed here.**

---

## 8. Completeness & determinism

- Every STATE-1 coupling category (invariants · process-manager/deploy · paths &
  env · data assumptions · tuned-to-Jegan constants · packaging · naming leakage)
  appears above, classified, with `file:line` evidence — no blanks.
- The inventory is derived from static repo state + one hermetic smoke run, so the
  same repo state reproduces the same inventory (determinism). The smoke test has
  no wall-clock/network/ambient-DB in its pass/fail path.
