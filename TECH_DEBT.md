# burnctl — Technical Debt Ledger

Known deferred work. Each entry is dated, file-cited, and labeled
with a priority so future sessions can triage without re-deriving
the context. Append-only; do not rewrite existing entries.

---

## oauth_sync.py

### oauth_sync.py — subprocess hang risk [logged 2026-04-23]

`tools/oauth_sync.py:89-93` calls `subprocess.check_output` on the
`security find-generic-password` binary without a `timeout=` kwarg.
If the macOS Keychain is locked when the cron runs, the call prompts
for user password and hangs indefinitely. Fix: add `timeout=2.0`, catch
`subprocess.TimeoutExpired`, return None. Low priority — cron retries
next hour anyway — but blocks any code reuse into interactive paths
like cli.py.

### $CLAUDE_CONFIG_DIR not respected anywhere [logged 2026-04-23]

Zero grep hits repo-wide for `CLAUDE_CONFIG_DIR`. Both
`cli.py:339` and `cli.py:370` hardcode `~/.claude/.credentials.json`.
`tools/oauth_sync.py:52-56` hardcodes three sibling paths.
Means users with custom config dirs (e.g. `~/.claude-work/`) get
silent tier-1 detection failure; they currently survive via tier-2
network call. Fix: replace expanduser calls with env-var-aware helper,
update CREDENTIALS_PATHS in oauth_sync.py. Defer until after
rc.4 (Phase 4) and rc.5 (Keychain).

---

## Verdict measurement

### Zero-session waste_events verdict [logged 2026-04-23]

fix_measurements rows with sessions_count=0 can still produce
non-trivial delta.waste_events.pct_change because waste events
fire from non-session triggers (background scans, cron sync).
Verdict code will correctly return "worsened" or "improving"
based on the numeric delta — but a user reading "worsened" for
a project they haven't touched in weeks may find it misleading.

Options for future fix:
- Tag the delta with a "measurement_confidence" score based on
  sessions_since and render a faded card in the UI
- Require sessions_since >= N before trusting waste_events
  deltas (separately from the sessions gate on verdict)
- Exclude non-session-triggered waste events from the
  post-fix count

Not urgent — zero-session fixes are rare (1 of 8 in current
live data: fix 12).

### Verdict staleness on verdict-logic changes [logged 2026-04-23]

`determine_verdict` output is stored in `fix_measurements.verdict`
at write time. Dashboard reads the stored string via
`server.py:515-522` without recomputing. CLI `fix-scoreboard`
correctly recomputes via `compute_delta` at render time
(`fix_scoreboard.py:122`).

Impact: any change to verdict logic creates silent drift — rows
measured under old logic keep their old verdict until re-measured.
rc.4 hit this: fix 12 (WikiLoop repeated_reads) still rendered
insufficient_data on the dashboard after rc.4 deployed, because
its stored row was written under rc.3. `auto_measure_pending()`
from the scan cron self-corrects within 5 min of next scan;
manual kick accelerates.

Options for proper fix:
- Move verdict derivation to read-time in server.py (delete the
  stored column dependency, always recompute from metrics_json +
  delta_json). Trade: read-time CPU cost.
- Keep stored column but add a 'verdict_computed_at_version'
  column. Dashboard recomputes if stored version != current
  burnctl version. Trade: migration + version-awareness.
- Keep as-is, document the "re-measure after verdict logic
  change" ritual in CHANGELOG for every future release.

Not urgent — cron self-corrects. But every future verdict logic
change will re-hit this bug. Pick an approach before the next
verdict change.

## v4.5.1 targets (from auditor 2026-04-24)

### P2-1: Recommendation ranking FIFO not value-ranked
- File: daily_report.py:135-140
- Fix: add `savings`, `cost`, `cost_usd` to saving extraction key aliases
- Impact: TOP ACTIONS currently sorted by insight_id ASC, not money-at-stake

### P2-2: Per-project CLAUDE.md not scanned
- File: baseline_scanner.py — walks wrong path for project CLAUDE.md
- Fix: read project_roots from accounts config, walk <root>/CLAUDE.md
- Impact: claudemd_bloat rule only fires on global ~/.claude/CLAUDE.md
