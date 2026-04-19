"""
fix_measurement.py — causal fix measurement for burnctl
Auto-starts before-snapshot. Requires 10 sessions minimum before reporting delta.
Avoids correlation-as-causation by enforcing session count threshold.

Uses a dedicated table `burnctl_fix_measurements` to avoid colliding with
the legacy `fix_measurements` table (owned by fix_tracker.py).
"""
import sqlite3, time, json


_TABLE = "burnctl_fix_measurements"

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fix_description TEXT NOT NULL,
    project TEXT NOT NULL,
    before_snapshot TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'measuring',
    min_sessions_required INTEGER NOT NULL DEFAULT 10
)
"""


def _ensure_schema(db):
    db.execute(_SCHEMA_SQL)
    db.commit()


def start_fix(fix_description, project, db_path="data/usage.db"):
    db = sqlite3.connect(db_path)
    _ensure_schema(db)
    before = _project_stats(db, project, lookback=20)
    mid = db.execute(
        f"""
        INSERT INTO {_TABLE}
        (fix_description, project, before_snapshot, started_at, status, min_sessions_required)
        VALUES (?,?,?,?,'measuring',10)
        """,
        (fix_description, project, json.dumps(before), int(time.time()))
    ).lastrowid
    db.commit()
    print(f"✓ Measurement #{mid} started for '{project}'")
    print(f"  Before baseline: {before['avg_tokens']:,} tokens/session avg ({before['session_count']} sessions)")
    print(f"  Apply your fix now.")
    print(f"  Run after 10+ sessions: burnctl fix result {mid}")
    return mid


def check_fix(measurement_id, db_path="data/usage.db"):
    db = sqlite3.connect(db_path)
    _ensure_schema(db)
    row = db.execute(
        f"""
        SELECT fix_description, project, before_snapshot, started_at, min_sessions_required
        FROM {_TABLE} WHERE id=?
        """,
        (measurement_id,)
    ).fetchone()
    if not row:
        print(f"Measurement #{measurement_id} not found")
        return
    desc, project, before_json, started_at, min_req = row
    before = json.loads(before_json)
    after = _project_stats(db, project, since_ts=started_at)

    if after["session_count"] < min_req:
        print(f"Need {min_req - after['session_count']} more sessions (have {after['session_count']}, need {min_req})")
        print("Statistical noise threshold not met yet — come back later")
        return

    before_avg = before["avg_tokens"]
    after_avg = after["avg_tokens"]
    if before_avg == 0:
        print("No baseline data found")
        return

    delta_pct = ((before_avg - after_avg) / before_avg) * 100

    print(f"\n=== Fix Result #{measurement_id}: {desc} ===")
    print(f"Project: {project}")
    print(f"Sessions measured: {after['session_count']} (minimum: {min_req})")
    print(f"Before: {before_avg:,} tokens/session")
    print(f"After:  {after_avg:,} tokens/session")
    if delta_pct > 5:
        print(f"✅ Improved: {delta_pct:.1f}% token reduction")
    elif delta_pct < -5:
        print(f"⚠️  Regression: {abs(delta_pct):.1f}% token increase")
    else:
        print(f"→ No significant change (within ±5% noise threshold)")


def _project_stats(db, project, lookback=None, since_ts=None):
    if since_ts:
        rows = db.execute(
            "SELECT input_tokens+output_tokens, cost_usd FROM sessions "
            "WHERE project LIKE ? AND timestamp>? ORDER BY timestamp DESC",
            (f"%{project}%", since_ts)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT input_tokens+output_tokens, cost_usd FROM sessions "
            "WHERE project LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{project}%", lookback or 20)
        ).fetchall()
    if not rows:
        return {"avg_tokens": 0, "session_count": 0}
    tokens = [r[0] or 0 for r in rows]
    return {
        "avg_tokens": int(sum(tokens)/len(tokens)),
        "session_count": len(rows)
    }
