"""daily_report — build the burnctl daily brief (v4.5.0).

Single source of truth for the `burnctl daily` CLI and the `/api/daily`
endpoint. Returns a structured dict; CLI formats, server.py JSON-serialises.

Never raises. If any data source is missing we return placeholder sections
with `available: False` so the UI can render 'data unavailable' inline.
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

from db import (
    get_conn,
    get_latest_baseline,
    get_previous_baseline,
    get_baseline_readings,
    get_insights,
)

# Baseline cost model — mirrors insights.py (Sonnet input-cache-write mid-band)
_BASELINE_PRICE_PER_TOKEN = 3.0 / 1_000_000
_MONTHLY_SESSIONS = 30


def _pct_delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100.0


def _sum_day_total_tokens(conn, date_str: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM daily_snapshots WHERE date = ?",
        (date_str,),
    ).fetchone()
    return int(row[0] or 0)


def _sum_day_cost(conn, date_str: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(total_cost_usd), 0) FROM daily_snapshots WHERE date = ?",
        (date_str,),
    ).fetchone()
    return float(row[0] or 0.0)


def _window_sum(conn, start_date: str, end_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM daily_snapshots "
        "WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()
    return int(row[0] or 0)


def _baseline_section(latest, prev) -> Dict[str, Any]:
    if not latest:
        return {"available": False, "tokens": 0}
    total = int(latest.get("total_tokens") or 0)
    prev_total = int(prev.get("total_tokens") or 0) if prev else 0
    delta_tokens = total - prev_total if prev else 0
    delta_pct = _pct_delta(total, prev_total) if prev else None
    # Identify added/grown sources vs previous
    prev_map = {s.get("name"): s for s in (prev.get("sources") if prev else [])}
    added: List[Dict[str, Any]] = []
    grown: List[Dict[str, Any]] = []
    for s in latest.get("sources") or []:
        name = s.get("name")
        cur_tokens = int(s.get("tokens") or 0)
        if name not in prev_map:
            added.append({"name": name, "type": s.get("type"), "tokens": cur_tokens})
        else:
            prev_tokens = int((prev_map[name] or {}).get("tokens") or 0)
            if cur_tokens - prev_tokens > 50:  # noise floor
                grown.append({
                    "name": name,
                    "type": s.get("type"),
                    "tokens": cur_tokens,
                    "delta_tokens": cur_tokens - prev_tokens,
                })
    return {
        "available": True,
        "tokens": total,
        "delta_tokens": delta_tokens,
        "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "added_sources": added,
        "grown_sources": grown,
    }


def _runtime_section(conn, today: str, yesterday: str) -> Dict[str, Any]:
    today_tokens = _sum_day_total_tokens(conn, today)
    yday_tokens = _sum_day_total_tokens(conn, yesterday)
    today_cost = _sum_day_cost(conn, today)
    dod_pct = _pct_delta(today_tokens, yday_tokens) if yday_tokens else None
    # WoW: this-7d vs prior-7d
    d = datetime.date.fromisoformat(today)
    this_start = (d - datetime.timedelta(days=6)).isoformat()
    prior_end = (d - datetime.timedelta(days=7)).isoformat()
    prior_start = (d - datetime.timedelta(days=13)).isoformat()
    this_7 = _window_sum(conn, this_start, today)
    prior_7 = _window_sum(conn, prior_start, prior_end)
    wow_pct = _pct_delta(this_7, prior_7) if prior_7 else None
    return {
        "available": True,
        "tokens": today_tokens,
        "dod_pct": round(dod_pct, 2) if dod_pct is not None else None,
        "wow_pct": round(wow_pct, 2) if wow_pct is not None else None,
        "est_cost_usd": round(today_cost, 4),
    }


def _trends_section(conn, readings, runtime) -> Dict[str, Any]:
    """Baseline drift over 7d + DoD + WoW runtime."""
    drift_pct: Optional[float] = None
    if readings and len(readings) >= 2:
        chrono = list(reversed(readings[:7]))
        first = int(chrono[0].get("total_tokens") or 0)
        last = int(chrono[-1].get("total_tokens") or 0)
        if first > 0:
            drift_pct = ((last - first) / first) * 100.0
    return {
        "baseline_drift_7d_pct": round(drift_pct, 2) if drift_pct is not None else None,
        "dod_runtime_pct": runtime.get("dod_pct"),
        "wow_total_pct": runtime.get("wow_pct"),
        "readings_count": len(readings or []),
    }


def _recommendations_section(conn, limit: int = 3) -> List[Dict[str, Any]]:
    """Top N insights, ranked by projected monthly USD saving where available.

    Consumes the existing insights table — never rewrites rule logic.
    """
    try:
        rows = get_insights(conn, account=None, dismissed=0, limit=50)
    except Exception:
        return []
    recs: List[Dict[str, Any]] = []
    for r in rows:
        try:
            detail = json.loads(r["detail_json"]) if r["detail_json"] else {}
        except (ValueError, TypeError):
            detail = {}
        saving_usd = (
            detail.get("usd_monthly")
            or detail.get("delta_usd_monthly")
            or detail.get("estimated_monthly_usd")
            or 0.0
        )
        try:
            saving_usd = float(saving_usd)
        except (TypeError, ValueError):
            saving_usd = 0.0
        recs.append({
            "rank": 0,  # filled after sort
            "insight_id": r["id"],
            "type": r["insight_type"],
            "message": r["message"],
            "saving_usd_monthly": round(saving_usd, 2),
            "action": detail.get("suggested_action"),
            "target": r["project"],
        })
    # Sort by saving descending, tie-break by insight_id asc (older first)
    recs.sort(key=lambda x: (-x["saving_usd_monthly"], x["insight_id"]))
    top = recs[:limit]
    for i, r in enumerate(top, 1):
        r["rank"] = i
    return top


def _last_outcome_section(conn) -> Optional[Dict[str, Any]]:
    """Most recent fix_measurements row with a directional verdict."""
    try:
        row = conn.execute(
            """SELECT fm.id, fm.fix_id, fm.verdict, fm.measured_at,
                      fm.delta_json, f.title, f.fix_type, f.project, f.created_at
               FROM fix_measurements fm
               LEFT JOIN fixes f ON f.id = fm.fix_id
               WHERE fm.verdict IS NOT NULL
               ORDER BY fm.measured_at DESC
               LIMIT 1"""
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        delta = json.loads(row["delta_json"]) if row["delta_json"] else {}
    except (ValueError, TypeError):
        delta = {}
    created_at = row["created_at"] or 0
    measured_at = row["measured_at"] or 0
    days_since = 0
    try:
        days_since = max(0, int((measured_at - created_at) / 86400))
    except Exception:
        pass
    return {
        "fix_id": row["fix_id"],
        "title": row["title"] or "",
        "project": row["project"] or "",
        "verdict": row["verdict"],
        "days_since": days_since,
        "delta": delta,
        "measured_at": measured_at,
    }


def build_daily_brief(conn=None) -> Dict[str, Any]:
    """Return a structured daily brief dict.

    Never raises. Missing sections render with available=False.
    """
    own = conn is None
    if own:
        conn = get_conn()
    try:
        today_dt = datetime.date.today()
        today = today_dt.isoformat()
        yesterday = (today_dt - datetime.timedelta(days=1)).isoformat()

        try:
            latest = get_latest_baseline(conn=conn)
            prev = get_previous_baseline(conn=conn)
            readings = get_baseline_readings(days=14, conn=conn)
        except Exception:
            latest, prev, readings = None, None, []

        baseline = _baseline_section(latest, prev)
        runtime = _runtime_section(conn, today, yesterday)
        trends = _trends_section(conn, readings, runtime)
        recommendations = _recommendations_section(conn, limit=3)
        last_outcome = _last_outcome_section(conn)

        # Trend availability caveat for < 2 days of data
        trend_caveat = None
        if len(readings or []) < 2:
            trend_caveat = "Baseline tracking started — trends available after 2+ days"

        return {
            "date": today,
            "weekday": today_dt.strftime("%A"),
            "baseline": baseline,
            "runtime": runtime,
            "recommendations": recommendations,
            "trends": trends,
            "trend_caveat": trend_caveat,
            "last_outcome": last_outcome,
        }
    finally:
        if own:
            conn.close()
