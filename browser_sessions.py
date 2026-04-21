"""burnctl browser_sessions — session detection from claude_ai_snapshots.

Detects browser sessions from pct_used deltas, computes per-account
summaries, flags browser-specific waste patterns. VPS-side only —
Mac collector is untouched.

GRANULARITY NOTE
────────────────
Anthropic's claude.ai usage API reports tokens_used rounded to the
nearest 10,000 and pct_used rounded to 1%. Every detection in this
module inherits that 10k-token / 1-pct floor. Bursts below that
threshold are invisible. Treat all cost numbers as "est. (API-list
input rate, 10k-token granularity)" — never invoice-grade.

HEURISTICS
──────────
Session boundaries:
  1. Window reset (pct_used drops > 5% between snapshots) — hard boundary
  2. Plateau ≥ 3 consecutive flat snapshots (≈15 min at 5-min cadence)
     — soft boundary; session ends at the last rising snapshot

A session is a contiguous run of snapshots where pct_used either rises
or is flat for < 3 consecutive polls. The start is the first rising
snapshot after a boundary; the end is the last rising snapshot before
the next boundary.

Spec says "gap > 30 min between snapshots" but real polling cadence is
~5 min with max 10.7 min — so gap-based detection never fires. Plateau
is the effective session-end signal.

COST
────
$3 / MTok (Sonnet input-only, API list price, conservative). Actual
blended rate is higher but this number is intentionally an underestimate
so we don't overclaim to operators. Labeled "est." in all output.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone


# ─── Constants ───────────────────────────────────────────────────

BLENDED_USD_PER_TOKEN = 3.0 / 1_000_000  # API-list input rate, conservative
PLATEAU_FLAT_SNAPSHOTS = 3                # ≈ 15 min at 5-min cadence
RESET_DROP_PCT = 5.0                      # pct drop indicating window reset
LONG_SESSION_MIN = 30                     # "long" session threshold
FLAGGED_AVG_MIN = 60                      # avg duration flagging threshold
FRAGMENTED_MIN_PER_DAY = 3                # same-account same-day session count
CONSECUTIVE_GAP_SEC = 600                 # < 10 min between sessions
THIN_DATA_MIN_SESSIONS = 3                # below this → thin-data flag
DAY_SEC = 86400


# ─── DB location (matches overhead_audit.load_db) ────────────────

def _load_db(db_path=None):
    if db_path:
        return sqlite3.connect(db_path) if os.path.exists(db_path) else None
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/projects/burnctl/data/usage.db"),
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


# ─── Session detection ───────────────────────────────────────────

def _close_session(cur, account_id, tokens_limit):
    """Emit a session dict from an in-progress cur state, or None."""
    if cur is None or cur["end_time"] is None:
        return None
    duration_sec = cur["end_time"] - cur["start_time"]
    # Ignore single-snapshot "sessions" (0-duration artefacts)
    if duration_sec <= 0:
        return None
    pct_delta = cur["end_pct"] - cur["start_pct"]
    tokens_consumed = (pct_delta / 100.0) * (tokens_limit or 1_000_000)
    if tokens_consumed < 0:
        tokens_consumed = 0.0
    cost_est = tokens_consumed * BLENDED_USD_PER_TOKEN
    duration_min = int(round(duration_sec / 60))
    return {
        "account_id": account_id,
        "start_time": cur["start_time"],
        "end_time": cur["end_time"],
        "duration_min": duration_min,
        "start_pct": cur["start_pct"],
        "end_pct": cur["end_pct"],
        "pct_delta": pct_delta,
        "tokens_consumed": int(tokens_consumed),
        "cost_est_usd": round(cost_est, 4),
        "is_long_session": duration_min > LONG_SESSION_MIN,
        "snapshot_count": cur["snapshot_count"],
    }


def detect_browser_sessions(account_id, db_path=None, days=7):
    """Return a list of session dicts for account_id over last `days`."""
    conn = _load_db(db_path)
    if not conn:
        return []
    cur = conn.cursor()
    cutoff = int(time.time()) - days * DAY_SEC
    cur.execute("""
        SELECT polled_at, pct_used, tokens_limit
        FROM claude_ai_snapshots
        WHERE account_id = ? AND polled_at >= ?
        ORDER BY polled_at ASC
    """, (account_id, cutoff))
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 2:
        return []

    sessions = []
    state = None
    flat_count = 0
    prev_pct = None
    # Use the most recent non-null tokens_limit we encounter as the canonical
    # limit for this account in this window.
    tokens_limit = 1_000_000
    for polled_at, pct, tl in rows:
        if tl:
            tokens_limit = tl

        if prev_pct is None:
            prev_pct = pct
            continue

        delta = pct - prev_pct

        # Hard boundary: window reset
        if delta < -RESET_DROP_PCT:
            emitted = _close_session(state, account_id, tokens_limit)
            if emitted:
                sessions.append(emitted)
            state = None
            flat_count = 0
            prev_pct = pct
            continue

        # Rising pct → session in progress
        if delta > 0:
            if state is None:
                state = {
                    "start_time": polled_at,
                    "end_time": polled_at,
                    "start_pct": prev_pct,
                    "end_pct": pct,
                    "snapshot_count": 2,  # prev + this
                }
            else:
                state["end_time"] = polled_at
                state["end_pct"] = pct
                state["snapshot_count"] += 1
            flat_count = 0
        else:
            # Flat or tiny negative (noise)
            if state is not None:
                flat_count += 1
                if flat_count >= PLATEAU_FLAT_SNAPSHOTS:
                    emitted = _close_session(state, account_id, tokens_limit)
                    if emitted:
                        sessions.append(emitted)
                    state = None
                    flat_count = 0

        prev_pct = pct

    # Tail session
    emitted = _close_session(state, account_id, tokens_limit)
    if emitted:
        sessions.append(emitted)

    return sessions


# ─── Time helpers ────────────────────────────────────────────────

def _start_of_today_utc():
    now = datetime.now(timezone.utc)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _cc_cost_in_window(conn, start_ts):
    """Sum Claude Code session cost since start_ts from sessions table."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM sessions
            WHERE timestamp >= ?
              AND (is_subagent = 0 OR is_subagent IS NULL)
        """, (start_ts,))
        return float(cur.fetchone()[0] or 0)
    except sqlite3.OperationalError:
        return 0.0


# ─── Summary ─────────────────────────────────────────────────────

def get_browser_summary(db_path=None, days=7):
    """Aggregate per-account browser session stats + combined CC vs browser."""
    conn = _load_db(db_path)
    if not conn:
        return {"accounts": {}, "combined": {}, "thin_data": True,
                "granularity_note": "10k-token / 1-pct granularity"}

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT account_id FROM claude_ai_snapshots")
    account_ids = [r[0] for r in cur.fetchall()]

    today_start = _start_of_today_utc()
    week_start = int(time.time()) - 7 * DAY_SEC

    accounts = {}
    any_thin = False
    total_browser_today = 0.0
    total_browser_week = 0.0

    for aid in account_ids:
        sessions = detect_browser_sessions(aid, db_path=db_path, days=days)
        today = [s for s in sessions if s["end_time"] >= today_start]
        week = [s for s in sessions if s["end_time"] >= week_start]

        durations_today = [s["duration_min"] for s in today]
        durations_week = [s["duration_min"] for s in week]

        avg_today = (sum(durations_today) / len(durations_today)) if durations_today else 0
        longest_today = max(durations_today) if durations_today else 0
        tokens_today = sum(s["tokens_consumed"] for s in today)
        cost_today = sum(s["cost_est_usd"] for s in today)
        cost_week = sum(s["cost_est_usd"] for s in week)
        long_today = sum(1 for s in today if s["is_long_session"])

        flagged = avg_today > FLAGGED_AVG_MIN if durations_today else False
        thin = len(sessions) < THIN_DATA_MIN_SESSIONS
        if thin:
            any_thin = True

        accounts[aid] = {
            "sessions_today": len(today),
            "sessions_this_week": len(week),
            "avg_duration_min": round(avg_today, 1),
            "longest_session_min": int(longest_today),
            "total_tokens_today": int(tokens_today),
            "total_cost_est_today": round(cost_today, 2),
            "total_cost_est_week": round(cost_week, 2),
            "long_sessions_today": int(long_today),
            "flagged": bool(flagged),
            "thin_data": bool(thin),
            "sessions_all": sessions,  # for downstream consumers
        }
        total_browser_today += cost_today
        total_browser_week += cost_week

    cc_cost_week = _cc_cost_in_window(conn, week_start)
    total_week = total_browser_week + cc_cost_week
    browser_pct = (total_browser_week / total_week * 100) if total_week > 0 else 0.0

    # Window-mismatch check: browser_cost_week covers only as much data as we
    # have snapshots for. If the earliest snapshot is <7 days old, the ratio
    # underrepresents browser share.
    cur = conn.cursor()
    cur.execute("SELECT MIN(polled_at) FROM claude_ai_snapshots")
    earliest = cur.fetchone()[0]
    browser_window_days = None
    window_note = None
    if earliest:
        browser_window_days = round((int(time.time()) - earliest) / DAY_SEC, 1)
        if browser_window_days < 7.0:
            window_note = (
                f"comparison window differs — browser data spans "
                f"{browser_window_days}d, cc spans 7d; ratio will self-correct "
                f"as snapshots accumulate"
            )

    conn.close()

    return {
        "accounts": accounts,
        "combined": {
            "browser_cost_today": round(total_browser_today, 2),
            "browser_cost_week": round(total_browser_week, 2),
            "cc_cost_week": round(cc_cost_week, 2),
            "browser_pct_of_total": round(browser_pct, 1),
            "browser_window_days": browser_window_days,
            "window_note": window_note,
        },
        "thin_data": any_thin,
        "granularity_note": (
            "est. (API-list input rate $3/MTok, 10k-token / 1-pct granularity)"
        ),
    }


# ─── Waste patterns ──────────────────────────────────────────────

def get_waste_patterns(db_path=None, days=7):
    """Detect browser-specific waste. Returns list of dicts (no DB writes).

    pattern_type ∈ {long_session, fragmented_topic, consecutive_peak}
    """
    conn = _load_db(db_path)
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT account_id FROM claude_ai_snapshots")
    account_ids = [r[0] for r in cur.fetchall()]
    conn.close()

    patterns = []

    for aid in account_ids:
        sessions = detect_browser_sessions(aid, db_path=db_path, days=days)
        if not sessions:
            continue

        # Pattern 1: long_session (> 60 min = context bloat risk)
        for s in sessions:
            if s["duration_min"] > FLAGGED_AVG_MIN:
                patterns.append({
                    "pattern_type": "long_session",
                    "account": aid,
                    "detected_at": s["end_time"],
                    "duration_min": s["duration_min"],
                    "cost_est_usd": s["cost_est_usd"],
                    "detail": (
                        f"{s['duration_min']}-min session on "
                        f"{datetime.fromtimestamp(s['start_time']).strftime('%Y-%m-%d %H:%M')} "
                        f"UTC"
                    ),
                })

        # Pattern 2: fragmented_topic — 3+ sessions same account same day
        by_day = {}
        for s in sessions:
            day = datetime.fromtimestamp(s["start_time"], tz=timezone.utc).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(s)
        for day, day_sessions in by_day.items():
            if len(day_sessions) >= FRAGMENTED_MIN_PER_DAY:
                total_cost = sum(s["cost_est_usd"] for s in day_sessions)
                patterns.append({
                    "pattern_type": "fragmented_topic",
                    "account": aid,
                    "detected_at": day_sessions[-1]["end_time"],
                    "session_count": len(day_sessions),
                    "cost_est_usd": round(total_cost, 2),
                    "detail": (
                        f"{len(day_sessions)} sessions on {day} "
                        f"(same-day fragmentation)"
                    ),
                })

        # Pattern 3: consecutive_peak — back-to-back < 10 min apart
        sessions_sorted = sorted(sessions, key=lambda s: s["start_time"])
        for i in range(1, len(sessions_sorted)):
            gap = sessions_sorted[i]["start_time"] - sessions_sorted[i - 1]["end_time"]
            if 0 < gap < CONSECUTIVE_GAP_SEC:
                pair_cost = (
                    sessions_sorted[i]["cost_est_usd"]
                    + sessions_sorted[i - 1]["cost_est_usd"]
                )
                patterns.append({
                    "pattern_type": "consecutive_peak",
                    "account": aid,
                    "detected_at": sessions_sorted[i]["start_time"],
                    "gap_sec": int(gap),
                    "cost_est_usd": round(pair_cost, 2),
                    "detail": (
                        f"sessions {int(gap/60)}min apart — no context reset"
                    ),
                })

    return patterns


# ─── CLI shim (for ad-hoc inspection) ────────────────────────────

def _main():
    summary = get_browser_summary()
    import json
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    _main()
