"""burnctl version-check — flag known-bad Claude Code versions.

Bad range: 2.1.x where 69 <= patch <= 89.
  - v2.1.69 introduced the cache regression — anthropics/claude-code issue #34629
  - v2.1.88 — token-count regression confirmed — issue #38335
  - v2.1.89 — --resume cache invalidation — issue #42749
  - v2.1.90+ — regression resolved (recommend v2.1.91+ for safety)

Additional critical points:
  - v2.1.118 — CRITICAL, three confirmed regressions (skip entirely):
      (1) Bash tool silently deletes hooks/, HEAD, objects, refs, config at
          project root — data loss, syscall-trace confirmed (issue #52578,
          NOT fixed in 2.1.119).
      (2) /usage broken for Team accounts (issue #52345).
      (3) 401 auth error with custom ANTHROPIC_BASE_URL / third-party
          providers (issue #52307).
  - v2.1.119 — WARNING, carries unfixed #52578 from 2.1.118 (project-root
    file deletion on Bash calls). Upgrade when patched.

Cross-checked via community analysis from cnighswonger/claude-code-cache-fix
and ArkNill/claude-code-hidden-problem-analysis.

Pure stdlib. No DB read. Safe to run anywhere.
"""

import os
import re
import subprocess


CACHE_FIX_PATHS = [
    "~/.claude/cache-fix-interceptor.js",
    "~/.claude/interceptor.js",
]
CACHE_FIX_REPO = "https://github.com/cnighswonger/claude-code-cache-fix"
SAFE_VERSION = "2.1.91"


def get_claude_version():
    """Best-effort detection — try local binary first, then npx fallback."""
    methods = [
        ["claude", "--version"],
        ["npx", "--no-install", "@anthropic-ai/claude-code", "--version"],
    ]
    for cmd in methods:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            text = (r.stdout or "") + (r.stderr or "")
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
            if m:
                return m.group(0), " ".join(cmd[:2])
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return None, None


def is_bad_version(version_str):
    """Range check for the cache-regression window. Returns (bool, reason_or_None).

    Kept at 2-tuple for backwards-compat with any external callers. Use
    classify_version() for severity-aware output.
    """
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not m:
        return False, None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if major == 2 and minor == 1 and 69 <= patch <= 89:
        return True, "cache regression — see GitHub issues #34629 / #38335 / #42749"
    return False, None


def classify_version(version_str):
    """Return (severity, short_reason) where severity is one of
    'critical' | 'warning' | None (clean).

    Kept separate from is_bad_version so existing callers are undisturbed.
    """
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not m:
        return None, None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if major == 2 and minor == 1 and 69 <= patch <= 89:
        return "critical", "cache regression (issues #34629 / #38335 / #42749)"
    if major == 2 and minor == 1 and patch == 118:
        return "critical", "3 confirmed regressions incl. project-root data loss (#52578)"
    if major == 2 and minor == 1 and patch == 119:
        return "warning", "#52578 data-loss regression inherited from 2.1.118, NOT YET FIXED"
    return None, None


def check_cache_fix_installed():
    """Is the community cache-fix interceptor present?"""
    for p in CACHE_FIX_PATHS:
        if os.path.exists(os.path.expanduser(p)):
            return True, p
    if os.environ.get("CLAUDE_CODE_INTERCEPTOR"):
        return True, "env:CLAUDE_CODE_INTERCEPTOR"
    return False, None


def run_version_check():
    print()
    print("burnctl version-check")
    print("=" * 50)

    # 1. Claude Code version
    version, source = get_claude_version()
    bad = False
    severity = None
    if version:
        print()
        print(f"Claude Code version: {version}  (via `{source}`)")
        severity, short_reason = classify_version(version)
        bad = severity == "critical"
        if version == "2.1.118":
            print(f"🔴 CRITICAL — SKIP THIS VERSION")
            print(f"   Three confirmed regressions in 2.1.118:")
            print(f"     (1) Bash tool silently deletes hooks/, HEAD, objects, refs, config")
            print(f"         at project root on every call — data loss, syscall-trace")
            print(f"         confirmed (issue #52578, NOT fixed in 2.1.119).")
            print(f"         Rename any of these at your project root before upgrading.")
            print(f"     (2) /usage broken for Team accounts (issue #52345).")
            print(f"     (3) 401 auth error with custom ANTHROPIC_BASE_URL /")
            print(f"         third-party providers (issue #52307).")
            print(f"   → Downgrade to v2.1.117 or upgrade directly to v2.1.119+.")
            print(f"   → Pin with DISABLE_UPDATES=1 to prevent auto-upgrade.")
        elif version == "2.1.119":
            print(f"⚠  WARNING — v2.1.119 carries unfixed data-loss from 2.1.118")
            print(f"   Issue #52578 (Bash tool call deletes project-root files:")
            print(f"   hooks/, HEAD, objects, refs, config) NOT YET FIXED.")
            print(f"   If your project root has any of these names, rename them")
            print(f"   before running Bash tool calls.")
            print(f"   Monitor https://github.com/anthropics/claude-code/issues/52578")
        elif severity == "critical":
            print(f"🔴 KNOWN BAD: {short_reason}")
            print(f"   Cache costs in this range can run 10-20x normal.")
            print(f"   Fix: npm update -g @anthropic-ai/claude-code  (target v{SAFE_VERSION}+)")
        elif severity == "warning":
            print(f"⚠  WARNING: {short_reason}")
        else:
            print(f"✓ No known critical/warning flags for this version")
    else:
        print()
        print("⚠️  Could not detect Claude Code version")
        print("   Try: claude --version")
        print("        npx @anthropic-ai/claude-code --version")

    # 2. Cache-fix interceptor — only surface the nudge if the user is on a
    # bad version or we couldn't detect the version at all. On a clean
    # version, mentioning the interceptor just confuses users into thinking
    # they're missing a required component.
    installed, path = check_cache_fix_installed()
    if installed:
        print()
        print(f"✓ Cache-fix interceptor detected: {path}")
        print(f"  Community fix for the --resume cache-bust is active.")
    elif bad or not version:
        print()
        print(f"ℹ  Cache-fix interceptor NOT installed")
        print(f"   Recommended on bad versions:")
        print(f"   {CACHE_FIX_REPO}")

    # 3. Quick reminders
    print()
    print("Reminders:")
    print("  • Avoid --resume — it can trigger a full context rebuild")
    print("  • Use /clear to start a fresh session instead")
    print("  • Run `burnctl resume-audit` to size up past damage")
    print()


if __name__ == "__main__":
    run_version_check()
