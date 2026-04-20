"""burnctl work-timeline — unified cognitive work timeline.

Joins Claude Code JSONL session data with claude.ai browser sync
snapshots to show work patterns across both surfaces, not token totals.

DATA SOURCES
------------
1. `sessions` table — one row per CC turn. Grouped by session_id to
   get real per-session [start, end, cost, project].

2. `claude_ai_snapshots` table — point-in-time polls (~5 min apart)
   of the claude.ai browser window. Activity is INFERRED from
   tokens_used deltas between consecutive snapshots.

HONESTY NOTES
-------------
- Browser activity is derived from snapshot deltas. Precision is the
  polling interval (typically 5 min). We never claim minute-level
  browser timestamps.
- If tokens_used decreases between snapshots, the 5h window reset —
  we skip that gap, not count it as browser activity.
- When browser data is too sparse (< 5 snapshots in the window) we
  say so instead of inventing a timeline.
"""
import datetime
import os
import sqlite3
import sys
from collections import defaultdict


POLL_INTERVAL_SEC = 300  # claude_ai_snapshots polled ~every 5 min
CC_TURN_GAP_MAX_SEC = 300  # turns within 5 min count as one active block
CC_MIN_BLOCK_SEC = 90  # single-turn block treated as ~1.5 min of active work
PEAK_START_UTC = 13
PEAK_END_UTC = 19
SWITCH_GAP_SEC = 1800  # 30 min — if surfaces within this gap, count as a switch


