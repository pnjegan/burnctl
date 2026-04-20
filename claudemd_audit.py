"""burnctl claudemd-audit — find dead rules in CLAUDE.md files.

For each rule discovered in ~/.claude/CLAUDE.md (and any project CLAUDE.md
files), check the last 30 days of waste_events. Rules whose associated
waste pattern has ZERO recent events are dead weight — they consume tokens
on every session startup but aren't earning their cost.

Heuristic: we group CLAUDE.md bullet lines into rule blocks, classify each
by the waste pattern keywords it mentions (retry, cache, compact, read,
flounder, etc.), then look up matching waste_events rows.

This does not parse CLAUDE.md semantically — it matches on keywords. A
rule with novel language that no waste pattern maps to will show up as
"unclassified" (not dead, just unknown).
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path


TOKENS_PER_CHAR = 0.25  # rough tiktoken estimate: ~4 chars/token
LOOKBACK_DAYS = 30


# ─────────────────────────────────────────────────────────
# Rule classification — map CLAUDE.md rule text to waste patterns
# ─────────────────────────────────────────────────────────

PATTERN_KEYWORDS = {
    "retry_error": [
        r"\bretry",
        r"\bretries?\b",
        r"tool.{0,10}fail",
    ],
    "dead_end": [
        r"dead.?end",
        r"stuck",
        r"3 consecutive fail",
        r"ask.{0,10}for guidance",
    ],
    "repeated_reads": [
        r"re.?read",
        r"repeated.{0,10}read",
        r"read.{0,10}same file",
        r"cache.{0,10}the read",
    ],
    "floundering": [
        r"flounder",
        r"multiple approaches",
        r"stop.{0,10}report",
    ],
    "oververbose_tool": [
        r"verbose.{0,10}output",
        r"head.{0,10}tail",
        r"pipe.{0,10}grep",
        r"large.{0,10}output",
        r"50KB",
    ],
    "browser_wall": [
        r"cloudflare",
        r"403",
        r"blocked.{0,10}URL",
        r"web.?fetch",
    ],
    "deep_no_compact": [
        r"compact",
        r"autoCompact",
        r"context.{0,10}rebuild",
        r"/clear\b",
    ],
    "cost_outlier": [
        r"cost.{0,10}outlier",
        r"file size limit",
        r"row limit",
    ],
}


# ─────────────────────────────────────────────────────────
# CLAUDE.md discovery + rule extraction
# ─────────────────────────────────────────────────────────

def discover_claude_md_files():
    """Return list of (label, path) for every CLAUDE.md worth auditing."""
    paths = []
    user_claude = Path.home() / ".claude" / "CLAUDE.md"
    if user_claude.exists():
        paths.append(("user", user_claude))
    # Project CLAUDE.md files for projects with waste_events
    for p in sorted(Path.home().glob(".claude/projects/*/CLAUDE.md"))[:5]:
        paths.append((f"project:{p.parent.name}", p))
    # Current repo CLAUDE.md if present
    cwd_claude = Path.cwd() / "CLAUDE.md"
    if cwd_claude.exists() and cwd_claude not in [p for _, p in paths]:
        paths.append(("repo", cwd_claude))
    return paths


def extract_rules(text):
    """Split CLAUDE.md text into coarse 'rules' — bullet/numbered/section blocks.

    Each rule is a dict: {line_num, text, tokens}.
    """
    rules = []
    current = None
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # new rule boundary: bullet, number, or heading
        if re.match(r"^(-|\*|\d+\.|#{2,4}\s)", stripped):
            if current:
                rules.append(current)
            current = {"line_num": i, "text": stripped, "tokens": 0}
        elif current is not None and stripped:
            current["text"] += " " + stripped
    if current:
        rules.append(current)
    # estimate tokens per rule
    for r in rules:
        r["tokens"] = max(1, int(len(r["text"]) * TOKENS_PER_CHAR))
    # filter: drop pure headings and very short rules
    return [r for r in rules if len(r["text"]) > 25 and not r["text"].startswith("#")]


def classify_rule(rule_text):
    """Return list of pattern_types this rule seems to target. May be empty."""
    text = rule_text.lower()
    matches = []
    for pattern, keywords in PATTERN_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, text, re.IGNORECASE):
                matches.append(pattern)
                break
    return matches


# ─────────────────────────────────────────────────────────
# DB lookups
# ─────────────────────────────────────────────────────────

def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def pattern_match_stats(conn, days=LOOKBACK_DAYS):
    """For each pattern_type, return (match_count, sum_token_cost) in last N days."""
    since = int(time.time()) - days * 86400
    cur = conn.cursor()
    cur.execute(
        "SELECT pattern_type, COUNT(*), COALESCE(SUM(token_cost), 0) "
        "FROM waste_events WHERE detected_at >= ? GROUP BY pattern_type",
        (since,),
    )
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def session_count_30d(conn, days=LOOKBACK_DAYS):
    since = int(time.time()) - days * 86400
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(DISTINCT session_id) FROM sessions "
        "WHERE timestamp >= ? AND is_subagent = 0",
        (since,),
    )
    return cur.fetchone()[0] or 0


# ─────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────

def run_claudemd_audit():
    print()
    print("burnctl claudemd-audit")
    print("=" * 64)

    claude_files = discover_claude_md_files()
    if not claude_files:
        print("No CLAUDE.md files found to audit.")
        print("Expected: ~/.claude/CLAUDE.md or ./CLAUDE.md")
        return

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return

    match_stats = pattern_match_stats(conn, LOOKBACK_DAYS)
    sess_count = session_count_30d(conn, LOOKBACK_DAYS)
    conn.close()

    total_active_tokens = 0
    total_dead_tokens = 0
    total_unclassified_tokens = 0

    for label, path in claude_files:
        text = path.read_text()
        rules = extract_rules(text)
        total_chars = len(text)
        total_tokens_file = int(total_chars * TOKENS_PER_CHAR)

        print()
        print(f"{label} — {path}")
        print(f"  File size: {total_chars:,} chars (~{total_tokens_file:,} tokens est)")
        print(f"  Rules extracted: {len(rules)}")
        print()

        active, dead, unclassified = [], [], []
        for r in rules:
            patterns = classify_rule(r["text"])
            if not patterns:
                unclassified.append((r, None, 0, 0.0))
                continue
            # best-match pattern (first one)
            best = max(patterns, key=lambda p: match_stats.get(p, (0, 0))[0])
            n, cost = match_stats.get(best, (0, 0))
            if n > 0:
                active.append((r, best, n, cost))
            else:
                dead.append((r, best, n, cost))

        if active:
            print("  ACTIVE rules (matched waste events in last 30d):")
            for r, pat, n, cost in active[:10]:
                preview = r["text"][:60].replace("\n", " ")
                print(f"    [OK] {pat:<20} — {n} matches, ~${cost:,.0f} est  ({r['tokens']} tok)")
                print(f"         {preview}...")
                total_active_tokens += r["tokens"]

        if dead:
            print()
            print("  DEAD rules (zero matches in last 30d — dead weight):")
            for r, pat, _n, _c in dead[:10]:
                preview = r["text"][:60].replace("\n", " ")
                print(f"    [DEAD] {pat:<18} — 0 matches  (~{r['tokens']} tok/session wasted)")
                print(f"           {preview}...")
                total_dead_tokens += r["tokens"]

        if unclassified:
            uncl_tokens = sum(r["tokens"] for r, *_ in unclassified)
            total_unclassified_tokens += uncl_tokens
            print()
            print(f"  UNCLASSIFIED: {len(unclassified)} rule(s) "
                  f"(~{uncl_tokens} tok) — domain-specific content beyond waste patterns")

    print()
    print("=" * 64)
    print(f"Dead-rule overhead across files: ~{total_dead_tokens:,} tokens/session")
    if sess_count > 0:
        monthly_wasted = total_dead_tokens * sess_count
        print(f"At {sess_count} non-subagent sessions/30d: "
              f"~{monthly_wasted:,} tokens/mo")
        # rough cost — Sonnet input pricing $3/MTok as mid-band
        monthly_cost_usd = monthly_wasted * 3.0 / 1_000_000
        print(f"~${monthly_cost_usd:.2f}/mo wasted on dead-weight CLAUDE.md rules")
    print()
    print("Recommendation: move dead rules to a CLAUDE.md.archive file")
    print("so the context budget goes to rules that actually catch waste.")
    print()


if __name__ == "__main__":
    run_claudemd_audit()
