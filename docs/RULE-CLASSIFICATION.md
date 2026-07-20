# burnctl — Rule Classification (GATE / FRICTION / FIXED POLICY)

Foundation for the autonomous loop: the loop **automates through FRICTION** and
**hard-stops at every GATE**. The loop's own control machinery is **FIXED
POLICY** — permanent brakes, never a gate/friction candidate.

Derived read-only from repo state (see enumeration in
`docs/goals/RULE-INVENTORY.md`). This doc **describes** rules only — it wires no
remedy and changes no behaviour. **Misclassifying a GATE as FRICTION is the
worst possible error; when unsure, classify GATE.**

---

## 1. Rubric

**Category A — External guardrails** (classified GATE or FRICTION):

- **GATE** — a failure that is *any* of: irreversible · leaves the box (npm
  publish / git push / production deploy / network) · out-of-lane (scope,
  credential, off-roadmap) · needs human or agent judgement · **a truth /
  data-integrity violation** (the tool misreports savings or waste). Never
  auto-passed.
- **FRICTION** — a failure that is reversible **AND** has a deterministic,
  known-safe remedy command that restores green without changing what the rule
  protects, and whose remedy does not itself cross a GATE boundary.
- **Default-to-GATE** — anything ambiguous, any remedy not proven safe, or any
  remedy that could *mask* a real defect → GATE.

**Category B — the loop's own control machinery** → **FIXED POLICY**. These
*are* the loop's safety envelope; "auto-passing" them is a category error.

**GATE `resolves_by`** (how a hard-stop is discharged — it is never auto-passed
either way):
- **human** — HUMAN / IRREVERSIBLE: push, publish, production deploy, DB
  migration, credential (A6), and the explicit human gates (A17, A18, A19), plus
  data-integrity truth violations (I1/I2/I5) and schema/deploy-integrity.
- **loop-iteration** — AGENT-JUDGEMENT: an in-lane verdict the loop feeds back
  and iterates on (A13 auditor GO, A14 tester PASS, A15 reviewer APPROVE, A4/I4).
  Escalate to human **only at `abort_ceiling`** (loop_runner `abort_ceiling=3`).

