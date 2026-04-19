"""burnctl variance [project] — session cost variance profiler.

Uses coefficient of variation (CV = std / mean × 100) to surface projects
where the same kind of work costs unpredictably different amounts.

Reads the sessions table from data/usage.db using the REAL schema:
  sessions(timestamp INT, project TEXT, cost_usd REAL,
           input_tokens INT, output_tokens INT,
           cache_read_tokens INT, cache_creation_tokens INT, ...)

`timestamp` is unix seconds (per scanner.py / INTERNALS.md).
`cache_creation_tokens` (NOT cache_write_tokens — never existed).
"""

import os
import math
import sqlite3
from collections import defaultdict


def load_db():
    candidates = [
        os.path.expanduser("~/projects/burnctl/data/usage.db"),
        "data/usage.db",
    ]
    for c in candidates:
        if os.path.exists(c):
            return sqlite3.connect(c)
    # Fall back to ~/.burnctl/data convention if installed via npm wrapper
    home_db = os.path.expanduser("~/.burnctl/data/usage.db")
    if os.path.exists(home_db):
        return sqlite3.connect(home_db)
    return None


def cv(values):
    """Coefficient of variation as percentage. Returns (cv_pct, mean, std)."""
    if len(values) < 2:
        return 0.0, 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return 0.0, 0.0, 0.0
    std = math.sqrt(sum((x - mean) ** 2 for x in values) / n)
    return round(std / mean * 100, 1), round(mean, 6), round(std, 6)


def get_session_stats(conn, project=None, days=60):
    """Pull per-session aggregates from the sessions table."""
    cur = conn.cursor()
    cutoff = f"strftime('%s', 'now', '-{int(days)} days')"
    try:
        if project:
            cur.execute(f"""
                SELECT
                  project,
                  session_id,
                  SUM(input_tokens)          AS inp,
                  SUM(output_tokens)         AS out,
                  SUM(cost_usd)              AS cost,
                  SUM(cache_read_tokens)     AS cache_read,
                  SUM(cache_creation_tokens) AS cache_create,
                  MIN(timestamp)             AS first_ts
                FROM sessions
                WHERE project LIKE ?
                  AND timestamp >= {cutoff}
                GROUP BY session_id
                HAVING inp > 0
                ORDER BY first_ts DESC
            """, (f"%{project}%",))
        else:
            cur.execute(f"""
                SELECT
                  project,
                  session_id,
                  SUM(input_tokens)          AS inp,
                  SUM(output_tokens)         AS out,
                  SUM(cost_usd)              AS cost,
                  SUM(cache_read_tokens)     AS cache_read,
                  SUM(cache_creation_tokens) AS cache_create,
                  MIN(timestamp)             AS first_ts
                FROM sessions
                WHERE timestamp >= {cutoff}
                GROUP BY session_id
                HAVING inp > 0
                ORDER BY first_ts DESC
            """)
        return cur.fetchall()
    except sqlite3.OperationalError as e:
        print(f"  DB error: {e}")
        try:
            row = cur.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='sessions'"
            ).fetchone()
            if row:
                print(f"  Actual schema: {row[0][:200]}")
        except Exception:
            pass
        return []


def run_variance(project=None, days=60):
    label = f"project='{project}'" if project else "all projects"
    print(f"\nburnctl variance  ({label}, last {days} days)")
    print("=" * 58)

    conn = load_db()
    if not conn:
        print("❌ No database found. Run 'burnctl scan' first.")
        return

    rows = get_session_stats(conn, project, days)
    conn.close()

    if not rows:
        print(f"No sessions found for {label} in last {days} days.")
        if project:
            print("Try: burnctl variance  (no project filter)")
        return

    by_project = defaultdict(list)
    for r in rows:
        proj = r[0] or "unknown"
        by_project[proj].append({
            "input": r[2] or 0,
            "output": r[3] or 0,
            "cost": r[4] or 0.0,
            "cache_read": r[5] or 0,
            "cache_create": r[6] or 0,
        })

    results = []
    for proj, sess in by_project.items():
        if len(sess) < 3:
            continue

        costs = [s["cost"] for s in sess if s["cost"] > 0]
        inputs = [s["input"] for s in sess if s["input"] > 0]
        if len(costs) < 3:
            continue

        cv_cost, mean_cost, _ = cv(costs)
        cv_input, mean_input, _ = cv(inputs)

        causes = []

        # Cache hit ratio: cache_read / total_processed
        cache_ratios = []
        for s in sess:
            total = s["input"] + s["cache_read"] + s["cache_create"]
            if total > 0:
                cache_ratios.append(s["cache_read"] / total)
        if len(cache_ratios) >= 3:
            cv_cache, mean_cache, _ = cv(cache_ratios)
            if cv_cache > 50:
                causes.append(
                    f"Cache hit rate varies {cv_cache:.0f}% CV "
                    f"(avg {mean_cache*100:.0f}%) — "
                    f"some sessions resume with full cache, others don't"
                )

        if cv_input > 60:
            causes.append(
                f"Starting context size varies {cv_input:.0f}% CV — "
                f"some sessions begin with much more context than others"
            )

        if cv_cost > 100 and not causes:
            causes.append(
                "Mixed session types — short and long sessions in same project"
            )

        results.append({
            "project": proj,
            "count": len(sess),
            "cv_cost": cv_cost,
            "mean_cost": mean_cost,
            "min_cost": round(min(costs), 6),
            "max_cost": round(max(costs), 6),
            "cv_input": cv_input,
            "causes": causes,
        })

    if not results:
        print("Not enough sessions per project to compute variance (need 3+).")
        print("Try a longer window: `burnctl variance <project> 90`")
        return

    results.sort(key=lambda x: x["cv_cost"], reverse=True)

    for r in results:
        icon = "🔴" if r["cv_cost"] > 100 else "🟡" if r["cv_cost"] > 50 else "🟢"
        print(f"\n{icon} {r['project']}  ({r['count']} sessions)")
        print(f"   Cost variance: {r['cv_cost']:.0f}% CV")
        print(f"   Range: ${r['min_cost']:.4f} – ${r['max_cost']:.4f}"
              f"  |  Mean: ${r['mean_cost']:.4f}")
        if r["causes"]:
            for i, c in enumerate(r["causes"]):
                prefix = "   Top cause:" if i == 0 else "             "
                print(f"{prefix} {c}")
        else:
            print("   Cause: insufficient signal to diagnose")

    print(f"\n{'=' * 58}")
    print("CV guide:  >100% 🔴 high   |   50-100% 🟡 medium   |   <50% 🟢 stable")
    print("High variance = same work costs unpredictably different amounts.")
    print()
    print("💡 Run `burnctl resume-audit` to check if cache-bust is the cause.")
    print()


if __name__ == "__main__":
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else None
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    run_variance(project, days)
