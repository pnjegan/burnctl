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

# v4.5.3 E-01: the canonical Claude Code session-log dir (PROJECTS_DIR
# above) does NOT contain real repo CLAUDE.md files — only JSONL logs.
# These defaults scan common checked-out-repo locations for project-level
# CLAUDE.md. Override via BURNCTL_PROJECT_ROOTS=/path/one:/path/two.
_DEFAULT_PROJECT_PARENTS = [
    os.path.join(HOME, "projects"),
    os.path.join(HOME, "code"),
    os.path.join(HOME, "dev"),
    os.path.join(HOME, "src"),
    os.path.join(HOME, "work"),
]

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


def _already_seen(path: str, seen: set) -> bool:
    """v4.5.3 N-2 symlink cycle guard. Returns True if `path` (resolved via
    os.path.realpath) has already been processed in the current scan.
    On first-seen, records it and returns False.

    Guards all three scan loops (agents, skills, CLAUDE.md walk) against
    circular symlinks. Confirmed ~5 symlinks in ~/.claude/skills/ — cheap
    insurance against a future self-referential one.
    """
    try:
        real = os.path.realpath(path)
    except OSError:
        return False  # best-effort — let caller process; failure will surface elsewhere
    if real in seen:
        _warn(f"symlink cycle: {path} already visited (realpath={real}), skipping")
        return True
    seen.add(real)
    return False


def _discover_project_roots() -> List[str]:
    """v4.5.3 E-01. Return a deduplicated list of directories that are likely
    to contain real project CLAUDE.md files.

    Priority order:
      1. BURNCTL_PROJECT_ROOTS env var (colon-separated) — explicit opt-in.
      2. Default parent directories under $HOME — each child dir is a
         potential project root.
    """
    roots: List[str] = []
    env_override = os.environ.get("BURNCTL_PROJECT_ROOTS", "").strip()
    if env_override:
        for p in env_override.split(":"):
            p = os.path.expanduser(p.strip())
            if p and os.path.isdir(p):
                roots.append(p)
    # Default parents: each of these is scanned one level deep (child is a project)
    for parent in _DEFAULT_PROJECT_PARENTS:
        if not os.path.isdir(parent):
            continue
        try:
            for entry in sorted(os.listdir(parent)):
                child = os.path.join(parent, entry)
                if os.path.isdir(child):
                    roots.append(child)
        except OSError as e:
            _warn(f"could not walk {parent}: {e}")
    # Deduplicate by realpath while preserving first-seen order
    seen: set = set()
    deduped: List[str] = []
    for r in roots:
        try:
            real = os.path.realpath(r)
        except OSError:
            real = r
        if real not in seen:
            seen.add(real)
            deduped.append(r)
    return deduped


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


def _scan_agents(seen: set) -> List[Dict[str, Any]]:
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
        if _already_seen(path, seen):
            continue
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


def _scan_skills(seen: set) -> List[Dict[str, Any]]:
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
        if _already_seen(skill_dir, seen):
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
        if not isinstance(data, dict):
            continue
        # ~/.claude.json uses "mcpServers"; ~/.claude/.mcp.json uses "servers";
        # ~/.claude/settings.json uses "mcpServers". Prefer non-empty.
        candidate = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(candidate, dict):
            candidate = {}
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


def _scan_claudemds(seen: set) -> List[Dict[str, Any]]:
    sources = []
    # 1. Global CLAUDE.md
    if os.path.isfile(GLOBAL_CLAUDEMD) and not _already_seen(GLOBAL_CLAUDEMD, seen):
        text = _read_text(GLOBAL_CLAUDEMD)
        if text is not None:
            sources.append({
                "type": "claudemd",
                "name": "~/.claude/CLAUDE.md",
                "path": GLOBAL_CLAUDEMD,
                "tokens": estimate_tokens(text),
                "last_modified": _iso_mtime(GLOBAL_CLAUDEMD),
            })
    # 2. Back-compat: CLAUDE.md under ~/.claude/projects/* (kept for existing
    #    installs that were relying on this path; real repos live elsewhere).
    if os.path.isdir(PROJECTS_DIR):
        try:
            for entry in sorted(os.listdir(PROJECTS_DIR)):
                proj = os.path.join(PROJECTS_DIR, entry)
                if not os.path.isdir(proj):
                    continue
                cmd = os.path.join(proj, "CLAUDE.md")
                if not os.path.isfile(cmd):
                    continue
                if _already_seen(cmd, seen):
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
    # 3. v4.5.3 E-01: scan real project roots for CLAUDE.md.
    for root in _discover_project_roots():
        cmd = os.path.join(root, "CLAUDE.md")
        if not os.path.isfile(cmd):
            continue
        if _already_seen(cmd, seen):
            continue
        text = _read_text(cmd)
        if text is None:
            continue
        # Display name: repo dir basename so UI shows e.g. "burnctl/CLAUDE.md"
        label = os.path.basename(os.path.abspath(root)) + "/CLAUDE.md"
        sources.append({
            "type": "claudemd",
            "name": label,
            "path": cmd,
            "tokens": estimate_tokens(text),
            "last_modified": _iso_mtime(cmd),
        })
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
    seen: set = set()  # realpath dedup + symlink cycle guard (N-2)
    sources.extend(_scan_agents(seen))
    sources.extend(_scan_skills(seen))
    sources.extend(_scan_mcps())  # MCP is config-file based; no path traversal
    sources.extend(_scan_claudemds(seen))
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
