# Skill Relevance Engine — Research + Design (PRD §11)

**Status:** Research/design only. BUILD NOTHING. Verdict at bottom.
**Date:** 2026-06-26
**Question:** Is there a real *computable* per-project relevance signal that routes dead
skills into ARCHIVE / REVIVE / KEEP **without hallucinating usefulness**?
**Answer (short):** **NO — do not build the relevance engine.** Two independent,
each-sufficient reasons (native capability + uncomputable signal). Ship stats-only
archiving; fix the finance trio the native way. Evidence below.

---

## 1. Native capability (A) — citations

Claude Code **already** solves per-project scoping natively. A relevance engine would
re-implement a shipped feature (platform risk, PRD §9).

| Question | Finding | Citation |
|---|---|---|
| Per-project skills? | **Yes, native.** `.claude/skills/<name>/SKILL.md` in a repo is scoped to *that project only*; "personal overrides project" on name clash. | code.claude.com/docs/en/skills#where-skills-live |
| How skills surface | `description` frontmatter loads at session start (global per user); **body lazy-loads on invoke**. Skill frontmatter also supports `paths:`, `disable-model-invocation`, `user-invocable`. | code.claude.com/docs/en/skills#frontmatter-reference |
| Path-scoped rules | **Yes — field is `paths:`, NOT `globs:`.** Rules without `paths` load unconditionally; `paths:` globs trigger the rule when a matching file is read. | code.claude.com/docs/en/memory#path-specific-rules |
| Shipped? | Live as of 2026; CC here is **2.1.193**. | claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more |

### Glob status confirmed on disk (B-mechanism)
`~/.claude/rules/{tidify,wikiloop,burnctl}.md` use `globs:` frontmatter
(e.g. `globs: /root/projects/Tidify*/**`). **`globs:` is a Cursor convention Claude Code
does not recognize** → the field is ignored → the rules load **unconditionally** in every
session. This is exactly the CLAUDE.md-audit observation (tidify.md + wikiloop.md present
in a burnctl session). **Root cause = wrong field name. Fix = rename `globs:` → `paths:`.**
This is a one-line config fix, not an engine.

**Implication:** the delivery mechanism the PRD wanted to *build* already exists
(`.claude/skills/` + `paths:`). The relevance engine is a workaround for a non-problem.

---

## 2. Computable signal (B) — exact data, derivation, 3 worked cases

### What burnctl actually stores (cited columns, `data/usage.db`)
- `sessions(project, source_path, model, input/output/cache tokens, cost_usd,
  tool_call_count, bash_count, read_count, write_count, grep_count, mcp_count,
  work_classification, inferred_project, …)` — **tool-call COUNTS by tool name; no file
  paths, no extensions, no languages.** `scanner.classify_session_tools()` increments
  counters from `_WRITE_TOOL_NAMES`/`_READ_TOOL_NAMES` and **discards the file argument**.
- `account_projects(project_name, keywords)` — 14 rows. Keywords are **path/identity
  aliases** (WealthOS→`["wealth-journal","wealth-tracker"]`, burnctl→`["burnctl","jk-usage",
  "cladash"]`), **not domain descriptors**.
- `work_classification` — **empty on all 61,670 sessions** (unusable).
- `skill_usage(session_id, project, skill_name, invoked, …)` — table exists, **0 rows**
  (never wired).

So the only project-identity signal is **name + path-alias keywords**. There is **no
project *domain* or *capability* signal** anywhere in the data.

### Derivation under test
`relevance(skill, project) = | domain_terms(skill) ∩ work_terms(project) |`
where `domain_terms` = frontmatter/body keywords (deterministic, inspectable) and
`work_terms` = project name + `account_projects.keywords` (the only thing we have).

### 3 real cases — does it separate them?

| Case | skill domain_terms | project work_terms | lexical ∩ | computed | expected | clean? |
|---|---|---|---|---|---|---|
| 1. mf-portfolio vs **burnctl** | mutual,fund,portfolio,equity,sebi,nav,elss,cap,india | burnctl,jk-usage,cladash | ∅ | LOW | LOW | ✅ |
| 2. mf-portfolio vs **WealthOS** | (same) | wealthos,wealth-journal,wealth-tracker | ∅ | LOW | **HIGH** | ❌ |
| 3. postgres-patterns vs **any** | postgres,sql,query,index,schema,migration | *(SQL usage not recorded anywhere)* | — | **uncomputable** | HIGH/LOW | ❌ |

