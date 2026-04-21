"""burnctl overhead-audit — startup overhead per project.

Adaptation note: `input_tokens` on the first DB row of each session is
2-6 tokens (essentially nothing — it's a metadata/permission row, not
the system prompt). Real overhead is captured in `cache_creation_tokens`:
the first time a session caches the system prompt + CLAUDE.md + tools +
MCP definitions, that all goes into cache_creation_tokens. We use
MAX(cache_creation_tokens) per session_id as the overhead proxy.

Reference for what's IN the overhead:
  Tara Prasad Routray, Medium, Apr 2026 — 35-40K tokens of CLAUDE.md
    + plugin overhead before first user message.
  GitHub anthropics/claude-code issue #29971 — 25K tokens per tool call
    from MCP skill injection.
"""
import os
import sqlite3


# Sonnet input-cache-write pricing for the cost rough-estimate.
# Real cache-creation pricing varies by model; this is a reasonable mid-band.
INPUT_PRICE_PER_TOKEN = 3.0 / 1_000_000


def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def run_overhead_audit(days=30):
    print(f"\nburnctl overhead-audit  (last {days} days)")
    print("=" * 58)
    print("Overhead measured via MAX(cache_creation_tokens) per session_id —")
    print("the largest cached chunk per session, which is the real CLAUDE.md +")
    print("tool definitions + MCP overhead injected at session start.\n")

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return

    cur = conn.cursor()
    cutoff = f"strftime('%s', 'now', '-{int(days)} days')"

    # One overhead value per session: MAX cache_creation_tokens
    cur.execute(f"""
        WITH per_session AS (
          SELECT session_id,
                 COALESCE(NULLIF(TRIM(inferred_project), ''), project) AS project,
                 MAX(cache_creation_tokens) AS overhead_tokens
          FROM sessions
          WHERE timestamp >= {cutoff}
            AND (is_subagent = 0 OR is_subagent IS NULL)
          GROUP BY session_id
          HAVING overhead_tokens > 1000
        )
        SELECT AVG(overhead_tokens),
               MIN(overhead_tokens),
               MAX(overhead_tokens),
               COUNT(*),
               SUM(overhead_tokens)
        FROM per_session
    """)
    avg_oh, min_oh, max_oh, sampled, total_oh = cur.fetchone()
    if not sampled:
        print(f"Not enough cached-session data in last {days} days.")
        print("Try: burnctl overhead-audit 90")
        conn.close()
        return

    avg_oh = int(avg_oh or 0)
    total_oh = int(total_oh or 0)
    cost_estimate = total_oh * INPUT_PRICE_PER_TOKEN

    print("Session startup overhead:")
    print(f"  Average:  {avg_oh:,} tokens per session")
    print(f"  Range:    {int(min_oh):,} – {int(max_oh):,} tokens")
    print(f"  Sampled:  {sampled} sessions")

    if avg_oh > 40000:
        print(f"\n  🔴 HIGH: {avg_oh:,} tokens cached before first user message.")
        print(f"     Trim CLAUDE.md, disable unused MCP servers + skills.")
    elif avg_oh > 20000:
        print(f"\n  🟡 MODERATE: {avg_oh:,} tokens at session start — room to trim.")
    else:
        print(f"\n  ✓  Reasonable ({avg_oh:,} tokens avg).")

    print(f"\n  Total overhead tokens this period: {total_oh:,}")
    print(f"  Estimated cost (Sonnet write-pricing): ${cost_estimate:.4f}")

    # Per-project breakdown
    cur.execute(f"""
        WITH per_session AS (
          SELECT session_id,
                 COALESCE(NULLIF(TRIM(inferred_project), ''), project) AS project,
                 MAX(cache_creation_tokens) AS overhead_tokens
          FROM sessions
          WHERE timestamp >= {cutoff}
            AND (is_subagent = 0 OR is_subagent IS NULL)
          GROUP BY session_id
          HAVING overhead_tokens > 1000
        )
        SELECT project,
               AVG(overhead_tokens) AS avg_oh,
               COUNT(*) AS sessions,
               SUM(overhead_tokens) AS total_oh
        FROM per_session
        GROUP BY project
        ORDER BY avg_oh DESC
        LIMIT 10
    """)
    proj_rows = cur.fetchall()
    if proj_rows:
        print()
        print("Per-project startup overhead:")
        for proj, p_avg, p_sess, p_total in proj_rows:
            icon = "🔴" if p_avg > 40000 else "🟡" if p_avg > 20000 else "🟢"
            print(f"  {icon} {(proj or 'unknown'):<20} "
                  f"{int(p_avg):>10,} avg tokens  ({p_sess} sessions)")

    # Trend (weekly)
    cur.execute(f"""
        WITH per_session AS (
          SELECT session_id,
                 strftime('%Y-%W', datetime(MIN(timestamp), 'unixepoch')) AS week,
                 MAX(cache_creation_tokens) AS overhead_tokens
          FROM sessions
          WHERE timestamp >= {cutoff}
            AND (is_subagent = 0 OR is_subagent IS NULL)
          GROUP BY session_id
          HAVING overhead_tokens > 1000
        )
        SELECT week, AVG(overhead_tokens), COUNT(*)
        FROM per_session
        GROUP BY week
        ORDER BY week
    """)
    trend = cur.fetchall()
    if len(trend) >= 3:
        print()
        print(f"Overhead trend ({len(trend)} weeks):")
        for week, avg, n in trend:
            bar = "█" * min(int(avg / 5000), 20)
            print(f"  Week {week}: {int(avg):>8,} tokens  {bar}")
        first_avg, last_avg = trend[0][1], trend[-1][1]
        if first_avg:
            change_pct = (last_avg - first_avg) / first_avg * 100
            if change_pct > 20:
                print(f"\n  🔴 Overhead GREW {change_pct:.0f}% over this period.")
            elif change_pct < -10:
                print(f"\n  ✓  Overhead REDUCED {abs(change_pct):.0f}% — good trend.")

    conn.close()
    print()
    print("=" * 58)
    print("💡 To reduce overhead:")
    print("  1. Trim CLAUDE.md — remove prose, keep only rules")
    print("  2. Disable unused MCP servers in ~/.claude/settings.json")
    print("  3. Remove unused skills from .claude/commands/")
    print()


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_overhead_audit(days)
