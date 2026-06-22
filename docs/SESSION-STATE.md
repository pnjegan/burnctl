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
| G2-STEP0 | **502 KILL — PASS / cold-start residual** | proxy `/stats` 2026-06-22 | headroom proxy 502 storm fixed via config only (no burnctl code). See block below for proven-vs-pending |

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