- **Case 1 works** — true negatives are detectable (no shared token).
- **Case 2 fails** — "wealth" ≈ "mutual fund" is **semantic**, not lexical. No shared token,
  so mf-portfolio scores *identical* against WealthOS and burnctl. Closing the gap needs an
  embedding/LLM (**hallucination — forbidden**) or a hand-declared project→domain ontology
  (**not "computed from data"; it's manual config that just re-creates native scoping**).
- **Case 3 is impossible** — burnctl records no file types/languages, so it cannot know any
  project uses SQL. Capability-relevance is unmeasurable with the current schema.

**Result: 1 of 3 separable. Per the PRD's own stop rule, the signal is NOT computable.**
The deterministic signal can assert *"no relevance"* but cannot non-hallucinatorily assert
*"high relevance"* — which is precisely what REVIVE would need.

---

## 3. Three-bucket routing (C) — predicates that DON'T need relevance

The finance-trio failure (good-but-dead skills wrongly archived) is real, but the fix is
**structural health, not relevance.** A dead skill that is *broken* explains its own zero
usage — no domain guess required.

```
KEEP    = invocations_30d ≥ 1                      (ACTIVE or RARE; from JSONL)
REVIVE  = invocations_30d = 0  AND  structurally_broken
          (no/invalid frontmatter, missing name/description, dead file refs)
ARCHIVE = invocations_30d = 0  AND  structurally_healthy
HOLD    = anything else / uncertain → never auto-moved
```

- `invocations_30d` — computable (JSONL `"skill":"X"` + `<command-name>`).
- `structurally_broken` — computable (the bug-hunt structural scan: frontmatter parse +
  ref existence). **Deterministic, no hallucination.**
- **Relevance is deliberately absent** — REVIVE keys off *brokenness*, which is measurable,
  not *usefulness*, which is not.

### Finance-trio worked end-to-end
`mf-portfolio`, `earnings-analysis`, `market-context`:
- invocations_30d = **0** → not KEEP.
- structural scan = **no YAML frontmatter** (missing `name`+`description`) → `structurally_broken = true`.
- → **REVIVE**, *because they're broken*, not because we guessed they're "finance."
- **Revive action is NATIVE, not global:** (a) add the frontmatter block (fixes auto-trigger);
  (b) relocate them to `<wealthos-repo>/.claude/skills/` **or** add `paths:` scoping so CC
  loads them only in WealthOS work — they stop polluting burnctl sessions with **zero**
  burnctl code. No relevance score is computed or needed.

This routes the trio correctly using only computable inputs, sidestepping the hallucination
problem entirely.

---

## 4. Hallucination guard (D)
- REVIVE never fires on a relevance guess. Its only trigger is **deterministic structural
  brokenness**; the bucket says "dead + broken → a human should fix-or-archive," never
  "this is useful for project X."
- No skill self-description is ever trusted as evidence of relevance.
- Where domain relevance *cannot* be computed (cases 2 & 3 — i.e. almost everything),
  the skill stays **ARCHIVE-or-HOLD**, never auto-REVIVE.

---

## 5. VERDICT — **NO-BUILD the relevance engine** (build/no-build, honest)

**Computable non-hallucinatorily? NO.** Two independent sufficient reasons:

1. **Redundant with native CC.** Per-project skills (`.claude/skills/`) and path-scoped
   rules (`paths:`) already ship (CC 2.1.193). The correct mechanism exists; building a
   scorer is reinventing it (platform risk realized).
2. **Signal insufficient.** burnctl stores identity (not domain) keywords and tool-call
   counts (not file types). Deterministic relevance separates 1 of 3 test cases; the two
   positive cases require semantics burnctl cannot compute → REVIVE-on-relevance would be a
   guess (forbidden).

### Ship instead (no new engine)
- **Stats-only archiving** — DEAD/ACTIVE/RARE from JSONL (already validated this session).
- **Structural REVIVE bucket** — reuse the bug-hunt structural scan; flag dead+broken for
  human fix. No relevance code.
- **Finance trio (native fix):** add frontmatter (BUG-1/2/3) + move to
  `<wealthos>/.claude/skills/` or add `paths:`.
- **Rules contamination (native fix):** rename `globs:` → `paths:` in
  `~/.claude/rules/*.md`.

### What would change the verdict to YES
A relevance engine becomes worth building **only if** burnctl starts recording a real
per-project *work* signal — i.e. scanner extracts **edited-file extensions / languages /
imported packages** per session (it currently throws the file argument away). With a
per-project language/dependency histogram, capability-relevance (Case 3) becomes computable
and Case 2 can be grounded in shared dependencies rather than semantics. Absent that schema
change, the honest answer is **stats + structural health, and let native scoping do the
routing.**
