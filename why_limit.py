"""burnctl why-limit — explain the current 5-hour window usage.

Answers "why is my session-limit X% used right now?" by reading the last 5
hours of `sessions`, `waste_events`, and the JSONL tool-call stream. Output
is a single-screen breakdown: where the tokens went, which files were
re-read, an estimated waste figure, and three concrete fix options.

Honesty rules (do not regress):
- Private project names are masked as "Project N" by default. Pass
  --reveal to show actual labels (intended for the owner of the DB, not
  for screenshots or blog posts).
- File paths in the JSONL are stripped to basename for display so
  repeated-reads never leak a real filesystem path.
- Sub-agents are split out explicitly — they're a known attribution
  source Claude Code's UI does not show.
- If no sessions in the window, say so and stop (do not invent anything).

No hardcoded paths: uses the same two-candidate resolver as
overhead_audit.py::load_db().
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


IST = timezone(timedelta(hours=5, minutes=30))


FIVE_HOURS_SEC = 5 * 3600
READ_BYTES_PER_TOKEN = 4              # rough tiktoken floor, matches overhead_audit
TOP_READ_FILES_SHOWN = 10
SONNET_INPUT_PER_TOKEN = 3.0 / 1_000_000  # cost-estimate mid-band


# ─────────────────────────────────────────────────────────
# DB + project-name handling
# ─────────────────────────────────────────────────────────

def load_db():
    """Same two-candidate pattern as overhead_audit.py::load_db()."""
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


# Known-private names live alongside the maintainer-leak patterns in the
# .burnctlignore convention. We reuse the same loader so both checks stay
# in sync. Default: mask the names currently in the maintainer's live DB.
_DEFAULT_PRIVATE_NAMES = (
    "Tidify", "Claudash", "Brainworks", "WikiLoop",
    "CareerOps", "Knowl",
)


def _load_private_names():
    """Load additional private names from .burnctlignore-private.

    One name per line, comments with `#`. Falls back to the baked-in list
    when the file doesn't exist. Combined with defaults."""
    repo = os.path.dirname(os.path.abspath(__file__))
    f = os.path.join(repo, ".burnctlignore-private")
    extra = []
    if os.path.isfile(f):
        try:
            with open(f, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        extra.append(line)
        except OSError:
            pass
    return tuple(set(_DEFAULT_PRIVATE_NAMES) | set(extra))


def _mask_project(name, mask_map, reveal):
    """Return display label. Masks known-private names to 'Project N'."""
    if reveal:
        return name or "Unknown"
    if not name:
        return "Unknown"
    private = _load_private_names()
    if name in private:
        if name not in mask_map:
            mask_map[name] = f"Project {len(mask_map) + 1}"
        return mask_map[name]
    if name == "Other" or name == "Unknown":
        return "Browser / Unmatched"
    return name


def _display_project_sql():
    """Project column expression that prefers inferred_project when set.
    Scanner may populate inferred_project for Other/empty rows; fall back
    to plain project. Safe even if the migrated column doesn't exist yet
    (we inspect before using)."""
    return "COALESCE(NULLIF(TRIM(inferred_project), ''), project)"


def _inferred_project_exists(conn):
    try:
        row = conn.execute(
            "SELECT 1 FROM pragma_table_info('sessions') WHERE name='inferred_project'"
        ).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False


# ─────────────────────────────────────────────────────────
# Aggregates for the current 5-hour window
# ─────────────────────────────────────────────────────────

def per_project_split(conn, cutoff, has_inferred):
    """Return list of (display_project, sessions, turns, tokens, cost)
    for is_subagent=0, plus a separate sub-agent aggregate row."""
    proj_expr = _display_project_sql() if has_inferred else "project"
    rows = conn.execute(
        f"""
        SELECT
          {proj_expr} AS display_project,
          COUNT(DISTINCT session_id) AS sessions,
          COUNT(*) AS turns,
          COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0)
            AS tokens,
          COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM sessions
        WHERE timestamp >= ? AND (is_subagent = 0 OR is_subagent IS NULL)
        GROUP BY display_project
        ORDER BY tokens DESC
        """,
        (cutoff,),
    ).fetchall()
    sub_row = conn.execute(
        """
        SELECT
          COUNT(DISTINCT session_id) AS sessions,
          COUNT(*) AS turns,
          COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0)
            AS tokens,
          COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM sessions
        WHERE timestamp >= ? AND is_subagent = 1
        """,
        (cutoff,),
    ).fetchone()
    return rows, sub_row


def repeated_reads_events(conn, cutoff, has_inferred):
    """Count repeated_reads waste events detected in the window.

    Note: waste_events has only a `project` column (no inferred_project).
    We select plain project here; display-layer masking still happens
    via _mask_project() in render().
    """
    rows = conn.execute(
        """
        SELECT
          project AS display_project,
          COUNT(*) AS n,
          COALESCE(SUM(token_cost), 0.0) AS attr_cost
        FROM waste_events
        WHERE detected_at >= ? AND pattern_type = 'repeated_reads'
        GROUP BY project
        """,
        (cutoff,),
    ).fetchall()
    return rows


# ─────────────────────────────────────────────────────────
# JSONL scan: top re-read files in the window
# ─────────────────────────────────────────────────────────

def _iter_tool_calls(path):
    """Yield (tool_name, input_dict) for every assistant tool_use block
    in a JSONL file. Same shape as waste_patterns._iter_assistant_tool_calls
    but inlined here to keep why_limit.py standalone."""
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name") or ""
                    inp = block.get("input") or {}
                    if isinstance(inp, dict):
                        yield name, inp
    except OSError:
        return


def top_reread_files(cutoff):
    """Scan ~/.claude/projects/**/*.jsonl touched since cutoff and count
    Read() calls per basename. Returns top N with counts + byte-estimate."""
    base = os.path.expanduser("~/.claude/projects/")
    reads = Counter()
    file_bytes = {}
    if not os.path.isdir(base):
        return []
    for jsonl in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(jsonl) < cutoff:
                continue
        except OSError:
            continue
        for name, inp in _iter_tool_calls(jsonl):
            if name != "Read":
                continue
            path = inp.get("file_path") or inp.get("path") or inp.get("filename")
            if not path:
                continue
            base_name = os.path.basename(str(path))
            reads[base_name] += 1
            # Keep best known size for estimating wasted tokens
            if base_name not in file_bytes:
                try:
                    file_bytes[base_name] = os.path.getsize(str(path))
                except OSError:
                    file_bytes[base_name] = 0

    rows = []
    for fname, count in reads.most_common(TOP_READ_FILES_SHOWN):
        if count < 2:
            continue
        size = file_bytes.get(fname, 0) or 0
        tokens_per_read = max(size // READ_BYTES_PER_TOKEN, 0)
        wasted = (count - 1) * tokens_per_read  # first read is necessary
        rows.append({
            "name": fname,
            "count": count,
            "tokens_per_read": tokens_per_read,
            "wasted": wasted,
        })
    return rows


# ─────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────

def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n:,}"
    return f"{n:,}"


def _rule():
    return "─" * 61


def _resolve_fix_id(conn):
    """Best-available fix_id for repeated_reads, status in measuring/proposed.
    Falls back to the newest repeated_reads fix regardless of status."""
    for status in ("measuring", "proposed", "applied", "confirmed"):
        row = conn.execute(
            "SELECT id FROM fixes WHERE waste_pattern='repeated_reads' "
            "AND status=? ORDER BY id DESC LIMIT 1",
            (status,),
        ).fetchone()
        if row:
            return row[0]
    row = conn.execute(
        "SELECT id FROM fixes WHERE waste_pattern='repeated_reads' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


ACCOUNT_LABELS = {
    "personal_max": "Max (personal_max)",
    "work_pro": "Pro (work_pro)",
}


def _fmt_duration(mins):
    if mins is None:
        return "0min"
    mins = int(round(mins))
    if mins < 60:
        return f"{mins}min"
    h = mins // 60
    m = mins % 60
    return f"{h}h {m:02d}m" if m else f"{h}h"


def _render_browser_health():
    """Print the v4.3.0 'Browser Session Health' section. Silent on error."""
    try:
        from browser_sessions import get_browser_summary
    except ImportError:
        return

    try:
        summary = get_browser_summary()
    except Exception:
        return

    accounts = summary.get("accounts") or {}
    combined = summary.get("combined") or {}

    print()
    print(" === Browser Session Health ===")

    if not accounts:
        print(" Browser session data: collecting... (no snapshots yet)")
        return

    # Thin-data guard per-account: if ANY account has < 3 sessions, mark it
    # collecting rather than printing dubious numbers.
    for aid, data in accounts.items():
        label = ACCOUNT_LABELS.get(aid, aid)
        print(f" Account: {label}")
        if data.get("thin_data"):
            print(
                f"   Browser session data: collecting... "
                f"(need 3+ sessions for analysis, have {data['sessions_today'] + 0})"
            )
            print()
            continue

        if data["flagged"]:
            badge = "⚠️ flagged"
        elif data["longest_session_min"] > LONG_BROWSER_SESSION_MIN:
            badge = "⚠️ long"
        else:
            badge = "✅ healthy"
        print(
            f"   Today:     {data['sessions_today']} sessions  "
            f"avg {_fmt_duration(data['avg_duration_min'])}  "
            f"longest {_fmt_duration(data['longest_session_min'])}  {badge}"
        )
        print(
            f"   Est. cost today: ~${data['total_cost_est_today']:.2f}"
            f"  |  This week: ~${data['total_cost_est_week']:.2f}"
        )

        if data["longest_session_min"] > LONG_BROWSER_SESSION_MIN:
            print()
            print(
                f"   ⚠️  Long session detected "
                f"({_fmt_duration(data['longest_session_min'])})"
            )
            print("   Every message re-reads entire conversation history.")
            print("   Estimated 3-5x cost vs 30-min focused sessions.")
            print("   → Start fresh conversation when switching tasks.")
        print()

    # Combined cost comparison
    b_week = combined.get("browser_cost_week", 0)
    cc_week = combined.get("cc_cost_week", 0)
    total_week = b_week + cc_week
    if total_week > 0:
        b_pct = b_week / total_week * 100
        cc_pct = cc_week / total_week * 100
        print(" Combined this week:")
        print(f"   Browser:     ~${b_week:>7.2f}  ({b_pct:.0f}%)")
        print(f"   Claude Code: ~${cc_week:>7.2f}  ({cc_pct:.0f}%)")
        print(f"   " + "─" * 25)
        print(f"   Total est.:  ~${total_week:>7.2f}")
        print()
        if combined.get("window_note"):
            print(f"   Note: {combined['window_note']}")
        print(" Note: Browser costs are estimates from window % deltas.")
        print(" Claude Code costs are exact from JSONL session data.")
        if summary.get("granularity_note"):
            print(f" {summary['granularity_note']}")


LONG_BROWSER_SESSION_MIN = 60


def _render_recent_browser_chats(conn):
    """Print the v4.4.0 'Recent Browser Chats' section.

    Reads browser_chat_sessions (populated by Mac-side chat_title_sync.py).
    Groups by account, shows the most recent 10 chats per account within
    the last 3 days. Duration = first→last page visit — an under-estimate
    (we don't see per-message timing). Flags:
      > 120 min  ⚠️  (context bloat risk)
      > 60 min   ⚠️  (long session)
      ≤ 60 min   ✅
    Silent if the table is empty (prints a one-line hint to run the
    Mac collector).
    """
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='browser_chat_sessions'"
        )
        if not cur.fetchone()[0]:
            return  # table absent — old DB, silent no-op
    except sqlite3.Error:
        return

    cutoff = int(time.time()) - 3 * 24 * 3600
    try:
        rows = conn.execute(
            """
            WITH ranked AS (
              SELECT title, account, first_visit, duration_min,
                     ROW_NUMBER() OVER (
                       PARTITION BY account
                       ORDER BY first_visit DESC
                     ) AS rn
              FROM browser_chat_sessions
              WHERE first_visit > ?
            )
            SELECT title, account, first_visit, duration_min
            FROM ranked
            WHERE rn <= 10
            ORDER BY account, first_visit DESC
            """,
            (cutoff,),
        ).fetchall()
    except sqlite3.Error:
        return

    print()
    print(" === Recent Browser Chats (last 3 days) ===")

    if not rows:
        print(" No chat titles yet — run chat_title_sync.py on your Mac.")
        return

    # Account label lookup — friendly "Plan (account_id)" where possible.
    # load_db() uses default row_factory (tuples), so index positionally.
    labels = {}
    try:
        for aid, plan in conn.execute("SELECT account_id, plan FROM accounts"):
            if aid:
                labels[aid] = f"{(plan or 'unknown').title()} ({aid})"
    except sqlite3.Error:
        pass

    grouped = defaultdict(list)
    for row in rows:
        title, account, first_visit, duration_min = row
        grouped[account].append((title, first_visit, duration_min))

    for account in sorted(grouped.keys()):
        label = labels.get(account, account)
        print()
        print(f" Account: {label}")
        for title, first_visit, duration_min in grouped[account]:
            dt_ist = datetime.fromtimestamp(first_visit, tz=IST)
            ts = dt_ist.strftime("%m-%d %H:%M")
            dur = _fmt_duration(duration_min)
            if duration_min > 120:
                flag = "⚠️ "
                note = "  context bloat risk"
            elif duration_min > 60:
                flag = "⚠️ "
                note = "  long session"
            else:
                flag = "✅ "
                note = ""
            safe_title = (title or "").strip().replace('"', "'")
            if len(safe_title) > 60:
                safe_title = safe_title[:57] + "..."
            print(f"   {ts} IST  {dur:>8}  {flag} \"{safe_title}\"{note}")


def render(reveal=False):
    conn = load_db()
    if conn is None:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return 0

    has_inferred = _inferred_project_exists(conn)
    now = int(time.time())
    cutoff = now - FIVE_HOURS_SEC
    window_start = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    window_end = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows, sub_row = per_project_split(conn, cutoff, has_inferred)
    total_tokens = sum(r[3] or 0 for r in rows) + (sub_row[2] or 0 if sub_row else 0)

    print()
    print(_rule())
    print(f" Your 5-hour window — {window_end}")
    print(f" window-start: {window_start}")
    print(_rule())

    if total_tokens == 0 and (not rows and (sub_row is None or (sub_row[1] or 0) == 0)):
        print()
        print(" No Claude Code activity in current window.")
        print(" Your limit may have reset. Run again after starting a session.")
        print()
        conn.close()
        return 0

    print()
    print(f" TOKENS USED THIS WINDOW: {_fmt_tokens(total_tokens)}")
    print()
    print(" WHERE IT WENT:")
    header = "┌──────────────────────┬──────────┬───────────────┬──────────┐"
    sep    = "├──────────────────────┼──────────┼───────────────┼──────────┤"
    footer = "└──────────────────────┴──────────┴───────────────┴──────────┘"
    print(f" {header}")
    print(f" │ {'Project':<20} │ {'Sessions':>8} │ {'Tokens':>13} │ {'Cost':>8} │")
    print(f" {sep}")
    mask_map = {}
    for r in rows:
        proj, sess, turns, tokens, cost = r
        display = _mask_project(proj, mask_map, reveal)
        print(
            f" │ {display[:20]:<20} │ {sess or 0:>8} │ "
            f"{_fmt_tokens(int(tokens or 0)):>13} │ ${cost or 0:>7.2f} │"
        )
    if sub_row and (sub_row[0] or 0) > 0:
        print(
            f" │ {'Sub-agents':<20} │ {sub_row[0] or 0:>8} │ "
            f"{_fmt_tokens(int(sub_row[2] or 0)):>13} │ ${sub_row[3] or 0:>7.2f} │"
        )
    else:
        print(
            f" │ {'Sub-agents':<20} │ {0:>8} │ {_fmt_tokens(0):>13} │ ${0:>7.2f} │"
        )
    print(f" {footer}")

    # "Other" / unmatched note
    unmatched_here = any(
        _mask_project(r[0], {}, reveal) == "Browser / Unmatched" for r in rows
    )
    if unmatched_here:
        print()
        print(" Note: 'Browser / Unmatched' means the session path could not be")
        print(" attributed to a known project. Run burnctl from the same machine")
        print(" as Claude Code for full project attribution.")

    # Why it happened — waste events in window + filename detail
    waste_rows = repeated_reads_events(conn, cutoff, has_inferred)
    file_rows = top_reread_files(cutoff)

    if waste_rows or file_rows:
        total_waste_events = sum(r[1] for r in waste_rows)
        print()
        print(" WHY IT HAPPENED:")
        if total_waste_events > 0:
            print(f" ⚠️  repeated_reads: {total_waste_events} events this window")
        elif file_rows:
            print(f" ⚠️  Files re-read in this window ({len(file_rows)} files)")

        if file_rows:
            print()
            print(" Files read multiple times this window:")
            for fr in file_rows:
                est = fr["wasted"]
                print(
                    f"   {fr['name'][:30]:<30} read {fr['count']}x   "
                    f"~{_fmt_tokens(est)} tokens wasted"
                )
            total_wasted = sum(r["wasted"] for r in file_rows)
            wasted_usd = total_wasted * SONNET_INPUT_PER_TOKEN
            print()
            print(
                f" Estimated repeated-read waste: "
                f"~{_fmt_tokens(total_wasted)} tokens ≈ ${wasted_usd:.2f}"
            )

        print()
        print(" Root cause (pick most likely):")
        print(" → Long session without /compact — Claude forgot what it read")
        print(" → 5-min cache TTL — cache busting on every short break")
        print(" → Sub-agent spawning same context repeatedly")

    # Browser session health (v4.3.0)
    _render_browser_health()

    # Recent browser chat titles (v4.4.0 — populated by Mac-side collector)
    _render_recent_browser_chats(conn)

    # Fix options
    print()
    print(" WHAT TO FIX:")
    fix_id = _resolve_fix_id(conn)
    if fix_id is not None:
        print(
            f" 1. burnctl fix apply {fix_id}   ← applies repeated_reads CLAUDE.md rule"
        )
    else:
        print(
            " 1. burnctl audit  ← surface a repeated_reads fix first, then fix apply <id>"
        )
    print(" 2. Use /compact at 60% context (not 95%)")
    print(" 3. Run: burnctl resume-audit  ← check if TTL is the cause")
    print()
    print(_rule())
    print()
    conn.close()
    return 0


def main():
    reveal = "--reveal" in sys.argv
    return render(reveal=reveal)


if __name__ == "__main__":
    sys.exit(main())
