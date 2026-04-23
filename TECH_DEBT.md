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
