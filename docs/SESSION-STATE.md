# burnctl — SESSION-STATE (persistent harness memory)

> **Top rule:** CC updates this file in the REFLECT step of every loop;
> `/goals` reads it to know what already passed. This is the L2 record of
> what is verified, so a fresh session does not re-litigate settled goals.

This file is the **canonical, tracked** harness state. See *versioning
policy* below: `.claude/commands/goals.md` is a deployed copy, not the source
of truth.

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

**Open (not yet verified):**
- **G2** — headroom full-adoption harness.
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

---

## Loop log (newest first)

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
