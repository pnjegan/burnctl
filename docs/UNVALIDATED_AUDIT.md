# burnctl — UNVALIDATED "done" audit (read-only)

> **Date:** 2026-06-23 · **Branch:** `v5.0-session-1` · **Mode:** read-only audit.
> Purpose: surface every claim of "done" that has **no independent mechanical
> check** (no committed test, no assert, no second human), so a future
> worker→verifier loop stands on checkable ground truth — not on "CC reported it
> + I read the report."
>
> Sources read: `docs/SESSION-STATE.md` (Verdicts + Loop log), `git log`
> (`v5.0-session-1`), `tests/`, `waste_patterns.py`, `daily_qa.py`.
>
> **Classification**
> - **VERIFIABLE** — a mechanical check could prove it → becomes a committed criterion.
> - **JUDGMENT** — no test can capture it honestly; needs a human. Marked, not automated.
> - **SENSITIVE** — security / credential / publish / harness surface. **EXCLUDED**
>   from any future autonomous loop, **human-gated permanently** (a worker must
>   never grade its own credential/publish surface).

---

## Already verified (committed test exists — NOT unvalidated, listed for completeness)

| Claim | Evidence | Lock |
|-------|----------|------|
| `cost_anomaly` catches the #68285/#57719 runaway (r1+r3 red, only-runaway flags) | `3aed2d6` | `tests/test_cost_anomaly.py` |
| `daily_qa` self-brake fires on a live runaway, silent on stale history | `c1f8ca8` | `tests/test_daily_qa_brake.py` |
| `BURNCTL_*` host config / non-localhost warn | `e09eeb6`,`3859043` | `tests/test_host_config.py` |
| redact util | — | `tests/util/test_redact.py` |

---

## VERIFIABLE — claimed done, NOT yet locked by a committed test

| ID | Claim ("done") | Where | Status |
|----|----------------|-------|--------|
| **V1** | `cost_anomaly` is **surface-only — no enforcement path** ("verified *by construction*"; "never pauses, kills, or throttles") | `waste_patterns.py:16-18,380`; SESSION-STATE *CIC* | **→ BUILD (criterion C)** — prose claim, no test |
| **V2** | `insufficient_baseline` is **reported, NOT flagged**, when trailing-7d history `< COST_ANOMALY_MIN_BASELINE` (5) | `waste_patterns.py:421-429`; SESSION-STATE *CIC* | **→ BUILD (criterion A)** — uncovered by existing test |
| **V3** | **r3** spend-without-output guard fires on `cost≥$20 AND output<3000` **below the r1 floor**, and the output floor is a real boundary | `waste_patterns.py:464-466`; SESSION-STATE *CIC* | **→ BUILD (criterion B)** — existing test only sees r3 bundled with r1 on the $420 runaway |
| V4 | "**idempotent UPSERT** (2nd run still 13, no dupes)" on `waste_events` | SESSION-STATE *CIC*; `detect_all` persist path | **VERIFIABLE-NEXT** — needs the DB write/persist path + `waste_events` fixture; not built this pass (not fabricated) |
| V5 | "**rowid read-back**" + "**ADD-only** (other patterns untouched)" after persist | SESSION-STATE *CIC* | **VERIFIABLE-NEXT** — persist/DB-op surface; defer with V4 |
| V6 | G1 "**local-JSONL core clean**" scan | SESSION-STATE *G1* | **VERIFIABLE-NEXT** — re-run scan + assert clean; low priority, harness-scan surface |

*This pass builds V1–V3 (the pure, read-only detector contract). V4–V6 are
honestly left unbuilt — they touch the DB write path / harness scan and would be
the next criterion group, not a fabricated test pretending to cover them.*

## JUDGMENT — no honest mechanical check; needs a human

| ID | Claim | Where | Why human |
|----|-------|-------|-----------|
| J1 | G-AUDIT skills / md / maturity inventory | `AUDIT.md` | Qualitative inventory + opinion |
| J2 | Commit 1 — harness spec versioned | `5c1d609` | Doc existence/quality, not a behavior |
| J3 | G2-STEP0 — headroom 502 fix (**config-only**, `~/.bashrc` + tmux daemon) | SESSION-STATE *G2-STEP0* | External environment, not a repo artifact; "zero-502 across a full heavy session" + "compression>0" are explicitly PENDING/observational |
| J4 | Dogfood skill-tax (~4.2k tok/turn, 71% irrelevant); BUILD-TO-DELETE / prune story | SESSION-STATE *Harness notes / SHOWCASE* | Measurement + narrative, no pass/fail line |

## SENSITIVE — EXCLUDED from any future loop, human-gated permanently

| ID | Claim | Where | Surface |
|----|-------|-------|---------|
| X1 | Removed claude.ai credential-solicitation UI + dead browser panels | `990fefc` (G1.5) | Credential UI |
| X2 | `/setup` + `/refresh` deleted; nothing persists | SESSION-STATE *G1.7* | Credential setup path |
| X3 | **G5 banned-string publish gate** (`tools/check_banned_strings.py`, wired into `daily_qa` DOD→exit 2 + `hooks/pre-commit`) | `2121f29` (G5) | **This IS the publish/credential gate** — never let a worker author or alter its own grade here |
| X4 | `org_id` harvested-identifier NULL-wipe (live DB data-op) | SESSION-STATE *G1.6/G1.6b* | Harvested-credential surface |
| X5 | v5.0 connect/revoke endpoints, Bearer auth + redact | `01b4650`,`c53cdf4` | Auth/credential surface |
| X6 | PUSH STATUS — commits local-only; `unitedappsmaker-tech` vs `pnjegan` auth decision | SESSION-STATE *#1 OPEN* | Publish/identity surface |

---

## Bottom line

The **only** "done" claims that are both mechanically checkable **and** safe to
hand a future verifier are the `cost_anomaly` **detector-contract** properties
(V1–V3). Everything credential/publish/harness (X1–X6) stays human-gated; the
measurement/narrative claims (J1–J4) cannot be reduced to a pass/fail line
without fabricating one. V4–V6 are real future criteria, explicitly not yet
built. This pass locks V1–V3.
