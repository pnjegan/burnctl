# burnctl — SESSION-STATE (persistent harness memory)

> **Top rule:** CC updates this file in the REFLECT step of every loop;
> `/goals` reads it to know what already passed. This is the L2 record of
> what is verified, so a fresh session does not re-litigate settled goals.

This file is the **canonical, tracked** harness state. See *versioning
policy* below: `.claude/commands/goals.md` is a deployed copy, not the source
of truth.

> **#1 OPEN — PUSH STATUS:** all `v5.0-session-1` commits are **LOCAL only**
> (nothing pushed). Blocked on the `unitedappsmaker-tech` vs `pnjegan` auth
> mismatch **plus** a deliberate decision on what reaches public history.
> "Done" in this file means **done locally** — not published.

---

## Verdicts (with evidence pointers)

| ID       | Verdict                     | Evidence | Note |
|----------|-----------------------------|----------|------|
| G1       | core **PASS** / E-banned **FAIL** | read-only verify | local-JSONL core clean; E-banned was failing → spawned G5 |
| G1.5     | **PASS**                    | `990fefc` | claude.ai credential-solicitation UI + dead browser panels removed |
| G1.7     | **PASS-A**                  | —        | `/setup` + `/refresh` deleted; nothing persists |
| G-AUDIT  | **done**                    | `AUDIT.md` | skills / md / maturity inventory |
| Commit 1 | **done**                    | `5c1d609` | harness spec (`burnctl-headroom-harness.md`) versioned |
| G5       | **PASS**                    | `2121f29` | banned-string gate; E-banned now **L3-mechanical** |
| G1.6     | **DONE (FOUND)**            | DB data-op 2026-06-22 | STATE-1 scan found 1 harvested-identifier column with real values: `claude_ai_accounts.org_id` (2 claude.ai org UUIDs). `raw_response` identifier-free; `account_id`/`label` are local self-assigned nicknames (left as-is); `session_key` already NULL |
| G1.6b    | **DONE**                    | DB data-op 2026-06-22 | STATE-3 NULL-wipe of `org_id` on the 2 stale rows (by rowid 1 & 2, NULL not `''`), atomic txn + pre-commit asserts + fresh read-back. Post: org_id non-null=0, rows still 2, account_id/label untouched, `session_key` re-verified NULL. Re-scan: zero harvested identifiers remain in either table |
| G-VERIFY-1 | **DONE — org_id wipe now has a committed criterion** | `ed59f33` | The G1.6b wipe was worker-self-verified (one-time read-back by the wiping agent). Now **independently re-runnable**: `tests/test_org_id_harvest_guard.py` — in-memory `claude_ai_accounts` fixture (no prod DB), self-contained `find_harvested_identifiers()` scanner scoped to the harvested-suspect column (`org_id`; clean = NULL or `''`). C1 NULL-or-empty invariant · C2 no UUID/email/claude.ai value in suspect col · C3 POSITIVE re-seeded org UUID caught + C1 also reds · C4 self-assigned `account_id`/`label` never flagged (even a UUID-shaped label). Non-vacuity proven by injection (poison→C1+C2 red, blind scanner→C3 red, over-fire→C4 red); real file 4/4 green. `session_key` deliberately out of scope (own guard). **Reproduce:** `cd ~/projects/burnctl && python3 -m unittest tests.test_org_id_harvest_guard -v` |
| G2-STEP0 | **502 KILL — PASS / cold-start residual** | proxy `/stats` 2026-06-22 | headroom proxy 502 storm fixed via config only (no burnctl code). See block below for proven-vs-pending |
| CIC (cluster #1) | **DETECTOR built — PASS** | `4880d7d` | `cost_anomaly` spend detector (gap-doc cluster #1). Surface-only, no enforcement. Backtest-tuned on live usage.db. Cluster #1 GAP→detected. See block below |
| UNVAL-AUDIT | **DONE — V1–V3 locked + injection-verified** | `06d7e62`,`012e9cd` | Classified every done-but-unverified claim (read-only `docs/UNVALIDATED_AUDIT.md`). VERIFIABLE V1–V3 (cost_anomaly detector-contract: baseline-reports-not-flags, r3-floors-are-real-boundaries, surface-only/no-enforcement) locked in `tests/test_cost_anomaly_contract.py` and each criterion **proven to go red on injected breakage** (guard weakened→below-baseline candidate flags; r3 `<`→`<=`→floor-case flags; flag grows `action:throttle`→rejected) while the real detector stays green (13/13). V4–V6 honestly deferred (DB-write/persist path); J1–J4 = human-judgment; X1–X6 = SENSITIVE, permanently human-gated, EXCLUDED from any future worker→verifier loop |

### CIC — cost_anomaly spend detector (gap-doc cluster #1; NOT on original G-board)

**Framing:** DETECTOR, not enforcer. v1 flags + records evidence in `waste_events`;
it does **not** pause/kill/block/throttle any spend (enforcement is explicitly out of
scope — belongs to Tether). Verified by construction: no stop/kill/throttle path in the code.

**Rules (tuned against the real 363-session usage.db, 2026-06-22):**
- **r1** cost > median + 8·MAD of trailing-7d session costs **AND** cost ≥ $300. Robust
  median+MAD chosen because the spec's plain "3× median" flagged **27.8%** of real history
  (bimodal distribution: tiny-median + fat-tail); median+8·MAD@$300 → **3.6%** (13 sessions).
  *User chose this threshold at the STATE-2 tuning checkpoint over 3 alternatives.*
- **r2** weekly spend > 2× prior week on Anthropic's Thu-06:00-UTC reset cadence, prior week
  ≥ $860 (a quiet-week recovery is not a spike). On real data fired on 1 week (wk42,
  $1904→$4305) whose top session was already an r1 outlier → folds into that one flag.
- **r3** cost ≥ $20 **AND** output_tokens < 3000 — spend-without-output stuck-loop guard
  (GH #57719). Floors raised from the gap-doc's unusable `out<100` (0 real sessions have
  near-zero output; p10 = 3,242 tok). 0 flags on this history = correct forward guard.
- **insufficient_baseline** reported (NOT flagged) when trailing-7d history < 5 sessions: 5 sessions.

**PROVEN NOW (ground truth, not a banner):** read-only run on real usage.db → 13 r1 flags,
r2 folds into an r1 session, 0 r3, 5 insufficient-baseline, **350/363 sessions quiet**, all
severity red. Write path verified on a DB copy: atomic write, **read-back by rowid** (sample
rowid round-trips with evidence), **idempotent** UPSERT (2nd run still 13, no dupes), ADD-only
(cost_outlier/floundering/etc. untouched). py_compile clean; **G5 gate green**.

**Status move:** gap-doc **cluster #1 GAP → detected** (burnctl now HAS the spend detector
Anthropic declined to build — #57719/#55144 closed-not-planned).

**PENDING / honest scope:**
- ~~Not yet run against production~~ **DONE 2026-06-23**: `detect_all()` run against prod
  `usage.db` (incremental) → 13 cost_anomaly rows persisted (all red, evidence intact),
  read-back by rowid (ids 1151928–1151938), other patterns unchanged (rr 94 / deep 81 /
  cost_outlier 48 / fl 10 / bc 1). Pre-write backup at `/tmp/usage.db.bak-pre-cost_anomaly-2026-06-23`.
- **Showcase copy stays PLANNED-tense** until this ships to npm (per discipline). The detector
  exists and is verified locally; it is not yet in a published release.
- This history contains **no genuine phantom-billing incident** — r1's flags here are large
  legitimate sessions, not runaway-cost events. The detector is validated structurally + on the
  weekly/guard rules; a true #68285-class event would light up r1 far harder (235× seen).

### G2 STEP 0 — headroom 502 fix (config-only; STEP 0 of G2, adoption checklist NOT started)

**Root cause (from `/stats` request log):** `cc()` → `headroom wrap claude` defaulted to the
`agent-90` savings profile (`wrap.py:127`), which carries `force_kompress=True`. On large
(~120k) cache-miss turns the forced ML Kompress path stalled ~30s, timed out, applied **nothing**
(empty transforms, 0% savings), and returned a tiny error body — the 502. Confirmed: reqs
000086/090/091 = 122k→122k, 0% saved, opt_latency ~30s, transforms `[]`.

**Fix (two coordinated config edits, no code):**
1. `~/.bashrc:185` `cc()` wrap line → `HEADROOM_SAVINGS_PROFILE=balanced HEADROOM_DISABLE_KOMPRESS=1`
   (and **removed** `--code-graph` — see cold-start note). `balanced` profile ships
   `force_kompress=False` + `smart_crusher` structural path (`agent_savings.py:87`); 70% honest
   target vs agent-90's unreachable 90% (it delivered only ~21.5–28%).
2. tmux `headroom` daemon relaunched: `HEADROOM_SAVINGS_PROFILE=balanced HEADROOM_DISABLE_KOMPRESS=1 headroom proxy`
   (env confirmed in `/proc/<pid>/environ`). `.bashrc` env kept in sync so `wrap` reuses the
   daemon instead of restarting it back to agent-90.

**PROVEN NOW (against `/stats` ground truth):** config is `balanced` + `force_kompress=False` +
`HEADROOM_DISABLE_KOMPRESS=1` (live process env). Real `cc` turns return **200** with a
**structural** transform (`router:protected:system_message`), **no kompress path**, and
`by_status` shows **zero 502s**. Steady-state `optimization_latency ≈ 92ms`. The 502 mechanism
(forced 30s ML Kompress → timeout → empty transform → 502) is **removed by construction**.
Tidify12 bypass intact (only the `else` branch of `cc()` was edited; `*Tidify12*` branch
unchanged → PHI boundary holds).

**RESIDUAL / CAVEAT (not overclaiming):** the **first** request after a cold daemon start cost
**~17.7s** opt_latency (down from ~38s when `--code-graph` was on; dropping it halved the
cold-start). This is **not** kompress and **not** code-graph — it's one-time first-request daemon
init, paid **once per daemon start**, and it is a **200, not a crash**. Under 30s but not "well
under." Did **not** iterate further per the STOP rule.

**PENDING (confirmed only on next real use):**
- Zero-502s across a **full heavy multi-hour session** — proven by construction here, but not yet
  observed end-to-end on real heavy traffic.
- **Compression > 0** (real structural savings) — NOT demonstrable on tiny single-turn `-p`
  requests (balanced doesn't compress user/system msgs, protects recent 4, no prior turns to
  crush → 0% is expected, not a fault). Needs a real multi-turn session.

**Out of scope (untouched):** the rest of the G2 adoption checklist (wrap config, holdout, MCP
stats, learn, local-first). **STOP before adoption** per session instruction.

**Open (not yet verified):**
- **G2** — headroom full-adoption harness (**STEP 0 / 502-fix done; adoption checklist not started**).
- **G3** — credit-pool burn-down tracker.
- **G4** — net-vs-gross headroom auditor.

---

## Harness state / notes

- **Maturity:** L2 documented + self-grounding, L4 measurement, and **one L3
  gate** (E-banned, via G5). Invariants 1–4 (STATE-gating, read-back-by-rowid,
  ADD-only schema, one-fix-per-commit) are still **trust-based** — a path to
  full L3 exists for later and is not blocking.

- **Versioning policy:** canonical harness state lives at **`docs/`** (tracked).
  `.claude/` is gitignored, so **`.claude/commands/goals.md` is a DEPLOYED
  COPY, not the source of truth.** Do not try to track anything under
  `.claude/`. This file lives at `docs/SESSION-STATE.md` for that reason.

- **Local-disk residue to decide on later** (NOT shipped, NOT pushed, and
  *not security-gating* — the live credential paths are already removed):
  - (a) `AUDIT.md` — untracked at repo root; documents the old mechanism.
  - (b) `backups/pre-v4.5.0-.../` — gitignored local snapshot that still
    contains the old `sessionKey` UI + writers. Frozen history; same category
    as `ARCHIVE/`. G5 scopes it out via `.gitignore` (not a prod path).

- **Dogfood finding:** skill tax ≈ **4.2k tok/turn**, ~**71% irrelevant** to
  this repo (per G-AUDIT). Capture now, prune later.

---

## Backlog (non-gating)

- **`claude_ai_tracker.py` still imports `fetch_org_id`** — the dormant
  harvester for the `org_id` just NULL-wiped in G1.6b. No caller today.
  **Do NOT rewire it.** Candidate for removal in a later cleanup pass.

### Harness audit vs canonical 5-layer model (this session — three misses, not yet acted on)

- **BUILD-TO-DELETE missing** — the harness accumulates, never prunes. In-repo
  evidence: `CLAUDE.md` 164 lines (bloated), 86 global skills (~61 dead,
  ~3k tok/turn), orphaned helpers (`timeAgo` / `windowClass` / `fmtPct`),
  the dormant `fetch_org_id` import, the stale `goal.md`. No decay test run.
- **LAYER 4 GAP (guardrails)** — a loop-iteration cap exists, but there is
  **no token/budget guardrail that halts a runaway**. burnctl *sees* waste
  (Layer 5) but cannot *fence* spend. The 502 storm was a symptom.
- **LAYER 2 (tools)** — skill tax was *measured* in G-AUDIT but not *acted on*.
  Prune candidate.
- **Strong layers:** Layer 1 (SESSION-STATE / goals), Layer 3 (G5 mechanical
  gate — ahead of baseline), Layer 5 (the product itself).

---

## SHOWCASE PLAN — claim only what's built

Anti-inflated-claim rule: a story is showcasable **only after its matching
artifact/phase lands**. Until then it stays here as a plan, not a claim.

1. **Decay-test / prune story** — *claimable ON COMPLETION.* **Ship first.**
   This is build-to-delete *demonstrated*. Receipt to publish:
   before/after of dead weight removed (dormant `fetch_org_id`, ~61 dead
   skills, orphaned helpers `timeAgo`/`windowClass`/`fmtPct`, `CLAUDE.md`
   slimmed) **plus** a "quality didn't drop" measurement. No claim until the
   prune is done and the receipt exists.

2. **Self-improving product loop** — *HEADLINE, claimable in stages.* Do NOT
   showcase a stage before the matching phase lands (inflated-claim trap):
   - after **Phase 1 backtest** agrees with the 8-fix history →
     claim *"reward signal validated"*.
   - after **Phase 3** closes →
     claim *"burnctl self-improves, bounded by hard gates"*.

---

## Loop log (newest first)

- **UNVALIDATED-AUDIT + V1–V3 detector-contract criteria** (`06d7e62` audit, `012e9cd`
  criteria, 2026-06-23) — PREREQUISITE for a worker→verifier loop (the loop itself was NOT
  built). Read past sessions/commits/tests and classified every "done" claim with no
  independent check: **VERIFIABLE** V1–V3 → committed executable criteria; **V4–V6** →
  real future criteria, honestly left unbuilt (touch the `waste_events` DB-write path);
  **J1–J4** → human-judgment, not automatable; **X1–X6** → SENSITIVE (credential / publish /
  G5 banned-string gate / harvested-id wipe / auth), EXCLUDED from any autonomous loop,
  human-gated permanently. Locked V1–V3 in `tests/test_cost_anomaly_contract.py` (13 tests
  incl. positive cases). REFLECT/verify pass 2026-06-23: re-ran the suite green, then
  re-proved each criterion fails on **injected** breakage against a faulted *copy* of
  `waste_patterns.py` in scratchpad — **no product code touched** (cwd-shadow trap noted: an
  isolated copy pulled the wrong project's `db.py`; corrected by running from the faulted dir
  with burnctl on `PYTHONPATH`). Detector contract holds; criteria are non-vacuous.
- **CIC / cost_anomaly detector** (`4880d7d`, 2026-06-22) — built gap-doc cluster #1: a
  surface-only spend detector (`cost_anomaly` waste pattern). STATE-2 backtest on live
  usage.db showed the spec'd "3× median" was noise (27.8%); user picked robust median+8·MAD
  @ $300 (3.6%, 13 flags) at the tuning checkpoint. r2 (weekly accel) + r3 (spend-without-output
  guard) kept; r3 floors recalibrated to real data (0 flags = correct guard). No enforcement
  path. Verified: rowid read-back, idempotent UPSERT, ADD-only, 350/363 quiet, G5 green. Two
  commits (code + this doc), no push. Cluster #1 GAP→detected. Showcase stays PLANNED until npm.
- **G2 STEP 0** (config-only, 2026-06-22) — fixed headroom proxy 502 storm. Root cause:
  `cc()`→`headroom wrap` default `agent-90` profile forced `force_kompress` → 30s ML stall →
  502 on ~120k cache-miss turns. Fix: `.bashrc` cc() + tmux daemon → `balanced` profile +
  `HEADROOM_DISABLE_KOMPRESS=1`, dropped `--code-graph`. Verified vs `/stats`: zero 502s,
  steady-state opt_latency ~92ms, structural transform only, no kompress, Tidify12 bypass intact.
  Residual: one-time ~17.7s cold-start on daemon's first request (down from 38s). PENDING:
  zero-502 across a full heavy session; compression>0 needs a real multi-turn session.
  Adoption checklist NOT started — STOPPED per instruction.
- **G1.6 / G1.6b** (DB data-op, 2026-06-22) — STATE-1 scan found
  `claude_ai_accounts.org_id` holding 2 real claude.ai org UUIDs (stale
  pre-v5 polling residue; no current writer). STATE-3 NULL-wiped both by
  rowid with atomic txn + read-back; re-scan clean, `session_key` wipe
  re-verified. No code commit (data-only); SESSION-STATE.md updated.
- **G5 / Commit 2** (`2121f29`) — added `tools/check_banned_strings.py`
  (self-contained allowlist, git-scoped), wired into `daily_qa.py`
  (DOD→exit 2 blocks publish) + tracked `hooks/pre-commit`. Verified green on
  clean tree, red on planted credential strings, all scope-outs ignored.
- **Commit 1** (`5c1d609`) — versioned `burnctl-headroom-harness.md`; removed
  the stale `.claude/commands/goal.md` duplicate from the working tree
  (`.claude/` is gitignored, so it was never tracked).