**Deploy distinction (so FRICTION never contradicts "deploy = GATE"):** the
GATE'd "deploy" is the **outward/production** deploy + `npm publish` + `git
push`. The **local pm2 restart** (`bash deploy.sh`) is idempotent,
`/api/health`-verified, and reversible — it is the known-safe FRICTION remedy
for A3/A8, **not** a production deploy.

**Escalation, never retry:** a FRICTION remedy that itself trips a GATE
**escalates** to that GATE — it does not retry the remedy. A3's `deploy.sh` may
trip A9 (version-mismatch); if so it escalates → A9 (human), never loops on
`deploy.sh`.

---

## 2. Category A — External guardrails

| id | rule | source | checks | on-fail blocks | class | resolves_by | remedy | rationale |
|----|------|--------|--------|----------------|-------|-------------|--------|-----------|
| A1 | I1 savings ≤ spend | check_invariants.py | fix-rules savings ÷ 30d spend ≤ 1.0 | Stop hook (block) | GATE | human | — | Data-integrity/truth — misreported savings; never auto-remediate a truth violation |
| A2 | I2 waste ≤ cost | check_invariants.py | Σ waste_events.token_cost ≤ session cost ×1.01 | Stop hook (block) | GATE | human | — | Data-integrity/truth — misreported waste |
| A3 | I3 live-process fresh | check_invariants.py | pm2 start-time ≥ newest .py mtime | Stop hook (block) | FRICTION | — | `bash deploy.sh` (pm2 restart; **may escalate → A9** if version-mismatch — escalates, never retries) | Idempotent local restart, /api/health-verified; validated 2026-07-20 |
| A4 | I4 windowed queries | INVARIANTS.md + verifier | every waste-emitting SQL is time-bounded | verifier VERDICT | GATE | loop-iteration | — | Structural judgement (baseline vs emit); a wrong auto-fix changes detector semantics |
| A5 | I5 dedup sanity | check_invariants.py | 30d dup_rate < 0.02 | Stop hook (block) | GATE | human | — | Data-integrity/truth — duplicate ingestion inflates ground-truth numbers |
| A6 | G5 banned-string | hooks/pre-commit + tools/check_banned_strings.py | no sessionKey / Cookie: / claude.ai/api in prod paths | commit | GATE | human | — | Credential/security boundary; auto-stripping prod code to dodge it is exactly wrong |
| A7 | daily_qa pre-publish gate (= never-publish-on-DOD) | daily_qa.py + CLAUDE.md/AGENTS.md | exit 2 (DOD) or regression vs qa-reports/latest.md | npm publish | GATE | human | — | Guards publish (leaves the box, irreversible once users pull) |
| A8 | Deploy Rule | CLAUDE.md/AGENTS.md | run deploy.sh after any *.py change / publish | stale live daemon | FRICTION | — | `bash deploy.sh` (same remedy as A3; **may escalate → A9**) | Human-process statement of what A3/I3 enforces mechanically; same safe remedy |
| A9 | deploy.sh version-mismatch | deploy.sh | /api/health version == package.json | exit 1 | GATE | human | — | Mismatch *after* a restart = import error / broken deploy needing diagnosis (pm2 logs), not a blind retry |
| A10 | schema-name rule | CLAUDE.md/AGENTS.md | canonical cost_usd / timestamp / pattern_type / id | reviewer / schema-guard | GATE | human | — | Data-integrity-adjacent; column drift = misread numbers, risk to existing DB |
| A11 | no-hardcoded-paths | CLAUDE.md/AGENTS.md | no literal DB/FS paths in prod code | reviewer | FRICTION | — | Replace literal with `db.DB_PATH` / `overhead_audit.py::load_db()` resolver — **CONSTRAINED to resolve to the identical DB path; post-write assert MUST prove resolved path == prior path, else reclassify GATE. No blind path edits.** | Reversible via one known resolver pattern, but only under the identical-path proof obligation |
| A12 | no-"Claudash" leak | CLAUDE.md/AGENTS.md | no "Claudash" in user-visible output | reviewer / pre-publish | FRICTION | — | Replace "Claudash" → "burnctl" in **user-visible OUTPUT strings ONLY; MUST NOT touch claudash.db / claudash.log references, filenames, paths, or code identifiers** | Deterministic, reversible pre-publish, scoped to output text |
| A13 | burnctl-auditor GO | CLAUDE.md/AGENTS.md | pre-code health = GO | build start | GATE | loop-iteration | — | Agent judgement; NO-GO halts before building; feed back + iterate, escalate at abort_ceiling |
| A14 | burnctl-tester PASS | CLAUDE.md/AGENTS.md | all commands PASS | npm publish | GATE | loop-iteration | — | Functional-correctness verdict; fixer loop iterates one bug at a time |
| A15 | burnctl-reviewer APPROVE | CLAUDE.md/AGENTS.md | shipped diff APPROVE | npm publish | GATE | loop-iteration | — | Agent judgement; BLOCK opens a fix loop |
| A16 | burnctl-schema-guard | CLAUDE.md/AGENTS.md | no column drift after db.py/scanner.py edit | npm publish | GATE | human | — | Data-integrity-adjacent; drift could reflect an intended schema change (human decision) |
| A17 | no auto-commit without human review | CLAUDE.md/AGENTS.md | human reviewed the diff | commit / publish | GATE | human | — | Explicit human gate |
| A18 | no off-roadmap features | CLAUDE.md/AGENTS.md | feature in research-reports/ or roadmap | build | GATE | human | — | Scope + human judgement |
| A19 | human-diff-review (step 11) | CLAUDE.md/AGENTS.md | human reads diff pre-publish | npm publish | GATE | human | — | Explicit human gate |
| A20 | /goal session Stop hook | runtime (`/goal`) | goal condition holds | task stop | GATE | human | — | Human-defined session halt; judgement |

---

## 3. Category B — Loop control machinery (FIXED POLICY — permanent brakes)

Not GATE/FRICTION candidates. Classifying any of these as auto-passable is a
category error.

| id | brake | source | enforces | class |
|----|-------|--------|----------|-------|
| B1 | loop axis 1 — criteria-pass | loop_runner.py | re-run criteria module at expected count | FIXED POLICY |
| B2 | loop axis 2 — non-vacuity | loop_runner.py | criteria are not trivially satisfiable | FIXED POLICY |
| B3 | loop axis 3 — real-binding | loop_runner.py | criteria import + call the bound symbols | FIXED POLICY |
| B4 | loop axis 4 — scope-compliance | loop_runner.py | changed files ⊆ scope_paths + G5/X-surface banned-scan | FIXED POLICY |
| B5 | loop axis 5 — state+budget | loop_runner.py | STATE1→2→3 seq · commits==2 · no-push · iters ≤ ceiling | FIXED POLICY |
| B6 | loop axis 6 — ledger+repro | loop_runner.py | ledger recorded + result reproduces | FIXED POLICY |
| B7 | abort_ceiling brake | loop_runner.py | halt the runner after 3 red iterations, no ship | FIXED POLICY |
| B8 | no-autonomous-push (DETECT-NOT-ENFORCE) | loop_runner.py | brake stops only the runner, never a CC session; never self-pushes | FIXED POLICY |
| B9 | accept-out human gate | loop_runner.py | checker output feeds a human accept gate; no self-ship | FIXED POLICY |
| B10 | post-write assert → auto-rollback | loop_runner.py | a red post-write assert rolls the commit back | FIXED POLICY |

---

## 4. Completeness ledger

- **INVARIANTS.md** defines exactly **I1, I2, I3, I4, I5** — no gap, no I6+.
- **`.github/workflows/`** — does not exist (`.github/` holds only
  `ISSUE_TEMPLATE/`). **No CI gates.**
- **SECURITY.md** — posture table + disclosure policy; **no build/publish gate.**
- **self-audit.sh** — advisory report generator (`set -uo pipefail`, no `-e`);
  greps dollar/token claims for *manual* reconciliation; **never exit-fails.**
- **close-out-session.sh** — runs `check_invariants.py --report` (report mode,
  always exit 0); re-surfaces I1–I5, **adds no new rule.**
- **harness.sh** — pxpipe-vs-baseline benchmark runner; **not a gate.**
- **prevent_repeated_reads.py** — PostToolUse hook, **non-blocking** (always
  exit 0); excluded from the classified set.
- **DB migration** — **no migration gate enumerated in the burnctl repo** (the
  DELETE/DROP/ALTER block lives in a different project's CLAUDE.md). The
  GATE-policy "migration = GATE" therefore holds vacuously here.

**Canonical classified set: 20 (Category A) + 10 (Category B) = 30 rules.**
