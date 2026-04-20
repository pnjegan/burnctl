"""burnctl compact-audit — compaction rate per project.

Adaptation note: the `compact_count` and `tokens_before_compact` /
`tokens_after_compact` columns are unpopulated by this scanner version,
so the "multiple compactions per session" deep-dive uses a JSONL pass
(counting `type=summary` records per session_id) instead.

`compaction_detected` IS populated and drives the per-project rate.
"""
import os
import sqlite3
import glob
import json
from collections import Counter


def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def _count_summaries_per_session():
    """JSONL pass — count `type=summary` records (compaction events)
    per session_id. ≥ 2 = session compacted more than once."""
    counts = Counter()
    base = os.path.expanduser("~/.claude/projects/")
    for fpath in glob.glob(f"{base}/**/*.jsonl", recursive=True):
        sid = os.path.basename(fpath).replace(".jsonl", "")
        try:
            with open(fpath, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if json.loads(line).get("type") == "summary":
                            counts[sid] += 1
                    except json.JSONDecodeError:
                        continue
        except (IOError, OSError):
            continue
    return counts


def run_compact_audit(days=30):
    print(f"\nburnctl compact-audit  (last {days} days)")
    print("=" * 58)

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return

    cur = conn.cursor()
    cutoff = f"strftime('%s', 'now', '-{int(days)} days')"

    # Overall rate (rows with compaction_detected=1)
    cur.execute(f"""
        SELECT
          COUNT(DISTINCT session_id) AS total_sessions,
          COUNT(DISTINCT CASE WHEN compaction_detected=1 THEN session_id END) AS compacted
        FROM sessions
        WHERE timestamp >= {cutoff}
    """)
    total, compacted = cur.fetchone()
    if not total:
        print(f"No session data in last {days} days.")
        conn.close()
        return

    compact_rate = (compacted or 0) / total * 100 if total else 0
    print()
    print("Compaction summary:")
    print(f"  Sessions with compaction:  {compacted or 0}/{total}  ({compact_rate:.0f}%)")

    if compact_rate > 30:
        print(f"\n  🔴 {compact_rate:.0f}% of sessions hit compaction.")
        print(f"     Sessions running too long or starting with too much context.")
        print(f"     Consider: shorter focused sessions, earlier /compact calls.")
    elif compact_rate > 15:
        print(f"\n  🟡 {compact_rate:.0f}% compaction rate — moderate.")
    else:
        print(f"\n  ✓  Low compaction rate ({compact_rate:.0f}%) — sessions sized well.")

    # Per-project compaction rate
    cur.execute(f"""
        SELECT
          project,
          COUNT(DISTINCT session_id) AS total,
          COUNT(DISTINCT CASE WHEN compaction_detected=1 THEN session_id END) AS compacted
        FROM sessions
        WHERE timestamp >= {cutoff}
        GROUP BY project
        HAVING compacted > 0
        ORDER BY (compacted * 1.0 / total) DESC
        LIMIT 10
    """)
    proj_rows = cur.fetchall()
    if proj_rows:
        print()
        print("Per-project compaction rate:")
        for proj, ptotal, pcompacted in proj_rows:
            rate = (pcompacted / ptotal * 100) if ptotal else 0
            icon = "🔴" if rate > 40 else "🟡" if rate > 20 else "🟢"
            print(f"  {icon} {(proj or 'unknown'):<20} "
                  f"{pcompacted}/{ptotal} sessions  ({rate:.0f}%)")

    # Optional: derive multi-compaction from JSONL `type=summary` records
    summary_counts = _count_summaries_per_session()
    multi = {sid: n for sid, n in summary_counts.items() if n >= 2}
    if multi:
        print()
        print(f"🔴 Sessions with multiple compactions (≥2 `type=summary` records):")
        # Pull project + recent timestamp for top-5 multi sessions
        for sid, n in sorted(multi.items(), key=lambda kv: kv[1], reverse=True)[:5]:
            proj_row = cur.execute(
                "SELECT project, MAX(timestamp), SUM(cost_usd) "
                "FROM sessions WHERE session_id = ?",
                (sid,)
            ).fetchone()
            if proj_row and proj_row[1]:
                from datetime import datetime
                dt = datetime.fromtimestamp(proj_row[1]).strftime("%Y-%m-%d %H:%M")
                cost = proj_row[2] or 0
                print(f"  {sid[:12]}…  {n} compactions  "
                      f"{(proj_row[0] or 'unknown')}  ${cost:.4f}  [{dt}]")
        print(f"  ({len(multi)} session(s) total with ≥2 compactions)")
    else:
        print()
        print("✓ No sessions with multiple compactions detected via JSONL pass.")

    conn.close()
    print()
    print("=" * 58)
    print("💡 High compaction = sessions too long or starting too heavy.")
    print("  1. Break long tasks into focused sessions")
    print("  2. Use /compact proactively at natural milestones")
    print("  3. Run `burnctl overhead-audit` to check session startup size")
    print()


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_compact_audit(days)
