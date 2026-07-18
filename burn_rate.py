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
from datetime import datetime, timezone
from pathlib import Path


DB_DEFAULT = "data/usage.db"

_DB_NOT_FOUND_ERR = "No burnctl database found. Run: burnctl scan first"


def resolve_db_path(db_path=DB_DEFAULT):
    """Locate the usage.db file across install layouts.

    Lookup order:
      1. The path passed in, if it exists (covers cwd-relative + absolute)
      2. ~/.burnctl/data/usage.db  (npm/git-clone install via bin/burnctl.js)
      3. <script_dir>/data/usage.db (dev/clone install — burn_rate.py adjacent to data/)

    Returns the resolved path string, or None if no DB is found anywhere.
    """
    if db_path and os.path.exists(db_path):
        return db_path
    install_db = Path.home() / ".burnctl" / "data" / "usage.db"
    if install_db.exists():
        return str(install_db)
    script_db = Path(__file__).parent / "data" / "usage.db"
    if script_db.exists():
        return str(script_db)
    return None


def get_burn_rate(db_path=DB_DEFAULT, window_minutes=5):
    """Tokens/min and $/min observed in the last `window_minutes`.

    Returns:
      tokens_per_min, cost_per_min, cost_per_hour (projected at current rate),
      input_tokens, output_tokens, sessions_active, window_minutes, sampled_at
    """
    resolved = resolve_db_path(db_path)
    if resolved is None or not os.path.exists(resolved):
        return {
            "error": _DB_NOT_FOUND_ERR,
            "tokens_per_min": 0,
            "cost_per_min": 0,
            "cost_per_hour": 0,
        }
    try:
        db = sqlite3.connect(resolved)
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
            "sampled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
    resolved = resolve_db_path(db_path)
    if resolved is None or not os.path.exists(resolved):
        return {"error": _DB_NOT_FOUND_ERR}
    try:
        db = sqlite3.connect(resolved)
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

    On missing/unreadable DB returns [] (silent — loop detection is
    best-effort and should never crash a statusline hook).
    """
    resolved = resolve_db_path(db_path)
    if resolved is None or not os.path.exists(resolved):
        return []
    try:
        db = sqlite3.connect(resolved)
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
    resolved = resolve_db_path(db_path)
    if resolved is None or not os.path.exists(resolved):
        return f"burnctl: {_DB_NOT_FOUND_ERR}"

    br = get_burn_rate(resolved, window_minutes=5)
    block = get_block_status(resolved)
    loops = detect_loops(resolved)

    tpm = br.get("tokens_per_min", 0)
    cph = br.get("cost_per_hour", 0)
    block_tok = block.get("block_tokens_used", 0) if "error" not in block else 0
    block_cost = block.get("block_cost_usd", 0) if "error" not in block else 0
    loop_str = f"⚠ {len(loops)} loop(s)" if loops else "✓"

    block_tok_h = (
        f"{block_tok / 1000:.1f}k" if block_tok >= 1000 else str(block_tok)
    )
    return f"⚡ {tpm}t/min | ${cph}/hr | 5hr: {block_tok_h} tok / ${block_cost} | Loop: {loop_str}"


# ── Project-aware live context gauge (v5.x) ──────────────────────────
# Claude Code's statusline hook sends its NATIVE context_window.used_percentage
# on stdin (per CC docs). We render a live gauge straight from that field
# (zero DB), and — only once context is genuinely filling (>=50%) — append a
# nudge grounded in THIS project's real compaction history from usage.db.
# That history is the thing a live-only statusline (HUD/ccstatusline) cannot
# show: it needs per-project churn data, which burnctl already has.
#
# Detect-not-enforce, absolute: the statusline only ever PRINTS. It never
# pauses, blocks, or compacts CC. No fabrication: if used_percentage is absent
# we show "--%", and if a project has no history we fall back to the plain
# gauge — never a guessed number.
#
# Perf: the hook fires every ~300ms. The gauge itself touches no DB. The
# project map and the per-project history are read at most once per TTL and
# cached to a small JSON file, so sqlite is never opened on the hot path.

_HISTORY_TTL_SEC = 1800   # 30 min — compaction history barely moves intra-session
_NUDGE_CTX_FLOOR = 50     # only consult the cache/DB once context is filling


def _statusline_cache_path():
    return os.path.expanduser("~/.burnctl/cache/statusline_history.json")


def _load_statusline_cache():
    import json
    try:
        with open(_statusline_cache_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_statusline_cache(cache):
    import json
    path = _statusline_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def _cached_project_map(db_path=DB_DEFAULT):
    """Project map (account_projects) read at most once per TTL, then cached.

    Avoids resolve_project()'s default DB open on every 300ms tick.
    """
    now = int(time.time())
    cache = _load_statusline_cache()
    entry = cache.get("_project_map")
    if entry and (now - entry.get("computed_at", 0)) < _HISTORY_TTL_SEC:
        return entry.get("map") or {}
    mapping = {}
    try:
        from db import get_project_map_config
        mapping = get_project_map_config() or {}
    except Exception:
        mapping = {}
    cache["_project_map"] = {"computed_at": now, "map": mapping}
    _save_statusline_cache(cache)
    return mapping


def _project_compaction_history(project, db_path=DB_DEFAULT):
    """Avg compactions/session over 30d for `project`, TTL-cached.

    Returns {"avg", "sessions", "compacts"} or None when there is no usable
    history (unknown bucket, <2 sessions, or zero compactions). Sources the
    canonical lifecycle_events compaction log (event_type='compact') — the
    same signal insights.py uses. Never fabricates.
    """
    from config import UNKNOWN_PROJECT
    if not project or project == UNKNOWN_PROJECT:
        return None

    now = int(time.time())
    cache = _load_statusline_cache()
    hist = cache.get("history") or {}
    entry = hist.get(project)
    if entry and (now - entry.get("computed_at", 0)) < _HISTORY_TTL_SEC:
        return entry.get("value")

    value = None
    resolved = resolve_db_path(db_path)
    if resolved and os.path.exists(resolved):
        cutoff = now - 30 * 86400
        try:
            conn = sqlite3.connect(resolved)
            try:
                sessions = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) FROM sessions "
                    "WHERE project=? AND is_subagent=0 AND timestamp>=?",
                    (project, cutoff),
                ).fetchone()[0] or 0
                compacts = conn.execute(
                    "SELECT COUNT(*) FROM lifecycle_events "
                    "WHERE project=? AND event_type='compact' AND timestamp>=?",
                    (project, cutoff),
                ).fetchone()[0] or 0
            finally:
                conn.close()
            if sessions >= 2 and compacts > 0:
                value = {
                    "avg": round(compacts / sessions, 1),
                    "sessions": int(sessions),
                    "compacts": int(compacts),
                }
        except sqlite3.Error:
            value = None

    hist[project] = {"computed_at": now, "value": value}
    cache["history"] = hist
    _save_statusline_cache(cache)
    return value


def _ctx_bar(pct, width=10):
    """Unicode bar; fill clamped to [0, width]. The true % is shown as text."""
    try:
        frac = (float(pct) or 0) / 100.0
    except (TypeError, ValueError):
        frac = 0.0
    filled = max(0, min(width, round(frac * width)))
    return "█" * filled + "░" * (width - filled)


def statusline_gauge(payload, db_path=DB_DEFAULT):
    """Render the project-aware context gauge from a CC statusline stdin dict.

    Format: [model] PROJECT ctx XX% <bar> <state>[ · PROJECT avg N compact/sess]
    Thresholds: <50 calm · 50-69 ⚠ wrap soon · 70-84 🔴 /clear · >=85 🛑 /clear NOW. Display only.
    """
    payload = payload or {}
    model = ((payload.get("model") or {}).get("display_name")) or "?"
    cw = payload.get("context_window") or {}
    pct = cw.get("used_percentage")

    workspace = payload.get("workspace") or {}
    current_dir = workspace.get("current_dir") or payload.get("cwd") or ""
    from config import UNKNOWN_PROJECT
    try:
        from scanner import resolve_project
        project, _account = resolve_project(current_dir, _cached_project_map(db_path))
    except Exception:
        project = UNKNOWN_PROJECT
    proj_label = project or UNKNOWN_PROJECT

    # used_percentage is null before the first API call — show "--", never fake.
    if pct is None:
        return f"[{model}] {proj_label} ctx --% {_ctx_bar(0)}"
    try:
        pctf = float(pct)
    except (TypeError, ValueError):
        return f"[{model}] {proj_label} ctx --% {_ctx_bar(0)}"

    line = f"[{model}] {proj_label} ctx {pctf:.0f}% {_ctx_bar(pctf)}"

    # Threshold state — detect only, never enforce.
    if pctf >= 85:
        line += " \U0001F6D1 /clear NOW"  # 🛑 /clear NOW
    elif pctf >= 70:
        line += " \U0001F534 /clear"      # 🔴 /clear
    elif pctf >= 50:
        line += " ⚠ wrap soon"       # ⚠ wrap soon

    # Project-aware nudge: only when filling AND this project has real history.
    if pctf >= _NUDGE_CTX_FLOOR:
        hist = _project_compaction_history(project, db_path)
        if hist:
            line += f" · {proj_label} avg {hist['avg']} compact/sess"
    return line


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
