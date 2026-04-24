"""baseline_scanner — context overhead snapshot.

Discovers everything that gets loaded into a Claude Code session BEFORE the
user types a single token:

  - Agents:   ~/.claude/agents/*.md
  - Skills:   ~/.claude/skills/** (first SKILL.md or *.md in each dir)
  - MCPs:     ~/.claude.json (mcpServers), ~/.claude/settings.json (mcpServers),
              ~/.claude/.mcp.json (servers) — priority order, first file found wins
  - CLAUDE.md:
      * global: ~/.claude/CLAUDE.md
      * projects: CLAUDE.md under ~/.claude/projects/** (one level deep by design —
        Claude Code stores per-project CLAUDE.md alongside session JSONL)

Tokens are counted with tiktoken (cl100k_base) if available, otherwise via
char-based approximation (len(text) * 0.25). A module-level flag
TIKTOKEN_AVAILABLE reflects which path is in use.

For MCP servers, we use a fixed 500-token estimate per server entry. The exact
value varies by server (schema size, description length, tool count) — 500 is
a safe mid-band approximation. Refine once Anthropic publishes MCP injection
token accounting.

Guardrail: if any source file fails to read, it is SKIPPED with a stderr
warning — scan_baseline() never raises on a missing/broken source.
"""
from __future__ import annotations

import os
import sys
import datetime
from typing import List, Dict, Any

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    TIKTOKEN_AVAILABLE = True
except Exception:
    _ENC = None
    TIKTOKEN_AVAILABLE = False


MCP_FIXED_TOKEN_ESTIMATE = 500

HOME = os.path.expanduser("~")
AGENTS_DIR = os.path.join(HOME, ".claude", "agents")
SKILLS_DIR = os.path.join(HOME, ".claude", "skills")
GLOBAL_CLAUDEMD = os.path.join(HOME, ".claude", "CLAUDE.md")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")

MCP_CONFIG_CANDIDATES = [
    os.path.join(HOME, ".claude.json"),
    os.path.join(HOME, ".claude", "settings.json"),
    os.path.join(HOME, ".claude", ".mcp.json"),
]


def estimate_tokens(text: str) -> int:
    """Token count for text. tiktoken (cl100k_base) if available, else char approx."""
    if not text:
        return 0
    if TIKTOKEN_AVAILABLE:
        try:
            return len(_ENC.encode(text))
        except Exception as e:
            _warn(f"tiktoken encode failed ({e}); using char approx")
    return int(len(text) * 0.25)


def _warn(msg: str) -> None:
    print(f"[baseline_scanner] WARNING: {msg}", file=sys.stderr)


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, PermissionError, UnicodeDecodeError) as e:
        _warn(f"could not read {path}: {e}")
        return None


