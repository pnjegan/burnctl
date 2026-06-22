#!/usr/bin/env python3
"""G5 enforcement gate — fail if a claude.ai credential-movement string
reappears in a production code path.

SELF-CONTAINED BY DESIGN. The prod-scope rules and the scope-out allowlist
are inlined below. This gate never reads AUDIT.md (or any other doc) at
runtime, so it keeps working if that file is deleted. AUDIT.md was consulted
once, at authoring time, only to enumerate the legitimate occurrences that
the allowlist exempts.

Banned families (case-insensitive) — the harness E-banned rule
("no sessionKey / Cookie: / claude.ai/api/* in prod paths"), matched
defensively so a reintroduction in any realistic form is caught:

    session[_-]?key   the browser cookie name AND the DB column that a
                      writer must never repopulate (audit risk #1)
    Cookie:           an outbound Cookie header (credential transmission)
    claude.ai/api     the undocumented consumer endpoint (credential use)

Scope-outs (inlined allowlist — legitimate, defensive uses):
  * paths:    ARCHIVE/, tests/, tools/legacy/, docs/, *.md, this file
  * comments + docstrings + triple-quoted blocks (schema DDL, multi-line SQL)
  * db.py NULL-wipe machinery: _migrate_wipe_session_keys, the
    `session_key TEXT` column def, `SET session_key = NULL`, the seed-as-NULL
    insert, clear_claude_ai_session()
  * server.py _handle_sync reject-guard set + the response-scrubbing pop()

This SUPERSEDES tests/test_cmd_init_two_tier.py::test_no_consumer_endpoint_in_source
(which checked only cli.py for "claude.ai/api/account"): it scans the whole
prod tree for all three families.

Exit 0 = clean. Exit 1 = at least one violation (printed to stderr).
Importable: `scan_violations()` returns a list of (relpath, lineno, label, line).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

SCAN_SUFFIXES = (".py", ".js", ".html")

# Prod scope. The file list comes from git (tracked + new-but-not-ignored),
# so anything in .gitignore — local pre-change backups/ snapshots, data/,
# .env, node_modules — is out of scope automatically (not prod, not shipped).
# ARCHIVE/ and tests/ ARE tracked, so they need the explicit prefix exclusion
# below. PRUNE_DIRS only applies to the os.walk fallback used when git is
# unavailable.
PRUNE_DIRS = {".git", "node_modules", "data", "ARCHIVE", "tests", "backups"}
EXCLUDE_PREFIXES = ("ARCHIVE/", "tests/", "tools/legacy/", "docs/",
                    "node_modules/", "data/", "backups/")
EXCLUDE_FILES = {"tools/check_banned_strings.py", "burnctl_test_runner.py"}

BANNED = (
    ("session-key", re.compile(r"session[_-]?key", re.I)),
    ("cookie-header", re.compile(r"cookie[\"']?\s*[:=]", re.I)),
    ("consumer-endpoint", re.compile(r"claude\.ai/api", re.I)),
)

# A flagged line (after comment/docstring blanking) is exempt if it matches
# any of these legitimate-defensive patterns.
ALLOW = tuple(re.compile(p, re.I) for p in (
    r"session[_-]?key\s+TEXT",                          # schema column def
    r"SET\s+session_key\s*=\s*NULL",                    # NULL-wipe write
    r"session_key\s*=\s*NULL",                          # clear_claude_ai_session
    r"session_key\s+IS\s+(NOT\s+)?NULL",                # wipe verify / guard
    r"_migrate_wipe_session_keys",                      # wipe routine (def+call)
    r"wipe.{0,40}session_key|session_key.{0,40}wipe",   # wipe log/err strings
    r"""\bpop\(\s*["']session_key["']""",               # scrub from API response
    r"forbidden\s*=\s*\{",                              # _handle_sync reject set
    r",\s*session_key,\s*plan",                         # seed-as-NULL insert cols
))


def _blank(m):
    """Replace a matched span with spaces, preserving newlines (so line
    numbers and column structure are unchanged)."""
    return re.sub(r"[^\n]", " ", m.group(0))


def code_view(text, suffix):
    """Return `text` with comments and (for .py) docstrings / triple-quoted
    blocks blanked out, line structure preserved. Single/double-quoted string
    literals are LEFT INTACT so real credential movement (cookie headers,
    URLs) is still scanned."""
    if suffix == ".py":
        text = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', _blank, text)
        text = re.sub(r'#[^\n]*', _blank, text)
    elif suffix == ".js":
        text = re.sub(r'/\*[\s\S]*?\*/', _blank, text)
        text = re.sub(r'//[^\n]*', _blank, text)
    elif suffix == ".html":
        text = re.sub(r'<!--[\s\S]*?-->', _blank, text)
    return text


def _git_files(root):
    """Tracked + untracked-but-not-ignored files, honoring .gitignore.
    Returns None if git is unavailable (caller falls back to os.walk)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=str(root), capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return [ln for ln in out.stdout.splitlines() if ln]
    except (OSError, subprocess.SubprocessError):
        return None


def _walk_files(root):
    """Fallback enumeration when git is unavailable."""
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in PRUNE_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            rels.append(p.relative_to(root).as_posix())
    return rels


def iter_prod_files(root=None):
    root = Path(root) if root else REPO_DIR
    rels = _git_files(root)
    if rels is None:
        rels = _walk_files(root)
    for rel in rels:
        p = root / rel
        if p.suffix not in SCAN_SUFFIXES:
            continue
        if rel in EXCLUDE_FILES:
            continue
        if any(rel.startswith(x) for x in EXCLUDE_PREFIXES):
            continue
        if not p.is_file():
            continue
        yield p, rel


def scan_violations(root=None):
    """Scan prod paths; return [(relpath, lineno, label, stripped_line), ...]."""
    violations = []
    for p, rel in iter_prod_files(root):
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(code_view(raw, p.suffix).splitlines(), 1):
            for label, pat in BANNED:
                if pat.search(line):
                    if any(a.search(line) for a in ALLOW):
                        continue
                    violations.append((rel, i, label, line.strip()))
                    break
    return violations


def main(argv=None):
    root = None
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        root = argv[0]
    violations = scan_violations(root)
    if not violations:
        print("G5 banned-string gate: PASS — 0 violations in prod paths "
              "(sessionKey / Cookie: / claude.ai/api)")
        return 0
    print(f"G5 banned-string gate: FAIL — {len(violations)} violation(s) "
          f"in prod paths:", file=sys.stderr)
    for rel, ln, label, text in violations:
        print(f"  {rel}:{ln}: [{label}] {text}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
