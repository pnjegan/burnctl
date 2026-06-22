# burnctl × headroom — harness build plan

> Companion to `/goals`. This is the harness: goals as closed loops, evals as gates, state machine as the write protocol. Nothing advances on a green banner — only on a passed eval against ground truth. Sequencing is enforced: **G0/G1 gate everything; G2 gates G4; G3 gates G4; G5 runs as the standing gate.**

---

## The harness itself (read once)

**State machine (write protocol).** Every DB or file write goes STATE 1 (read-only audit) → STATE 2 (dry-run, print the diff) → STATE 3 (atomic write + read-back assert by rowid). No exceptions.

**Loop.** Each goal runs: PLAN (write the eval first) → ACT → OBSERVE (ground truth) → VERIFY (run eval) → REFLECT (verdict + one commit) → LOOP. Max 3 iterations per goal before escalating.

**Eval gates (the harness only advances when these pass):**
- `E-readback`: every insert/update re-read by rowid, asserted present and correct.
- `E-qa`: full QA suite green (current baseline: 87 pass, 1 known-unrelated namespace collision).
- `E-banned`: no `sessionKey` / `Cookie:` / `claude.ai/api/*` in prod paths (scopes out `ARCHIVE/`, comments, the NULL-wipe lines, the reject-guard set). This is G5; it runs after every goal.
- `E-net`: any "saved" claim is the **billed** delta from local JSONL, never a self-reported gross number.

**Anti-drift.** Re-run `/goals` at the top of every session and after any compaction. Goal grounding every loop is the harness's drift control (same principle as Tether's Drift Score — out-of-scope actions ÷ total actions).

---

## G0 — Reissue OpenRouter key
**Goal:** Close the last live exposed secret (was in April Drive backups; powers `fix_generate`).
**Loop:**
- ACT: reissue in OpenRouter console (human, not pasted into chat).
- STATE 2: dry-run the settings-row update.
- STATE 3: write, then read-back the row by rowid; age-vault the new value.
**Eval / Done:** old key → 401 on a probe call; new key → 200; settings row read-back matches; value in age vault, not in git/chat.
**Guardrails:** named, never pasted. No code dependency — do this first because it's free.

---

## G1 — Stage 2: verify the clean core (read-only)
**Goal:** Prove the local-JSONL analytics survived Stage 1 credential removal intact and credential-free.
**Loop (all read-only — no STATE 3 here):**
- Confirm `scan` ingests `~/.claude/projects/**/*.jsonl` → `usage.db` with no credential in the path.
- Confirm attribution, waste-detection, burn-rate, and fix-ROI modules compute correctly post-Stage-1.
- Confirm the dead claude.ai dashboard panels **degrade to empty, not stack traces**.
- Run full QA.
**Eval / Done:** `E-qa` green; every analytics module returns real numbers on real local data; dead panels render empty; `E-banned` green. Zero writes this goal.
**Guardrails:** read-only verification, safe to start, no gating read outstanding.

---

## G2 — headroom full-adoption harness
**Goal:** Actually use headroom, and apply *all* features that fit your workflow — not just `wrap claude`. Make adoption a config artifact, not a habit.

**Feature adoption checklist (apply + verify each):**
| Feature | Apply | Verify |
|---|---|---|
| `headroom wrap claude --code-graph` | default for cc on VPS (file-heavy sessions) | proxy on :8787 intercepts; a session shows compressed payloads |
| Output-token holdout | `export HEADROOM_OUTPUT_HOLDOUT=0.1` | dashboard shows "Output Tokens Saved" measured-vs-estimated + confidence band |
| MCP stats surface | `headroom mcp install` → `headroom_stats` | stats callable over MCP (this is what G4 consumes) |
| Prometheus endpoint | enable proxy-prod metrics | `curl :8787/metrics` returns per-request token/cost |
| `headroom learn` | run against failed sessions → writes CLAUDE.md/AGENTS.md | corrections written; **burnctl proves ROI, headroom just writes the rule — keep that boundary** |
| CacheAligner | on by default | verify cache hits actually rise (measurable in G4, not assumed) |
| Cross-agent memory | `--memory` **only if** you run Codex too | skip if CC-only; mark N/A |
| Local-first hardening | `HF_HUB_OFFLINE=1`, pre-pulled `kompress-base`, pinned wheel + SHA | first run does zero network fetch |
| **Tidify12 exclusion** | `cc` shell function skips headroom for Tidify12 (PHI boundary) | a Tidify12 session bypasses the proxy — assert in the wrapper |
| **`wrap copilot --subscription`** | **DO NOT** | OAuth→Copilot token exchange = credential movement. Stays off. |
| Image compression | skip | not relevant to code/text workflow; mark N/A |

**Loop:**
- STATE 1: read current `.bashrc` cc/cc-tidify functions.
- STATE 2: dry-run the bashrc block (wrap defaults, env vars, Tidify12 guard).
- STATE 3: apply; re-source; assert `cc` launches the proxy and `cc-tidify`/Tidify12 does not.
**Eval / Done:** every checklist row is either verified-applied or explicitly N/A; Tidify12 bypass asserted; no network fetch on cold start; `E-banned` green.