def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def _fmt_hm(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%H:%M")


def _fmt_day(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%b %d")


def _fmt_weekday(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%a")


def _fmt_duration(sec):
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def _in_peak_hours(ts):
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.weekday() < 5 and PEAK_START_UTC <= dt.hour < PEAK_END_UTC


def get_cc_sessions(conn, since_ts, until_ts):
    """Return CC session active-blocks grouped by session_id.

    Each returned session has `active_blocks` (list of [start, end] where
    consecutive turns were within CC_TURN_GAP_MAX_SEC of each other) plus
    summary fields. Active time = sum of block durations, NOT session span.
    This prevents inflated "20h/day" numbers when a session is left open
    across meals / sleep.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT session_id, timestamp, cost_usd, project, account, is_subagent
        FROM sessions
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY session_id, timestamp
        """,
        (since_ts, until_ts),
    )
    rows = cur.fetchall()
    grouped = defaultdict(list)
    for r in rows:
        grouped[r[0]].append(r)

    sessions = []
    for sid, turns in grouped.items():
        timestamps = [t[1] for t in turns]
        cost = sum((t[2] or 0.0) for t in turns)
        projects = defaultdict(int)
        for t in turns:
            projects[t[3] or "Unknown"] += 1
        project = max(projects.items(), key=lambda x: x[1])[0]
        account = turns[0][4] or "unknown"
        is_sub = bool(turns[0][5])

        # build active blocks — consecutive turns within CC_TURN_GAP_MAX_SEC
        blocks = []
        block_start = timestamps[0]
        block_end = timestamps[0]
        for ts in timestamps[1:]:
            if ts - block_end <= CC_TURN_GAP_MAX_SEC:
                block_end = ts
            else:
                blocks.append([block_start, max(block_end, block_start + CC_MIN_BLOCK_SEC)])
                block_start = ts
                block_end = ts
        blocks.append([block_start, max(block_end, block_start + CC_MIN_BLOCK_SEC)])

        sessions.append({
            "session_id": sid,
            "start": timestamps[0],
            "end": blocks[-1][1],
            "active_blocks": blocks,
            "duration": sum(b[1] - b[0] for b in blocks),
            "cost": cost,
            "project": project,
            "account": account,
            "is_subagent": is_sub,
        })
    sessions.sort(key=lambda s: s["start"])
    return sessions


def get_browser_activity(conn, since_ts, until_ts):
    """Derive browser activity bursts from snapshot deltas.

    Returns list of {start, end, tokens_delta, pct_delta, account}.
    Each burst represents a gap between two consecutive snapshots where
    tokens_used increased — meaning the user sent messages to claude.ai
    during that interval. Precision floor: POLL_INTERVAL_SEC.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT account_id, polled_at, tokens_used, pct_used,
               five_hour_utilization, window_start
        FROM claude_ai_snapshots
        WHERE polled_at >= ? AND polled_at < ?
        ORDER BY account_id, polled_at
        """,
        (since_ts, until_ts),
    )
    rows = cur.fetchall()
    if len(rows) < 2:
        return []

    bursts = []
    per_account = defaultdict(list)
    for r in rows:
        per_account[r[0]].append(r)

    for account, acct_rows in per_account.items():
        for i in range(1, len(acct_rows)):
            prev = acct_rows[i - 1]
            curr = acct_rows[i]
            _, prev_polled, prev_tokens, prev_pct, _, prev_win = prev
            _, curr_polled, curr_tokens, curr_pct, _, curr_win = curr
            # skip snapshots crossing a window reset — tokens_used drops
            if curr_win != prev_win:
                continue
            delta = curr_tokens - prev_tokens
            if delta <= 0:
                continue
            gap_sec = curr_polled - prev_polled
            if gap_sec > POLL_INTERVAL_SEC * 4:
                # the browser-sync daemon was paused; we can't claim the
                # whole gap was active work
                continue
            bursts.append({
                "start": prev_polled,
                "end": curr_polled,
                "duration": min(gap_sec, POLL_INTERVAL_SEC * 2),
                "tokens_delta": delta,
                "pct_delta": (curr_pct or 0) - (prev_pct or 0),
                "account": account,
            })
    bursts.sort(key=lambda b: b["start"])
    return bursts


def detect_overlaps(cc_sessions, browser_bursts):
    """Find time ranges where both CC and browser were actively in use.

    Uses CC active_blocks (intra-session keyboard bursts), not full session
    spans — so a session left open across meals doesn't fake an overlap.
    """
    overlaps = []
    for cc in cc_sessions:
        for block_start, block_end in cc["active_blocks"]:
            for br in browser_bursts:
                o_start = max(block_start, br["start"])
                o_end = min(block_end, br["end"])
                if o_end > o_start:
                    overlaps.append({
                        "start": o_start,
                        "end": o_end,
                        "duration": o_end - o_start,
                        "project": cc["project"],
                    })
    return overlaps


def count_switches(cc_sessions, browser_bursts):
    """Count surface transitions (CC→BR or BR→CC) within SWITCH_GAP_SEC."""
    events = []
    for cc in cc_sessions:
        events.append((cc["start"], "CC", cc["end"]))
    for br in browser_bursts:
        events.append((br["start"], "BR", br["end"]))
    events.sort()
    switches = 0
    last_surface = None
    last_end = None
    for start, surface, end in events:
        if last_surface is not None and surface != last_surface:
            if last_end is None or (start - last_end) < SWITCH_GAP_SEC:
                switches += 1
        last_surface = surface
        last_end = end
    return switches


def build_timeline(cc_sessions, browser_bursts):
    """Merge CC + BR into one chronological event list.

    Browser bursts polled within the same interval across multiple accounts
    are collapsed into one event (summing token_delta, max pct_delta).
    """
    events = []
    for cc in cc_sessions:
        events.append({
            "ts": cc["start"],
            "surface": "CC",
            "label": cc["project"],
            "duration": cc["duration"],
            "cost": cc["cost"],
            "is_subagent": cc["is_subagent"],
        })
    # collapse browser bursts that start within 60s (multi-account polls)
    by_start = defaultdict(list)
    for b in browser_bursts:
        bucket = (b["start"] // 60) * 60
        by_start[bucket].append(b)
    for start_ts, group in by_start.items():
        tokens = sum(g["tokens_delta"] for g in group)
        pct_delta = max((g["pct_delta"] or 0) for g in group)
        duration = max(g["duration"] for g in group)
        events.append({
            "ts": start_ts,
            "surface": "BR",
            "label": "browser",
            "duration": duration,
            "pct_delta": pct_delta,
            "tokens_delta": tokens,
        })
    events.sort(key=lambda e: e["ts"])
    return events


def _ratio_note(cc_pct):
    """Plain-English interpretation of CC vs BR ratio."""
    if cc_pct >= 70:
        return "building-heavy"
    if cc_pct >= 55:
        return "healthy — more building than planning"
    if cc_pct >= 45:
        return "balanced"
    if cc_pct >= 30:
        return "planning-heavy"
    return "mostly planning / research"


def render_day(conn, day_start, day_end, show_timeline=True):
    cc = get_cc_sessions(conn, day_start, day_end)
    br = get_browser_activity(conn, day_start, day_end)

    # wall-clock active time: merge overlapping intervals across sessions/accounts
    cc_intervals = [tuple(b) for s in cc for b in s["active_blocks"]]
    br_intervals = [(b["start"], b["end"]) for b in br]
    cc_merged = _merge_intervals(cc_intervals)
    br_merged = _merge_intervals(br_intervals)
    cc_active_sec = sum(e - s for s, e in cc_merged)
    br_active_sec = sum(e - s for s, e in br_merged)
    total = cc_active_sec + br_active_sec

    day_label = _fmt_day(day_start)
    print(f"\n{day_label} Work Intelligence")
    print("=" * 58)

    if total == 0:
        print("(no activity recorded)")
        return {"cc_sec": 0, "br_sec": 0, "switches": 0, "overlaps": 0}

    cc_pct = int(round(100 * cc_active_sec / total)) if total else 0
    br_pct = 100 - cc_pct

    print("\nSURFACE PATTERN")
    if br_active_sec == 0 and len(br) == 0:
        print(f"  Claude Code CLI    {_fmt_duration(cc_active_sec):>6}  (no browser snapshots for this window)")
    else:
        print(f"  Browser claude.ai  {br_pct:>3}% of active time  ({_fmt_duration(br_active_sec)})")
        print(f"  Claude Code CLI    {cc_pct:>3}% of active time  ({_fmt_duration(cc_active_sec)})")
        print(f"  Ratio: {_ratio_note(cc_pct)}")

    overlaps = detect_overlaps(cc, br)
    switches = count_switches(cc, br)

    if show_timeline:
        timeline = build_timeline(cc, br)
        if timeline:
            print(f"\nTIMELINE  ({day_label})")
            for ev in timeline[:30]:  # cap for terminal readability
                hm = _fmt_hm(ev["ts"])
                dur = _fmt_duration(ev["duration"])
                if ev["surface"] == "CC":
                    tag = "[CC]"
                    proj = ev["label"][:20]
                    cost = f"${ev['cost']:>6.2f}"
                    note = "  (subagent)" if ev.get("is_subagent") else ""
                    print(f"  {hm}  {tag}  {proj:<20} {dur:>5}  {cost}{note}")
                else:
                    tag = "[BR]"
                    delta = ev.get("pct_delta", 0) or 0
                    arrow = f"+{delta:.0f}%" if delta >= 0 else f"{delta:.0f}%"
                    tokens = ev.get("tokens_delta", 0) or 0
                    print(f"  {hm}  {tag}  {'browser':<20} {dur:>5}  window {arrow}  ({tokens:,} tok)")
            if len(timeline) > 30:
                print(f"  ... {len(timeline) - 30} more events")

        if overlaps:
            print()
            overlap_total = sum(o["duration"] for o in overlaps)
            merged = _merge_intervals([(o["start"], o["end"]) for o in overlaps])
            print("OVERLAPS (both surfaces active)")
            for m_start, m_end in merged[:5]:
                print(f"  [WARN] {_fmt_hm(m_start)}  CC + browser simultaneously  ({_fmt_duration(m_end - m_start)})")
            if len(merged) > 5:
                print(f"  ... {len(merged) - 5} more overlap windows")
            print(f"  Total overlap time: {_fmt_duration(overlap_total)} — double drain")

        print("\nPATTERNS DETECTED")
        if switches <= 4:
            print(f"  [OK]   Low context switching ({switches} transitions)")
        else:
            print(f"  [WARN] High context switching ({switches} transitions today)")

        if not overlaps:
            print(f"  [OK]   No overlap — surfaces used sequentially")
        else:
            print(f"  [WARN] {len(merged)} overlap period(s) — browser + CC simultaneous")

        peak_sessions = [s for s in cc if _in_peak_hours(s["start"])]
        peak_bursts = [b for b in br if _in_peak_hours(b["start"])]
        if peak_sessions or peak_bursts:
            print(f"  [WARN] {len(peak_sessions)} CC + {len(peak_bursts)} browser activity in peak hours (13:00-19:00 UTC)")
        else:
            print(f"  [OK]   No activity in peak-hour drain window")

    return {
        "cc_sec": cc_active_sec,
        "br_sec": br_active_sec,
        "switches": switches,
        "overlaps": len(overlaps),
    }


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [tuple(m) for m in merged]


def render_week(conn, days):
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    day_len = 86400
    today_utc = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_of_today = int(today_utc.timestamp())

    print(f"\nWEEK VIEW  (last {days} days)")
    print("=" * 58)
    for offset in range(days - 1, -1, -1):
        d_start = start_of_today - offset * day_len
        d_end = d_start + day_len
        cc = get_cc_sessions(conn, d_start, d_end)
        br = get_browser_activity(conn, d_start, d_end)
        cc_intervals = [tuple(b) for s in cc for b in s["active_blocks"]]
        br_intervals = [(b["start"], b["end"]) for b in br]
        cc_sec = sum(e - s for s, e in _merge_intervals(cc_intervals))
        br_sec = sum(e - s for s, e in _merge_intervals(br_intervals))
        total = cc_sec + br_sec
        if total == 0:
            print(f"  {_fmt_weekday(d_start)} {_fmt_day(d_start):<7}  (no activity)")
            continue
        cc_pct = int(round(100 * cc_sec / total))
        br_pct = 100 - cc_pct
        switches = count_switches(cc, br)
        note = _ratio_note(cc_pct)
        note_flag = ""
        if cc_pct < 45:
            note_flag = "  [planning-heavy]"
        elif cc_pct > 85:
            note_flag = "  [building-heavy]"
        print(
            f"  {_fmt_weekday(d_start)} {_fmt_day(d_start):<7}  "
            f"CC {_fmt_duration(cc_sec):>5}  BR {_fmt_duration(br_sec):>5}  "
            f"ratio {cc_pct:>2}/{br_pct:<2}  switches {switches:>2}"
            f"{note_flag}"
        )


def run_work_timeline(days=1):
    conn = load_db()
    if conn is None:
        print("Error: no burnctl DB found. Run `burnctl scan` from your project dir first.")
        return

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM claude_ai_snapshots")
    snap_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sessions")
    sess_count = cur.fetchone()[0]

    if snap_count < 5:
        print(
            "\nwork-timeline: browser sync data is too sparse to build a cross-surface timeline.\n"
            f"  claude_ai_snapshots rows: {snap_count}  (need >= 5)\n"
            f"  sessions rows: {sess_count}\n"
            "\nTo unlock the full timeline, run the mac-sync daemon on the machine with"
            "\nthe claude.ai browser session:"
            "\n  burnctl sync-daemon --start"
        )
        if sess_count > 0:
            print("\nCC-only view (no browser overlay):")
            now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            today_utc = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            render_day(conn, int(today_utc.timestamp()), now, show_timeline=True)
        conn.close()
        return

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    today_utc = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_of_today = int(today_utc.timestamp())

    if days <= 1:
        render_day(conn, start_of_today, now, show_timeline=True)
    else:
        render_day(conn, start_of_today, now, show_timeline=True)
        render_week(conn, days)

    print(
        "\nNote: browser timing is approximate — derived from snapshots"
        f" polled every ~{POLL_INTERVAL_SEC // 60} min, so precision is ±{POLL_INTERVAL_SEC // 60} min."
    )
    conn.close()


def _parse_days(argv):
    for i, a in enumerate(argv):
        if a == "--days" and i + 1 < len(argv):
            try:
                return max(1, int(argv[i + 1]))
            except ValueError:
                pass
    return 1


if __name__ == "__main__":
    run_work_timeline(_parse_days(sys.argv))
