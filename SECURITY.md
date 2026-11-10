# Security

## Disclosed incidents

### 2026-04-22 — git history rewritten to purge committed credentials

**What happened:** On 2026-04-11 (initial commit), a local `data/usage.db` file
was unintentionally committed before the `.gitignore` was finalized. It was
removed from `HEAD` on 2026-04-13, but the blob remained in git history.

**What it contained:** test-run session metadata, a dashboard key, a sync token,
an OpenRouter API key, and two claude.ai session cookies.

**What was done:** All credentials were rotated, and the old values are
confirmed invalid (HTTP 403 when tested against the claude.ai organizations
endpoint). On 2026-04-22 the blob was purged from all git history via
`git filter-repo`, and the repository was force-pushed to overwrite the remote.

**What you need to do:** If you cloned burnctl before 2026-04-22, your clone has
divergent history. Please re-clone:

```bash
cd .. && rm -rf burnctl && git clone https://github.com/pnjegan/burnctl.git
```

**How it was found:** this repository's own 6-dimension self-audit, plus a 7th
independent meta-review — documented in `audit-reports/2026-04-22-*.md`. The
tool that audits token waste also audits itself; in this case that is the only
reason the blob was found at all.

## Current security posture (personal use)

burnctl is designed for single-user personal deployment.

| Control | Status | Notes |
|---|---|---|
| Dashboard authentication | ✅ Done | HMAC timing-safe key comparison |
| CSRF protection | ✅ Done | Origin checks on all write endpoints |
| Sensitive data scrubbing | ✅ Done | raw_response stripped before API responses |
| Auto-update on launch | ✅ Removed | No silent code updates |
| Process isolation | ✅ Done | PID lock prevents duplicate processes |
| DB file permissions | ✅ Done | 0600 on Unix (owner-only read) |
| Network exposure | ✅ Localhost only | Binds to 127.0.0.1, not 0.0.0.0 |
| HTTPS | ❌ Not implemented | Localhost only — SSH tunnel for remote |
| Secrets encryption at rest | ❌ Not implemented | API keys in plaintext SQLite |
| Multi-user auth | ❌ Not implemented | Single shared dashboard key |
| Audit trail | ❌ Not implemented | No per-action logging |

## Known limitations

**For personal use on a developer machine:** the current security posture is acceptable.

**Not recommended for:**
- Team deployments without additional controls
- Cloud/VPS exposure without HTTPS and proper auth
- Storing credentials you cannot rotate

## Reporting a vulnerability

Open a GitHub issue with label `security`.
For sensitive reports, email the repository owner directly via GitHub.

## What data burnctl stores

- Session token counts (not conversation content)
- Tool call types and counts per session
- Cost calculations
- Dashboard authentication key (random, generated on init)
- API key for fix generation (only if configured)
- claude.ai session cookie (only if browser tracking enabled)

## What burnctl does NOT store

- Conversation content or message text
- File contents from your projects
- Personal identification information
- Any data from outside your local machine
