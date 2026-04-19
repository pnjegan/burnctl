"""burn_rate.py — live burn-rate, retry-loop detection, statusline.

Reads only the `sessions` table from data/usage.db (already populated by
scanner.py). Zero pip deps. All numbers are observed local data — there
are NO estimates of Anthropic-published rate limits, since Anthropic does
not publish them.

Schema reference (sessions, verified):
  cost_usd        REAL    per-session cost
  input_tokens    INTEGER
  output_tokens   INTEGER
  timestamp       INTEGER unix seconds
  project         TEXT
"""

import os
import sqlite3
import time
from datetime import datetime


DB_DEFAULT = "data/usage.db"


def _connect(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found at {db_path}. Run `burnctl scan` first.")
    return sqlite3.connect(db_path)


def get_burn_rate(db_path=DB_DEFAULT, window_minutes=5):
    """Tokens/min and $/min observed in the last `window_minutes`.

    Returns:
      tokens_per_min, cost_per_min, cost_per_hour (projected at current rate),
      input_tokens, output_tokens, sessions_active, window_minutes, sampled_at
    """
    try:
        db = _connect(db_path)
        cutoff = int(time.time()) - (window_minutes * 60)
        row = db.execute(
            """
            SELECT
              COUNT(*),
              COALESCE(SUM(input_tokens), 0),
              COALESCE(SUM(output_tokens), 0),
              COALESCE(SUM(cost_usd), 0.0)
            FROM sessions
            WHERE timestamp > ?
            """,
            (cutoff,),
        ).fetchone()
        sessions, input_t, output_t, cost = row
        total_tokens = (input_t or 0) + (output_t or 0)
        cost = cost or 0.0
        return {
            "tokens_per_min": round(total_tokens / window_minutes, 1),
            "cost_per_min": round(cost / window_minutes, 6),
            "cost_per_hour": round((cost / window_minutes) * 60, 4),
            "input_tokens": input_t,
            "output_tokens": output_t,
            "sessions_active": sessions or 0,
            "window_minutes": window_minutes,
            "sampled_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        return {
            "error": str(e),
            "tokens_per_min": 0,
            "cost_per_min": 0,
            "cost_per_hour": 0,
        }


def get_block_status(db_path=DB_DEFAULT):
    """5-hour rolling block — observed totals only.

    We deliberately do NOT estimate `% of limit used` because Anthropic
    does not publish per-plan block limits. Reporting a fabricated limit
    misleads users; reporting raw burn lets them apply their own intuition.
    """
    try:
        db = _connect(db_path)
        block_start = int(time.time()) - (5 * 3600)
        row = db.execute(
            """
            SELECT
              COALESCE(SUM(input_tokens + output_tokens), 0),
              COALESCE(SUM(cost_usd), 0.0),
              COUNT(*),
              MIN(timestamp)
            FROM sessions
            WHERE timestamp > ?
            """,
            (block_start,),
        ).fetchone()
        total_tokens, total_cost, session_count, first_ts = row

        # Block reset estimate — when does the oldest session in the
        # current 5h window age out? That is when usage starts dropping.
        reset_in = None
        if first_ts:
            reset_at = first_ts + (5 * 3600)
            secs = reset_at - int(time.time())
            if secs > 0:
                hh = secs // 3600
                mm = (secs % 3600) // 60
                reset_in = f"{hh}h {mm}m"

        return {
            "block_tokens_used": total_tokens,
            "block_cost_usd": round(total_cost, 4),
            "session_count": session_count,
            "estimated_pct_used": None,
            "eta_to_limit": None,
            "block_resets_in": reset_in,
            "note": "Anthropic does not publish block limits. Numbers above are observed local burn only — no quota inference.",
        }
    except Exception as e:
        return {"error": str(e)}


def detect_loops(db_path=DB_DEFAULT, lookback_minutes=10,
                 min_sessions=5, max_avg_gap_seconds=60):
    """Conservative retry-loop detector.

    A "loop" here is the same project firing >= `min_sessions` sessions
    within `lookback_minutes`, with an average inter-session gap below
    `max_avg_gap_seconds`. The thresholds are deliberately conservative
    so an active human-in-the-loop session does NOT trip the detector;
    we want signal for autonomous retry storms only.
    """
    try:
        db = _connect(db_path)
        cutoff = int(time.time()) - (lookback_minutes * 60)
        rows = db.execute(
            """
            SELECT project, timestamp, cost_usd
            FROM sessions
            WHERE timestamp > ?
            ORDER BY project, timestamp
            """,
            (cutoff,),
        ).fetchall()

        per_project = {}
        for project, ts, cost in rows:
            per_project.setdefault(project, []).append((ts, cost or 0.0))

        loops = []
        for project, sess in per_project.items():
            if len(sess) < min_sessions:
                continue
            avg_gap = (sess[-1][0] - sess[0][0]) / max(len(sess) - 1, 1)
            if avg_gap < max_avg_gap_seconds:
                loops.append({
                    "project": project,
                    "session_count": len(sess),
                    "total_cost_usd": round(sum(c for _, c in sess), 4),
                    "avg_gap_seconds": round(avg_gap, 1),
                    "severity": "HIGH" if len(sess) >= 10 else "MEDIUM",
                })
        return loops
    except Exception:
        return []


def statusline(db_path=DB_DEFAULT):
    """One-line statusline output for Claude Code statusline hooks.

    Format: ⚡ 142t/min | $0.84/hr | 5hr: 12.3k tok / $0.41 | Loop: ✓
    """
    br = get_burn_rate(db_path, window_minutes=5)
    block = get_block_status(db_path)
    loops = detect_loops(db_path)

    tpm = br.get("tokens_per_min", 0)
    cph = br.get("cost_per_hour", 0)
    block_tok = block.get("block_tokens_used", 0) if "error" not in block else 0
    block_cost = block.get("block_cost_usd", 0) if "error" not in block else 0
    loop_str = f"⚠ {len(loops)} loop(s)" if loops else "✓"

    block_tok_h = (
        f"{block_tok / 1000:.1f}k" if block_tok >= 1000 else str(block_tok)
    )
    return f"⚡ {tpm}t/min | ${cph}/hr | 5hr: {block_tok_h} tok / ${block_cost} | Loop: {loop_str}"


def _print_human(db_path=DB_DEFAULT):
    br = get_burn_rate(db_path)
    block = get_block_status(db_path)
    loops = detect_loops(db_path)

    print("=== burnctl status ===")
    if "error" in br:
        print(f"ERROR: {br['error']}")
        return
    print(f"Burn rate (last 5 min):  {br['tokens_per_min']} tokens/min")
    print(f"Cost rate:               ${br['cost_per_min']}/min  (${br['cost_per_hour']}/hr projected)")
    print(f"Active sessions:         {br['sessions_active']}")
    print()
    print(f"5-hour block (observed):")
    print(f"  Tokens used:           {block.get('block_tokens_used', 0):,}")
    print(f"  Cost:                  ${block.get('block_cost_usd', 0)}")
    if block.get("block_resets_in"):
        print(f"  Window rolls forward:  {block['block_resets_in']}")
    print(f"  {block.get('note', '')}")
    print()
    if loops:
        print(f"⚠  {len(loops)} loop(s) detected (last 10 min):")
        for lp in loops:
            print(f"   {lp['project']}: {lp['session_count']} sessions, "
                  f"avg gap {lp['avg_gap_seconds']}s, ${lp['total_cost_usd']}  [{lp['severity']}]")
    else:
        print("✓ No retry loops detected in last 10 min")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "statusline":
        print(statusline())
    elif cmd == "block":
        import json
        print(json.dumps(get_block_status(), indent=2))
    elif cmd == "loops":
        loops = detect_loops()
        if not loops:
            print("✓ No retry loops detected")
        else:
            print(f"⚠  {len(loops)} loop(s) detected:")
            for lp in loops:
                print(f"   {lp['project']}: {lp['session_count']} sessions, "
                      f"avg gap {lp['avg_gap_seconds']}s, ${lp['total_cost_usd']}  [{lp['severity']}]")
    elif cmd == "burnrate":
        import json
        print(json.dumps(get_burn_rate(), indent=2))
    else:
        _print_human()
