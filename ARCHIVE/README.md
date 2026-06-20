# ARCHIVE — retired credential-path code (v5 clean architecture)

These files were moved out of the production/release path during the v5
clean-architecture refactor (2026-06-20). They implement the **old
session-credential movement** that v5 removes entirely:

| File | What it did |
|------|-------------|
| `tools/mac-sync.py` | Copied the browser Cookie SQLite DB and decrypted the claude.ai `sessionKey` via the macOS Keychain "Safe Storage" key. |
| `tools/get-derived-keys.py` | Derived/printed the per-browser AES cookie-decryption keys. |
| `tools/oauth_sync.py` | Read the Claude Code OAuth `accessToken` and POSTed it to the dashboard `/api/claude-ai/sync`. |
| `tools/sync-daemon.py` | 5-minute loop driving mac-sync / oauth_sync. |
| `oauth_lookup.py` | Called the consumer endpoint `claude.ai/api/account` with a Bearer token (first-run plan auto-detect, tier 2). |
| `tests/test_oauth_lookup.py` | Tests for the above. |

## Status

- **Not shipped** — excluded from the npm tarball (`.npmignore`) and the
  `package.json` `files` allowlist no longer references them.
- **Not imported** — every production import of these modules was removed.
- **Kept in git for now** — history scrubbing and credential rotation are a
  separate, later pass. Do **not** re-wire these into the live code.

The replacement for browser attribution is the **no-cookie extension**
(reads only `document.title` + URL + timestamp; never touches cookies,
localStorage, or `claude.ai/api/*`).
