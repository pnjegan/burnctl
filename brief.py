"""burnctl brief — proactive, cross-day, per-project usage brief.

A brief that comes to you, rather than a dashboard you poll. It groups the
existing per-project-day snapshots by project, builds a robust baseline from the
prior days in range, and flags a project whose burn *today* is a genuine anomaly.

Design seam: ``UsageSource`` is the one interface a future hook/OTEL source
would implement. ``SnapshotUsageSource`` is the only adapter built here — it
wraps the already-normalized ``daily_snapshots`` model (``db.get_daily_snapshots``).
No data migration; the snapshot rows ARE the normalized record.

Anomaly method mirrors ``waste_patterns._detect_cost_anomalies`` rule r1: robust
``median + K*MAD``, applied at the project-DAY grain (not per-session). It never
enforces — it surfaces flags + evidence only.
"""

import statistics

from db import get_daily_snapshots

# ── Tunables (approved STATE 2/3) ──────────────────────────────────────────
BRIEF_MAD_K = 5.0            # today_cost > median + K*MAD(prior days) -> anomaly.
                            # 5.0 (vs r1's 8.0): daily grain leans sensitive.
BRIEF_MIN_COST_FLOOR = 1.0  # AND today_cost >= $1 — stops trivial $0.01->$0.05.
BRIEF_MIN_PRIOR_DAYS = 3    # need >=3 prior days in range, else the flag is skipped.

# ── Attribution thresholds (heuristic; daily_snapshots fields ONLY) ─────────
_CACHE_DROP_PP = 10.0       # cache-hit rate fell >=10 percentage points vs prior median
_SESSION_SPIKE_MULT = 1.5   # session_count >= 1.5x prior median
_TPS_SPIKE_MULT = 1.5       # tokens-per-session >= 1.5x prior median


class UsageSource:
    """Seam for a future hook/OTEL source. ONE method: normalized
    per-project-day usage records for a date range, account-scoped."""

    def daily_records(self, days, account="all"):
        raise NotImplementedError


class SnapshotUsageSource(UsageSource):
    """The only adapter built here — wraps the existing parser's output
    (``db.daily_snapshots``). The snapshot rows are already the normalized
    model, so this is a thin, migration-free wrap."""

    def __init__(self, conn):
        self.conn = conn

    def daily_records(self, days, account="all"):
        return [dict(r) for r in get_daily_snapshots(self.conn, account, days)]


def _median(xs):
    return statistics.median(xs) if xs else 0.0


def _tokens_per_session(r):
    return r["total_tokens"] / r["session_count"] if r["session_count"] else 0.0


def _attribute(today_row, prior_rows):
    """Top contributing cause for a flagged project, from daily_snapshots fields
    ONLY. Heuristic. Model-mix is deferred (it needs a sessions join)."""
    candidates = []

    # Each candidate carries a NORMALIZED score (dimensionless fractional
    # deviation) so the three causes are ranked on the same scale — a raw
    # percentage-point drop is not comparable to a raw session-count ratio.

    # cache-hit drop — normalized as fraction of the prior baseline
    prior_cache = [r["cache_hit_rate"] for r in prior_rows]
    if prior_cache:
        base = _median(prior_cache)
        drop = base - today_row["cache_hit_rate"]
        if drop >= _CACHE_DROP_PP:
            score = drop / base if base > 0 else drop
            candidates.append((score, {
                "kind": "cache_hit_drop",
                "from": round(base, 1),
                "to": round(today_row["cache_hit_rate"], 1),
                "unit": "pct_points",
                "heuristic": True,
            }))

    # session-count spike — normalized as (ratio - 1)
    base_sc = _median([r["session_count"] for r in prior_rows])
    if base_sc > 0 and today_row["session_count"] >= _SESSION_SPIKE_MULT * base_sc:
        candidates.append((today_row["session_count"] / base_sc - 1, {
            "kind": "session_count_spike",
            "from": base_sc,
            "to": today_row["session_count"],
            "unit": "sessions",
            "heuristic": True,
        }))

    # tokens-per-session jump — normalized as (ratio - 1)
    base_tps = _median([_tokens_per_session(r) for r in prior_rows if r["session_count"]])
    today_tps = _tokens_per_session(today_row)
    if base_tps > 0 and today_tps >= _TPS_SPIKE_MULT * base_tps:
        candidates.append((today_tps / base_tps - 1, {
            "kind": "tokens_per_session_jump",
            "from": round(base_tps),
            "to": round(today_tps),
            "unit": "tokens_per_session",
            "heuristic": True,
        }))

    if not candidates:
        return None
    # Top cause = largest normalized deviation; tie-break on kind for determinism.
    candidates.sort(key=lambda c: (c[0], c[1]["kind"]), reverse=True)
    return candidates[0][1]


def brief(records, today, k=BRIEF_MAD_K):
    """PURE. No I/O, no clock — ``today`` ('YYYY-MM-DD', UTC) is passed in.

    ``records``: normalized per-project-day dicts (see ``UsageSource``).

    Returns ``{"generated_for": today, "projects": [ProjectBrief, ...]}`` where
    each ProjectBrief is ``{project, account, tokens, cost, cache_pct, baseline,
    robust_score, anomaly, cause?}``. Deterministic: identical input yields
    byte-identical output (projects sorted; floats rounded)."""
    by_project = {}
    for r in records:
        by_project.setdefault((r["account"], r["project"]), []).append(r)

    projects = []
    for (account, project), rows in by_project.items():
        today_rows = [r for r in rows if r["date"] == today]
        prior_rows = [r for r in rows if r["date"] < today]

        if today_rows:
            tr = today_rows[0]
            tokens = tr["total_tokens"]
            cost = tr["total_cost_usd"]
            cache_pct = tr["cache_hit_rate"]
        else:
            tr = None
            tokens = 0
            cost = 0.0
            cache_pct = 0.0

        prior_costs = [r["total_cost_usd"] for r in prior_rows]
        baseline = _median(prior_costs)

        anomaly = False
        robust_score = 0.0
        cause = None
        if len(prior_rows) >= BRIEF_MIN_PRIOR_DAYS:
            med = statistics.median(prior_costs)
            mad = statistics.median([abs(x - med) for x in prior_costs]) or 1e-9
            robust_score = (cost - med) / mad
            if robust_score > k and cost >= BRIEF_MIN_COST_FLOOR:
                anomaly = True
                if tr is not None:
                    cause = _attribute(tr, prior_rows)

        pb = {
            "project": project,
            "account": account,
            "tokens": tokens,
            "cost": round(cost, 2),
            "cache_pct": round(cache_pct, 1),
            "baseline": round(baseline, 2),
            "robust_score": round(robust_score, 1),
            "anomaly": anomaly,
        }
        if cause is not None:
            pb["cause"] = cause
        projects.append(pb)

    projects.sort(key=lambda p: (p["account"], p["project"]))
    return {"generated_for": today, "projects": projects}
