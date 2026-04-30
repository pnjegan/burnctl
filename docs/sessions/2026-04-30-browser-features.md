# burnctl session — 2026-04-30 morning (browser feature track)

Handoff for next session resuming the browser-side feature work.

## State at handoff

- Branch: main, fully synced with origin
- Latest commit: 4475f44 fix(dashboard): clarify Pro panel copy; file TD-27/TD-28
- npm @latest = 4.5.5 (yesterday's release, clean)
- Working tree clean
- VPS at vps3326999, pm2 serving v4.5.5, dashboard live at localhost:8080
- Template hot-reload confirmed: Flask re-reads templates per request, no pm2 restart needed for template-only changes

## What landed this session (4 commits)

1. `2c89738` docs(td): close TD-17 as misdiagnosed; file TD-25/TD-26
   - TD-17 ("missing upsert key") investigated: dedup already exists at two layers (write-side `_insight_exists_recent` + read-side `get_insights` collapse on (type, project, message))
   - The "messy report" perception is a rendering issue, not a data issue
   - Filed TD-25 (rule-window hardcoding across 26 call sites) and TD-26 (group-card rendering)

2. `4475f44` fix(dashboard): clarify Pro panel copy; file TD-27/TD-28
   - Reworded `templates/dashboard.html:1157` from "No Claude Code sessions — browser tracking only" to "Browser sessions tracked above; CLI sessions track separately when active"
   - Filed TD-27 (account label provenance — capture organization.name from Anthropic API)
   - Filed TD-28 (hero card "Browser-only account" headline)

## TD ledger (after this session)

**Open (sequential):**
- TD-15 — Pro panel copy reword (RESOLVED 2026-04-30 in commit 4475f44 — needs status flip)
- TD-16 — Recent Browser Sessions widget gates on titles, not data
- TD-18 — Anthropic settings reconciliation (BLOCKING-CHECK before F4) — Pro reconciles cleanly, Max not yet eyeballed
- TD-25 — Rule debounce windows hardcoded across 26 call sites (P2)
- TD-26 — Dashboard renders related observations as N separate cards (P3, F4-adjacent)
- TD-27 — Account labels user-supplied, no auto-derivation (P3)
- TD-28 — Hero card "Browser-only account" headline reads as negative (P3)

**Reserved slots (do not reuse):**
- TD-19..TD-24 reserved for the 6 deferred items in `.deferred-tds-2026-04-29.md`

**Next sequential open slot:** TD-29

## Next item: TD-29 (metered overage rendering) — the headline feature

**Why first**: yesterday's competitive research established this is the single highest-ROI browser feature on the roadmap. No other tool surfaces metered overage. Anthropic's settings page shows "$21.36 of $50 extra usage (43%)" — burnctl's DB has the same values in `claude_ai_snapshots.extra_credits_used` and `.extra_credits_limit`, polled fresh every ~5 min, currently never rendered.

**Scope discipline**: minimum-viable. One number rendered on each account panel + edge-case handling (no metered configured / $0 used / over 100%). Anything more is a future TD.

**Verified data**:
- work_pro: extra_credits 2136/5000 = $21.36/$50 = 42.72%
- personal_max: extra_credits 6894/6900 = $68.94/$69 = 99.9%
- Both fresh (polled within last 5 min), `is_enabled=true` in raw_response

**Open question for STATE 1**: `/api/accounts` does NOT currently include extra_credits fields. Need to find which endpoint (or none) currently exposes them, then decide between adding fields to `/api/accounts` vs. reading from the existing endpoint vs. creating a new one. Pick cheapest.

## Standing rules (apply to every prompt — embed in next session's prompts)

1. NO HARDCODING. Time windows, thresholds, paths, IDs, account names, project names, organization names, dollar amounts, plan names — configurable. If a value would need to change in 6 months without a code edit, file a TD or refactor it.

2. NO MANUAL STEPS. Don't add features that require the user to run a separate sync script, enable a setting, or remember to do anything. Automate.

3. CLI SIDE — USE THE JSONL. ~/.claude/projects/ session JSONL has tool calls, tool results, per-turn model selection, file reads, errors, costs. Check it before inventing new sources.

4. BROWSER SIDE — USE WHAT ANTHROPIC EXPOSES. Use claude.ai's API surface (usage windows, extra_usage, org metadata, conversations). mac-sync.py is the existing client-side bridge for authenticated polling — extend it for new fields when needed; don't introduce parallel polling mechanisms.

5. READ-BEFORE-DRAFT. Before drafting a TD or fix, read the affected code path. Evidence beats interpretation.

## Discipline rules (carried from yesterday)

- One commit per change
- STATE 1 (read-only diagnostics) → STATE 2 (draft in chat for review, no file write) → STATE 3 (write + commit + push)
- ASK gate between every commit, no auto-chaining
- After every Python code change: `tsc` or project test command (no equivalent for templates — Flask hot-reloads)
- Live verification after template changes via `curl localhost:8080 | grep`

## Sequence after TD-29 (today's plan, if energy holds)

1. **TD-29** — metered overage rendering (1.5-2 hr) ← NEXT
2. **TD-16** — Recent Browser Sessions widget gating (~45 min)
3. **TD-18 close** — Max eyeball + bump to v4.5.6 + CHANGELOG + smoke test + npm publish + git tag (~1-1.5 hr)

Realistic landing for v4.5.6 publish: ~12:30-13:00 IST.

## LinkedIn post

Deferred to tomorrow (Friday 1-May), with screenshots of v4.5.6's metered overage feature + 24-hour soak. Angle: "browser-side visibility that no other tool surfaces — and the discipline arc that got us there."

## Open architectural questions (parking lot, not blocking)

- mac-sync.py vs server-side polling: TD-27 captures the org-name fix using mac-sync.py (correct for Mac+VPS setup — claude.ai auth is browser-bound, lives on Mac). Eventually-replaceable but not today.
- F4 implementation (zero-floor + after-sample inflation): unblocked once TD-18 closes cleanly. Real meat for a future session.

## To resume in fresh session

Paste this entire document as context, then:
> Resuming burnctl browser-feature track per `docs/sessions/2026-04-30-browser-features.md`. Next item: TD-29 metered overage rendering. Start with STATE 1.
