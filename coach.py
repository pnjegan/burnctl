"""burnctl coach — F1: in-workflow habit teaching grounded in measured waste_events.

A single session-end (NOT per-turn) one-liner. Reuses the existing waste_events
detections (waste_patterns.py); pairs each recurring pattern with a short plain-English
teaching grounded in a real count. Celebration-first: an improving or clean trend is
recognized before any habit is flagged.

Discipline:
  - NO LLM, no network, no live model — one aggregate SQLite read, deterministic text.
  - Teach on PATTERN (N distinct sessions over a window), never a single instance.
  - Display-only: returns a string; never blocks, compacts, or auto-clears.
  - Silenceable via BURNCTL_COACH_SILENT.
"""
import os
import sqlite3
import time

from burn_rate import resolve_db_path, DB_DEFAULT

# Detection -> teaching. {n} = distinct sessions exhibiting the pattern; {proj} = project.
# Each rendered line (incl. the 💡 prefix) stays <= ~140 chars for glanceability.
TEACHING = {
    "deep_no_compact": "deep sessions without /compact in {n} recent {proj} sessions — split big tasks and /clear at natural seams.",
    "repeated_reads":  "same file re-read 3+x across {n} {proj} sessions — keep it open or note the path to skip re-reads.",
    "cost_outlier":    "{n} {proj} sessions cost >3x your project avg — watch for runaway loops or oversized context.",
    "floundering":     "same tool fired 4+x in a row across {n} {proj} sessions — pause, re-read the error, switch approach.",
    "cost_anomaly":    "{n} {proj} sessions ran hot vs your baseline — review recent prompts for scope creep.",
}

PATTERN_THRESHOLD = 3   # >= N distinct sessions in the window = a habit, not an instance
WINDOW_DAYS = 30        # lookback window
CELEBRATE_HALF = 15     # compare last 15d vs prior 15d to detect an improving trend


def _silenced():
    """True if the user opted out (BURNCTL_COACH_SILENT=1/true)."""
    return os.environ.get("BURNCTL_COACH_SILENT", "").strip().lower() not in ("", "0", "false")


def coach_line(project, db_path=DB_DEFAULT, now=None):
    """Return one session-end teaching/celebration line, or '' if there's nothing to say.

    Deterministic and cheap: a single aggregate query over waste_events. No LLM,
    no network. Safe to call once per session (not per-turn).
    """
    if _silenced():
        return ""
    if not project:
        return ""
    now = int(now if now is not None else time.time())
    since = now - WINDOW_DAYS * 86400
    mid = now - CELEBRATE_HALF * 86400

    path = resolve_db_path(db_path)
    if not path or not os.path.exists(str(path)):
        return ""

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT pattern_type, "
            "       COUNT(DISTINCT session_id) AS n, "
            "       SUM(CASE WHEN detected_at >= ? THEN 1 ELSE 0 END) AS recent, "
            "       SUM(CASE WHEN detected_at <  ? THEN 1 ELSE 0 END) AS prior "
            "FROM waste_events "
            "WHERE project = ? AND detected_at >= ? "
            "GROUP BY pattern_type",
            (mid, mid, project, since),
        ).fetchall()
    finally:
        conn.close()

    # No waste at all in the window — celebrate a clean run.
    if not rows:
        return f"✅ {project}: no recurring waste pattern in {WINDOW_DAYS}d — clean sessions."

    # Patterns that recur enough to be a habit, strongest first.
    habits = sorted((r for r in rows if r["n"] >= PATTERN_THRESHOLD), key=lambda r: -r["n"])

    if habits:
        top = habits[0]
        # Celebration-first: improving trend on the dominant habit.
        if top["prior"] and top["recent"] is not None and top["recent"] < top["prior"]:
            return (f"\U0001F389 {project}: {top['pattern_type']} down "
                    f"{top['prior']}→{top['recent']} sessions vs prior {CELEBRATE_HALF}d "
                    f"— habit improving.")
        tmpl = TEACHING.get(top["pattern_type"])
        if tmpl:
            return "\U0001F4A1 " + tmpl.format(n=top["n"], proj=project)

    # Some waste, but nothing crossed the habit threshold — steady, not a nag.
    return f"✅ {project}: no habit crossed {PATTERN_THRESHOLD}+ sessions in {WINDOW_DAYS}d — steady."