---

## G3 — Credit-pool burn-down tracker (the net-new wedge)
**Goal:** Track burn-down against the new June-15 automation credit pool ($20 Pro / $100 Max5x / $200 Max20x) for headless `claude -p` + Agent SDK runs. Nobody owns this view yet. **This is local arithmetic, not the cut 5-hour feature — no credential, no claude.ai call.**

**Loop — starts with a discovery gate (do not build before this passes):**
- **STATE 1 discovery (gating):** Can headless/automation runs be distinguished from interactive in the JSONL? Look for a flag/field/entrypoint marker. *If they can't be cleanly classified, STOP and surface — the feature depends on this.*
- STATE 1: confirm `total_cost_usd` (or per-step usage) is present per headless run; capture the rate table (Opus 4.8 $5/$25, Sonnet 4.6 $3/$15, Haiku 4.5 $1/$5; cache reads ~$0.50/$0.30; cache writes 1.25×).
- STATE 2: dry-run the burn-down computation: `sum(headless cost since cycle anchor) / allotment`; print projected depletion date at current rate.
- STATE 3 (schema, ADD-only): add a `credit_pool` table or columns (cycle_anchor, plan_tier, allotment, running_cost). Read-back by rowid.
**Eval / Done:** on real local data, tracker prints e.g. "Max pool 78% consumed, day 9, depletes the 23rd"; numbers reconcile to summed JSONL cost; `E-readback` + `E-banned` green.
**Honest UI caveat (must ship in the view):** remaining balance isn't exposed locally — this is *estimated from summed local cost since cycle start*, not a true balance read. Label it estimated.

---

## G4 — Net-vs-gross headroom auditor (the defensible number)
**Goal:** burnctl becomes the independent ledger that audits headroom's own savings claim — the one number neither headroom nor anyone else can produce: **net billed savings including the CCR retrieval tax.**

**The measurement loop (this is the "ship with loops" core):**
```
PLAN     → define net: net_saved = baseline_billed − treatment_billed
           (both from local JSONL), vs headroom's claimed gross from headroom_stats.
ACT      → run comparable sessions: baseline (headroom off) and treatment (headroom on,
           --code-graph). Same class of work (WealthOS/burnctl, never Tidify12).
OBSERVE  → burnctl reads (a) billed JSONL for both, (b) headroom_stats via MCP /
           :8787/metrics for claimed gross + retrieval-call count.
VERIFY   → compute net. Compute retrieval tax = claimed_gross − net. Flag if tax is high
           (e.g. compresses 90% but model retrieves half back → net ≪ gross).
REFLECT  → write verdict to dashboard: "headroom claims X%, billed net is Y%, retrieval
           tax Z%." Recommend: keep / tune (e.g. disable text compression if it doesn't net out).
LOOP     → feed verdict back; re-run after the tuning change; prove the delta moved.
```
**Loop (build):**
- STATE 1: confirm burnctl can read headroom's stats (MCP `headroom_stats` and/or `:8787/metrics`) read-only.
- STATE 2: dry-run the diff: billed-net vs claimed-gross vs retrieval-tax.
- STATE 3 (ADD-only): persist audit rows (session, claimed_gross, billed_net, retrieval_tax, verdict). Read-back by rowid.
**Eval / Done:** for a real A/B pair, burnctl outputs net %, gross %, and retrieval tax, and the net is derived only from billed JSONL (`E-net`); audit row read-back asserts; `E-banned` green.
**Boundary:** don't try to out-write `headroom learn`'s CLAUDE.md rules. Your edge is proving whether a rule/compression *actually reduced billed spend* — the ROI verdict, not the rule text.

---

## G5 — Enforcement test (the standing gate)
**Goal:** CI fails if `sessionKey` / `Cookie:` / `claude.ai/api/*` appears in a prod path.
**Loop:**
- STATE 1: enumerate prod paths; scope out `ARCHIVE/`, comments, the NULL-wipe lines, the reject-guard set.
- STATE 2: dry-run the matcher against the tree; confirm zero false positives on the scoped-out set.
- STATE 3: add the CI test. Read-back the test file; run it.
**Eval / Done:** test passes on clean tree, fails on a planted banned string, ignores scoped-out set. This becomes `E-banned`, run after every other goal.

---

## Ship order (the outer loop)
```
G0 (free, do now)
  → G1 (read-only verify)            [gate: E-qa, E-banned]
    → G2 (headroom adoption)         [gate: checklist verified, Tidify12 bypass]
    → G3 (credit-pool tracker)       [gate: discovery passed, E-readback]
      → G4 (net-vs-gross auditor)    [gate: E-net, read-back]   ← needs G2+G3
G5 woven in as the standing E-banned gate after each
```
Do not push `v5.0-session-1` to the public remote until the `unitedappsmaker-tech` vs `pnjegan` auth mismatch is resolved AND there's a deliberate decision about leaked-token-in-history (rotation closed it; the string persists at tag v1.0.10).
