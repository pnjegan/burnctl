"""burnctl version-check — flag known-bad Claude Code versions.

Bad range: 2.1.x where 69 <= patch <= 89.
  - v2.1.69 introduced the cache regression — anthropics/claude-code issue #34629
  - v2.1.88 — token-count regression confirmed — issue #38335
  - v2.1.89 — --resume cache invalidation — issue #42749
  - v2.1.90+ — regression resolved (recommend v2.1.91+ for safety)

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
    """Range check for the cache-regression window. Returns (bool, reason_or_None)."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not m:
        return False, None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if major == 2 and minor == 1 and 69 <= patch <= 89:
        return True, "cache regression — see GitHub issues #34629 / #38335 / #42749"
    return False, None


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
    if version:
        print()
        print(f"Claude Code version: {version}  (via `{source}`)")
        bad, reason = is_bad_version(version)
        if bad:
            print(f"🔴 KNOWN BAD: {reason}")
            print(f"   Cache costs in this range can run 10-20x normal.")
            print(f"   Fix: npm update -g @anthropic-ai/claude-code  (target v{SAFE_VERSION}+)")
        else:
            print(f"✓ Not in known-bad range (2.1.69 – 2.1.89)")
    else:
        print()
        print("⚠️  Could not detect Claude Code version")
        print("   Try: claude --version")
        print("        npx @anthropic-ai/claude-code --version")

    # 2. Cache-fix interceptor
    print()
    installed, path = check_cache_fix_installed()
    if installed:
        print(f"✓ Cache-fix interceptor detected: {path}")
        print(f"  Community fix for the --resume cache-bust is active.")
    else:
        print(f"ℹ  Cache-fix interceptor NOT installed")
        print(f"   For users on bad versions or affected by --resume cache-bust:")
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
