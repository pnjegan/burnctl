"""burnctl subagent-audit — subagent cost attribution + chain-depth detection.

Adaptation note: the `subagent_count` column on sessions is unpopulated
(always 0) on this scanner version, so we derive chain depth from the
actual rows by GROUPing on parent_session_id. is_subagent IS populated
(~52% of rows on real DBs) and drives the cost split.
"""
import os
import sqlite3


def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def run_subagent_audit(days=30):
    print(f"\nburnctl subagent-audit  (last {days} days)")
    print("=" * 58)

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return

    cur = conn.cursor()
    cutoff = f"strftime('%s', 'now', '-{int(days)} days')"

    # Overall split
    cur.execute(f"""
        SELECT
          SUM(CASE WHEN is_subagent=0 OR is_subagent IS NULL THEN cost_usd ELSE 0 END),
          SUM(CASE WHEN is_subagent=1 THEN cost_usd ELSE 0 END),
          COUNT(DISTINCT CASE WHEN is_subagent=0 OR is_subagent IS NULL THEN session_id END),
          COUNT(DISTINCT CASE WHEN is_subagent=1 THEN session_id END),
          SUM(cost_usd)
        FROM sessions
        WHERE timestamp >= {cutoff}
    """)
    main_cost, sub_cost, main_sess, sub_sess, total = cur.fetchone()
    main_cost = main_cost or 0
    sub_cost = sub_cost or 0
    total = total or 0

    if total == 0:
        print(f"No cost data in last {days} days.  Try: burnctl subagent-audit 90")
        conn.close()
        return

    sub_pct = sub_cost / total * 100 if total else 0
    print()
    print("Overall split:")
    print(f"  Main agent:  ${main_cost:.4f}  ({main_sess or 0} sessions)")
    print(f"  Subagents:   ${sub_cost:.4f}  ({sub_sess or 0} sessions) — {sub_pct:.1f}% of total")
    print(f"  Total:       ${total:.4f}")
    if sub_pct > 40:
        print(f"\n  ⚠️  Subagents consume {sub_pct:.0f}% of budget — review chain depths below.")
    elif sub_pct > 20:
        print(f"\n  🟡 Subagents at {sub_pct:.0f}% of budget — worth monitoring.")
    else:
        print(f"\n  ✓  Subagent spend looks proportional.")

    # Per-project breakdown (uses is_subagent only)
    cur.execute(f"""
        SELECT
          project,
          SUM(CASE WHEN is_subagent=1 THEN cost_usd ELSE 0 END) AS sub_cost,
          SUM(cost_usd) AS proj_total,
          COUNT(DISTINCT CASE WHEN is_subagent=1 THEN session_id END) AS sub_sess,
          SUM(CASE WHEN is_subagent=1 THEN input_tokens+output_tokens ELSE 0 END) AS sub_tokens
        FROM sessions
        WHERE timestamp >= {cutoff}
        GROUP BY project
        HAVING sub_cost > 0
        ORDER BY sub_cost DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    if rows:
        print()
        print("Per-project subagent breakdown:")
        for proj, sc, pt, ss, st in rows:
            pct = (sc / pt * 100) if pt else 0
            icon = "🔴" if pct > 50 else "🟡" if pct > 25 else "🟢"
            print(f"\n  {icon} {proj or 'unknown'}")
            print(f"     Subagent cost: ${sc:.4f}  ({pct:.0f}% of project total)")
            print(f"     Subagent sessions: {ss}  |  Tokens: {int(st or 0):,}")

    # Chain depth: derive from parent_session_id (subagent_count column is dead)
    cur.execute(f"""
        SELECT
          parent_session_id,
          COUNT(DISTINCT session_id) AS chain_depth,
          SUM(cost_usd) AS chain_cost,
          MAX(project) AS proj
        FROM sessions
        WHERE is_subagent=1
          AND parent_session_id IS NOT NULL
          AND timestamp >= {cutoff}
        GROUP BY parent_session_id
        HAVING chain_depth > 3
        ORDER BY chain_depth DESC
        LIMIT 10
    """)
    chains = cur.fetchall()
    if chains:
        print()
        print("🔴 Deep subagent chains (>3 distinct subagents per parent):")
        for parent, depth, cost, proj in chains:
            short_parent = (parent or "?")[:12]
            print(f"  parent={short_parent}…  depth={depth}  cost=${cost:.4f}  ({proj or 'unknown'})")
    else:
        print()
        print("✓ No deep subagent chains (>3 subagents per parent) detected.")

    conn.close()
    print()
    print("=" * 58)
    print("💡 Investigation tips for high subagent cost:")
    print("  1. Agentic loops spawning subagents on every iteration")
    print("  2. Workflows running without per-session limits")
    print("  3. Chain-depth >3 often indicates runaway recursion")
    print()


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_subagent_audit(days)