def _iso_mtime(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
        return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except OSError:
        return ""


def _scan_agents() -> List[Dict[str, Any]]:
    sources = []
    if not os.path.isdir(AGENTS_DIR):
        return sources
    try:
        entries = sorted(os.listdir(AGENTS_DIR))
    except OSError as e:
        _warn(f"could not list {AGENTS_DIR}: {e}")
        return sources
    for name in entries:
        if not name.endswith(".md"):
            continue
        path = os.path.join(AGENTS_DIR, name)
        text = _read_text(path)
        if text is None:
            continue
        sources.append({
            "type": "agent",
            "name": name[:-3],
            "path": path,
            "tokens": estimate_tokens(text),
            "last_modified": _iso_mtime(path),
        })
    return sources


def _scan_skills() -> List[Dict[str, Any]]:
    sources = []
    if not os.path.isdir(SKILLS_DIR):
        return sources
    try:
        entries = sorted(os.listdir(SKILLS_DIR))
    except OSError as e:
        _warn(f"could not list {SKILLS_DIR}: {e}")
        return sources
    for name in entries:
        skill_dir = os.path.join(SKILLS_DIR, name)
        if not os.path.isdir(skill_dir):
            continue
        # Prefer SKILL.md; fall back to any single top-level .md
        candidates = ["SKILL.md", "skill.md"]
        chosen = None
        for cand in candidates:
            p = os.path.join(skill_dir, cand)
            if os.path.isfile(p):
                chosen = p
                break
        if chosen is None:
            try:
                mds = [f for f in os.listdir(skill_dir) if f.endswith(".md")]
            except OSError:
                mds = []
            if mds:
                chosen = os.path.join(skill_dir, sorted(mds)[0])
        if chosen is None:
            continue
        text = _read_text(chosen)
        if text is None:
            continue
        sources.append({
            "type": "skill",
            "name": name,
            "path": chosen,
            "tokens": estimate_tokens(text),
            "last_modified": _iso_mtime(chosen),
        })
    return sources


def _scan_mcps() -> List[Dict[str, Any]]:
    """First MCP config file found wins; we collect server entries from it."""
    import json
    sources = []
    chosen_config = None
    servers_map: Dict[str, Any] = {}
    for cfg in MCP_CONFIG_CANDIDATES:
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            _warn(f"could not parse {cfg}: {e}")
            continue
        # ~/.claude.json uses "mcpServers"; ~/.claude/.mcp.json uses "servers";
        # ~/.claude/settings.json uses "mcpServers". Prefer non-empty.
        candidate = data.get("mcpServers") or data.get("servers") or {}
        if candidate:
            chosen_config = cfg
            servers_map = candidate
            break
    if not servers_map:
        return sources
    for name in sorted(servers_map.keys()):
        sources.append({
            "type": "mcp",
            "name": name,
            "path": chosen_config,
            "tokens": MCP_FIXED_TOKEN_ESTIMATE,
            "last_modified": _iso_mtime(chosen_config) if chosen_config else "",
        })
    return sources


def _scan_claudemds() -> List[Dict[str, Any]]:
    sources = []
    # Global
    if os.path.isfile(GLOBAL_CLAUDEMD):
        text = _read_text(GLOBAL_CLAUDEMD)
        if text is not None:
            sources.append({
                "type": "claudemd",
                "name": "~/.claude/CLAUDE.md",
                "path": GLOBAL_CLAUDEMD,
                "tokens": estimate_tokens(text),
                "last_modified": _iso_mtime(GLOBAL_CLAUDEMD),
            })
    # Per-project CLAUDE.md under ~/.claude/projects/*
    if os.path.isdir(PROJECTS_DIR):
        try:
            for entry in sorted(os.listdir(PROJECTS_DIR)):
                proj = os.path.join(PROJECTS_DIR, entry)
                if not os.path.isdir(proj):
                    continue
                cmd = os.path.join(proj, "CLAUDE.md")
                if not os.path.isfile(cmd):
                    continue
                text = _read_text(cmd)
                if text is None:
                    continue
                sources.append({
                    "type": "claudemd",
                    "name": entry + "/CLAUDE.md",
                    "path": cmd,
                    "tokens": estimate_tokens(text),
                    "last_modified": _iso_mtime(cmd),
                })
        except OSError as e:
            _warn(f"could not walk {PROJECTS_DIR}: {e}")
    return sources


def scan_baseline() -> Dict[str, Any]:
    """Scan all context overhead sources and return a structured snapshot.

    Returns:
        {
          "timestamp": ISO-8601 str,
          "total_tokens": int,
          "sources": [ {type, name, path, tokens, last_modified}, ... ]
        }

    Never raises. Unreadable sources are skipped with a stderr warning.
    """
    sources: List[Dict[str, Any]] = []
    sources.extend(_scan_agents())
    sources.extend(_scan_skills())
    sources.extend(_scan_mcps())
    sources.extend(_scan_claudemds())
    total = sum(int(s.get("tokens") or 0) for s in sources)
    return {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_tokens": total,
        "sources": sources,
    }


if __name__ == "__main__":
    snap = scan_baseline()
    print(f"baseline: {snap['total_tokens']} tokens across {len(snap['sources'])} sources")
    print(f"tiktoken: {'yes' if TIKTOKEN_AVAILABLE else 'no (char approx)'}")
    by_type: Dict[str, int] = {}
    for s in snap["sources"]:
        by_type[s["type"]] = by_type.get(s["type"], 0) + s["tokens"]
    for t, tok in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {t:10s} {tok:>8d} tokens")
