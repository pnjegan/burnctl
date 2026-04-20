"""burnctl mcp-audit — find orphan MCP servers.

Reads ~/.claude/settings.json and any discovered .mcp.json files to list
configured MCP servers. For each, scans the last 30 days of JSONL session
files and counts sessions where at least one tool call's name starts with
`mcp__<server>__`. Servers loaded but never called are pure overhead.

Generic — works for any MCP server name. Does not rely on the sessions
table (mcp_count is aggregate per session, not per-server).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path


LOOKBACK_DAYS = 30
# Conservative per-server overhead estimate. MCP tool definitions inject
# ~80-120 tokens per tool into the system prompt on session start. We don't
# know the exact per-server count without sampling, so report as a range.
EST_OVERHEAD_PER_SERVER = 85  # tokens/session, low end of observed range
SESSION_ESTIMATE_CAP = 100_000  # don't blow up on pathological JSONL


# ─────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────

def discover_configured_mcp_servers():
    """Read settings.json + any .mcp.json files. Returns dict {name: source}."""
    servers = {}

    # ~/.claude/settings.json
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            d = json.loads(settings_path.read_text())
            for name in (d.get("mcpServers") or {}).keys():
                servers[name] = str(settings_path)
        except json.JSONDecodeError:
            pass

    # ~/.claude/.mcp.json + project-scoped .mcp.json
    candidates = [
        Path.home() / ".claude" / ".mcp.json",
        Path.home() / ".mcp.json",
        Path.cwd() / ".mcp.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
            for name in (d.get("mcpServers") or {}).keys():
                servers.setdefault(name, str(p))
        except json.JSONDecodeError:
            continue

    return servers


# ─────────────────────────────────────────────────────────
# JSONL scan for mcp__<server>__<tool> tool names
# ─────────────────────────────────────────────────────────

def scan_mcp_tool_usage(days=LOOKBACK_DAYS):
    """Return (sessions_with_mcp, usage_by_server).

    sessions_with_mcp: total count of sessions (JSONL files) that invoked
      at least one MCP tool.
    usage_by_server: {server_name: set(session_id)}.
    """
    cutoff = time.time() - days * 86400
    usage = defaultdict(set)
    sessions_total = 0
    sessions_with_mcp = 0

    # Same discovery approach as scanner.py — all project dirs under ~/.claude/projects/
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return 0, usage

    pattern = re.compile(rb"mcp__([A-Za-z0-9_-]+)__[A-Za-z0-9_-]+")

    for jsonl in projects_root.rglob("*.jsonl"):
        try:
            if jsonl.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        sessions_total += 1
        session_id = jsonl.stem  # JSONL filename is the session UUID
        found_any = False
        try:
            with open(jsonl, "rb") as f:
                data = f.read(SESSION_ESTIMATE_CAP * 10)
        except OSError:
            continue
        for m in pattern.finditer(data):
            server = m.group(1).decode("ascii", errors="replace")
            usage[server].add(session_id)
            found_any = True
        if found_any:
            sessions_with_mcp += 1

    return sessions_total, usage


# ─────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────

def run_mcp_audit():
    print()
    print("burnctl mcp-audit")
    print("=" * 64)
    print("Which configured MCP servers are actually earning their token cost?")
    print(f"Window: last {LOOKBACK_DAYS} days\n")

    configured = discover_configured_mcp_servers()
    if not configured:
        print("No MCP servers found in settings.json or .mcp.json files.")
        print("If you expected some: check ~/.claude/settings.json")
        return

    total_sessions, usage = scan_mcp_tool_usage(LOOKBACK_DAYS)
    if total_sessions == 0:
        print("No JSONL session files found in the last 30 days.")
        print(f"Checked: ~/.claude/projects/")
        return

    active = []
    orphan = []
    # Also surface servers we see in JSONL but aren't in config (legacy names)
    unconfigured_active = []

    for name, source in sorted(configured.items()):
        sess_with_calls = len(usage.get(name, set()))
        if sess_with_calls > 0:
            active.append((name, source, sess_with_calls))
        else:
            orphan.append((name, source, 0))

    for name in sorted(usage.keys()):
        if name not in configured:
            unconfigured_active.append((name, len(usage[name])))

    print(f"Servers configured: {len(configured)}   "
          f"JSONL sessions scanned: {total_sessions}\n")

    if active:
        print("ACTIVE (called in last 30d):")
        for name, _source, n in active:
            pct = int(round(100 * n / total_sessions)) if total_sessions else 0
            print(f"  [OK]   {name:<24} — {n}/{total_sessions} sessions ({pct}%)")

    if orphan:
        print()
        print("ORPHAN (configured but never called in 30d):")
        orphan_overhead_monthly = 0
        for name, _source, _ in orphan:
            monthly = EST_OVERHEAD_PER_SERVER * total_sessions
            orphan_overhead_monthly += monthly
            print(f"  [WASTE] {name:<24} — 0/{total_sessions} sessions  "
                  f"(~{EST_OVERHEAD_PER_SERVER} tok/session × {total_sessions} = "
                  f"~{monthly:,} tok/mo)")
        print()
        cost_usd = orphan_overhead_monthly * 3.0 / 1_000_000  # Sonnet mid-band
        print(f"Total orphan overhead (estimated): ~{orphan_overhead_monthly:,} tok/mo "
              f"≈ ${cost_usd:.2f}/mo")

    if unconfigured_active:
        print()
        print("LEGACY / UNCONFIGURED (seen in JSONL but not in current config):")
        for name, n in unconfigured_active[:10]:
            print(f"  [LEGACY] {name:<22} — {n} session(s) in last 30d")

    print()
    if orphan:
        print("Fix: remove orphan servers from ~/.claude/settings.json,")
        print("or move to project-specific .mcp.json so they only load in")
        print("the projects where they are actually used.")
    elif not active and not unconfigured_active:
        print("No MCP tool calls detected in the scan window.")
        print("If that is unexpected, verify your MCP servers are actually running.")
    else:
        print("All configured servers are earning their token cost.")
    print()


if __name__ == "__main__":
    run_mcp_audit()
