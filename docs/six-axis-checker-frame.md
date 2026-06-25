# Six-Axis Checker Frame

The dimensions a **stateless checker** grades each **worker run** on, in fresh
context, to decide whether a claimed "done" is real. This doc is the **runner's
input** — it does not build the checker, worker, or loop runner.

## Premises (NOT axes — the frame's structure)
- **Maker ≠ checker.** The checker runs in a separate, fresh context. It cannot
  trust the worker's say-so, summary, or memory. *This is why the frame exists;
  it is not one of the six axes.* (7-dim loop-audit dimension "critic".)
- **Stateless = fresh context.** Context-hygiene is answered by re-grading from
  scratch, not by a per-run axis. (7-dim dimension "context-hygiene".)
- **Nothing advances on a green banner** — only on a signal read from ground
  truth (`burnctl-headroom-harness.md:3,9,11`).
- **Module-path test invocation only**, never `unittest discover` (B1 `util/` vs
  `tests/util/` collision makes discover unreliable).

## Relationship to the 7-dim loop audit (no parallel taxonomy)
The 7-dim audit grades **repo maturity** (does the repo *have* a capability).
This frame grades **one worker run** (is *this* run's done real). Map:

| 7-dim loop audit (repo) | This frame (run) |
|---|---|
| success-criteria + completion-check | Axis 1 criteria-pass |
| termination + brakes | Axis 5 STATE+budget discipline |
| run-ledger | Axis 6 ledger/reproducibility |
| tools+harness | split across Axis 3 (real-binding) + Axis 4 (scope) |
| critic | *premise* (stateless checker), not an axis |
| context-hygiene | *premise* (statelessness), not an axis |
| — (new at run level) | Axis 2 non-vacuity, Axis 3 real-binding |

---

## The Six Axes

Each axis: what it grades · the concrete SIGNAL (file:line / command + expected
output) · pass/fail predicate · the FAILURE mode (defined red — an axis that
can't fail is as vacuous as a test that can't) · grader.

### Axis 1 — CRITERIA-PASS (re-run, never trust the report)
- **Grades:** the run's claimed criteria actually pass when the checker re-runs
  them in fresh context.
- **Signal:** `PYTHONPATH=~/projects/burnctl python3 -m unittest <criteria module>`
  → trailing `OK` **and** `Ran N tests` where N == the count the ledger claims
  (e.g. V6 `tests.test_core_clean_scan_contract` → `Ran 5 … OK`; V4/V5 → 8; V1–V3 → 8).
- **Pass:** exit 0 **and** test count == documented count.
- **Red:** any failure/error; import error / missing module; **or count < documented**
  (a silently dropped test reads as "fewer assertions," not "still green").
- **Grader:** STATELESS-CHECKER.

### Axis 2 — NON-VACUITY (the criterion can actually fail)
- **Grades:** each criterion has a recorded fault that drove it RED with an exact
  revert to green — proof it is not a test that cannot fail.
- **Signal:** (a) ledger row carries a fault receipt — e.g. SESSION-STATE CORE-CLEAN:
  "live in-tree fault `return # FAULT` → RED (`0 != 3`) → `git restore` → green";
  (b) the criteria file contains an in-file `test_nonvacuity*` / negative case;
  (c) the checker re-applies the named fault in a scratch copy and observes RED,
  then `git restore` → `git status --short <file>` empty → re-run green.
- **Pass:** fault receipt present **and** the re-applied fault reproduces RED
  **and** the revert is exact (clean `git status`) **and** post-revert green.
- **Red:** no fault evidence; the re-applied fault still passes green (vacuous);
  the revert is not exact (working tree dirty after restore).
- **Grader:** STATELESS-CHECKER (re-runs the fault in scratch / in-tree-then-revert).

### Axis 3 — REAL-CODE BINDING (no reimplementation)
- **Grades:** the criterion exercises the REAL production path, not a reimpl that
  would pass even if prod is broken.
- **Signal:** `grep -nE 'import (db|scanner|waste_patterns)' <file>` **and** a call
  to the graded prod symbol (`db.insert_waste_event` / `db.insert_session` /
  `scanner.scan_jsonl_file` / `wp._detect_cost_anomalies`); confirm the graded
  function is **not re-defined** inside the test (no shadow copy of the logic).
  Schema must come from real `db.init_db()`, not a hand-written `CREATE TABLE`.
- **Pass:** prod symbol imported **and** called **and** not shadowed; schema from `init_db`.
- **Red:** the test defines its own copy of the graded function; asserts against
  hand-rolled SQL/algorithm instead of the prod call; imports nothing from the
  prod module; or hand-copies the DDL (would survive a prod schema break).
- **Grader:** STATELESS-CHECKER.

### Axis 4 — SCOPE-COMPLIANCE (in-bounds writes; X-bucket untouched)
- **Grades:** the run changed only what its goal declared, touched no out-of-bounds
  file, and did not edit the human-gated X-bucket (credential/publish/org_id).
- **Signal:** `git show --stat <commit>` / `git diff --name-only <range>` vs the
  goal's declared scope; `python3 tools/check_banned_strings.py` → `PASS … exit=0`;
  confirm no prod-path edits (`db.py`/`scanner.py`) in a "test-only" goal.
- **Pass:** every changed path ∈ declared scope **and** G5 `exit=0` **and** zero
  X1–X6 surface edits.
- **Red:** a commit touches an out-of-scope file (prod code in a test-only goal);
  a banned string appears (G5 DOD/exit 2); the worker edits any X-surface.
- **Grader:** STATELESS-CHECKER for file-scope + G5 (mechanical). **HUMAN-GATED**
  for any judgment that an X-surface change is acceptable — a worker or checker
  must **never grade its own publish/credential gate** (`UNVALIDATED_AUDIT.md` X3).

### Axis 5 — STATE + BUDGET DISCIPLINE
- **Grades:** the run followed STATE 1→2→3, stayed under the abort ceiling, kept
  one fix per commit, and did not autonomously push.
- **Signal:** ledger/loop-log shows STATE 1 (read-only) → STATE 2 (dry-run/diff)
  → STATE 3 (write + read-back by rowid); `git log --stat` shows one logical
  concern per commit; loop iterations ≤ **3** (`burnctl-headroom-harness.md:11`);
  `git log origin/<branch>..HEAD` + no worker-initiated `git push`.
- **Pass:** STATE sequence present; commits atomic; iterations ≤ 3; no autonomous push.
- **Red:** a write with no prior read-only/dry-run; a bundled commit (>1 concern);
  an autonomous `git push`; >3 iterations without escalation.
- **Grader:** STATELESS-CHECKER for the mechanical checks (commit stats, push
  absence, STATE markers). **HUMAN-GATED** for the push/auth decision itself (X6).

### Axis 6 — LEDGER / REPRODUCIBILITY (human is the final gate)
- **Grades:** the run is reproducible from the record; the checker can emit a
  checklist a human re-runs; the worker did not self-certify "done."
- **Signal:** a SESSION-STATE verdict row exists with a verbatim **`Reproduce:`**
  command that, run as-is, reproduces the green; every claim cites a commit SHA +
  `file:line` / command-output, not prose.
- **Pass:** verdict row + verbatim reproduce command present **and** it reproduces
  **and** evidence is SHA/file:line/output (no memory/say-so).
- **Red:** no reproduce command; the command does not reproduce; evidence is
  say-so; or the run is marked "done" without the checker + human gate.
- **Grader:** STATELESS-CHECKER emits the reproducible checklist; **HUMAN-GATED**
  is the final "this ships" decision.

---

## Dry-validation against the V6 run (`cf3dc0d` / `62c79c4`)
Would these 6 have graded V6 green, and does each have a real red?

| Axis | V6 verdict | Signal read | A red would be |
|---|---|---|---|
| 1 criteria-pass | **GREEN** | `unittest tests.test_core_clean_scan_contract` → `Ran 5 … OK` | a failing test / count < 5 |
| 2 non-vacuity | **GREEN** | CORE-CLEAN row "`return # FAULT` → RED (`0 != 3`) → restore → green" + `test_nonvacuity_readback_detects_absence_before_scan` | no fault receipt / fault stays green |
| 3 real-binding | **GREEN** | `import scanner` + `scanner.scan_jsonl_file(...)`; schema via `db.init_db()` | a reimplemented scan/insert |
| 4 scope | **GREEN** | `git show --stat cf3dc0d` = only `tests/test_core_clean_scan_contract.py` (+137); G5 exit 0 | cf3dc0d also editing `scanner.py` |
| 5 STATE+budget | **GREEN** | STATE 1 plan → STATE 2 green → STATE 3 fault; commit 1 test-only, commit 2 docs-only; no push | bundled commit / autonomous push / >3 iters |
| 6 ledger/repro | **GREEN** | CORE-CLEAN `Reproduce: … python3 -m unittest tests.test_core_clean_scan_contract -v` reproduces 5/5 | no reproduce command |

All six grade `cf3dc0d` green and each has a concrete, reachable red — no axis is
unfailable. The frame is complete for the run-grading surface; the loop runner
(next goal) consumes it.
