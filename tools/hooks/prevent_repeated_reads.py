#!/usr/bin/env python3
"""burnctl PostToolUse hook — warn on repeat Read of the same file.

Installs as:

  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Read",
          "hooks": [
            {
              "type": "command",
              "command": "python3 /absolute/path/to/burnctl/tools/hooks/prevent_repeated_reads.py"
            }
          ]
        }
      ]
    }
  }

Behaviour:

1. Reads the hook payload from stdin (Claude Code PostToolUse JSON).
2. Extracts the file_path from the Read tool input.
3. Writes a per-session cache at /tmp/burnctl-reads-<SESSION_ID>.json.
   SESSION_ID comes from $CLAUDE_SESSION_ID, falls back to today's date
   so the cache still works in early / pre-1.0 Claude Code that didn't
   export the session id.
4. If the file has already been read in this session, prints a warning
   to stderr (Claude Code surfaces stderr but does NOT block the tool).
5. Token estimate: os.path.getsize(path) // 4.
6. Housekeeping: on startup, delete /tmp/burnctl-reads-*.json files
   whose mtime is older than 24 hours.

The hook is intentionally non-blocking — we nudge, we do not cancel.
Claude gets the read result; the user sees a line telling them that
the cost was avoidable so they can apply a CLAUDE.md rule for next
time.

Exit codes: always 0 (never block the tool). Errors are printed to
stderr and swallowed.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from datetime import datetime, timezone


CACHE_DIR = "/tmp"
CACHE_PREFIX = "burnctl-reads-"
MAX_CACHE_AGE_SEC = 24 * 3600


def _cleanup_stale_caches():
    """Remove per-session caches older than 24 hours. Never raises."""
    cutoff = time.time() - MAX_CACHE_AGE_SEC
    for path in glob.glob(os.path.join(CACHE_DIR, f"{CACHE_PREFIX}*.json")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _session_id():
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    # Fallback — one file per calendar date. Still scopes the warning
    # per day, which is better than shared global state.
    return datetime.now(timezone.utc).strftime("date-%Y%m%d")


def _cache_path(sid):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)
    return os.path.join(CACHE_DIR, f"{CACHE_PREFIX}{safe}.json")


def _load_cache(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _tokens_estimate(path):
    try:
        return os.path.getsize(path) // 4
    except OSError:
        return 0


def _hhmm(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except (OSError, ValueError):
        return "?"


def main():
    _cleanup_stale_caches()

    # Read hook payload from stdin (Claude Code sends JSON)
    try:
        raw = sys.stdin.read()
    except (OSError, KeyboardInterrupt):
        return 0
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    # Only react to Read tool calls; matcher should already filter this,
    # but we double-check defensively.
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    if tool_name != "Read":
        return 0

    tool_input = (
        payload.get("tool_input")
        or payload.get("toolInput")
        or payload.get("input")
        or {}
    )
    if not isinstance(tool_input, dict):
        return 0
    path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("filename")
    )
    if not path or not isinstance(path, str):
        return 0

    sid = _session_id()
    cache_path = _cache_path(sid)
    cache = _load_cache(cache_path)

    # Cache shape: { "<file_path>": {"ts": <unix>, "count": N}, ... }
    entry = cache.get(path)
    now = int(time.time())
    if entry:
        prev_ts = entry.get("ts", now)
        entry["count"] = int(entry.get("count", 1)) + 1
        entry["ts"] = now
        cache[path] = entry
        _save_cache(cache_path, cache)

        basename = os.path.basename(path)
        est = _tokens_estimate(path)
        prev_hm = _hhmm(prev_ts)
        msg = (
            f"⚠️  burnctl: {basename} re-read (already read at {prev_hm})\n"
            f"   Saves ~{est:,} tokens if skipped.\n"
            f"   Consider /compact if context is filling up."
        )
        print(msg, file=sys.stderr)
    else:
        cache[path] = {"ts": now, "count": 1}
        _save_cache(cache_path, cache)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Never block the tool. Report and exit clean.
        print(f"burnctl hook error (non-fatal): {e}", file=sys.stderr)
        sys.exit(0)
