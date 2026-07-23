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

import math
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


def robust_score(cost, prior_costs):
    """PURE, math-only. Robust z-score of LOG-SCALED cost:
    ``(log1p(cost) - median(log1p(prior))) / MAD(log1p(prior))``, MAD floored at
    1e-9 so a zero-spread prior never divides by zero.

    Why log (FIX-DETECTOR): daily cost is right-skewed and multiplicative — an
    active-work day is many× an idle day — so a raw ``(cost - median)/MAD`` score
    produced a fat tail no k could threshold (calibration over 310 project-days:
    even k=8 flagged 11%+, p99≈117). ``log1p`` compresses that skew so a k lands
    in the 2–5% target band. It also handles ``cost == 0`` (``log1p(0) == 0``), so
    no separate zero/divide guard is needed beyond the MAD floor; ``max(0.0, x)``
    guards against any stray negative cost.

    The single source of the robust-score math — both the live ``brief()`` path
    and ``calibrate()`` call this, so a threshold tuned by calibrate scores
    project-days identically to how the brief will flag them.

    Precondition: ``prior_costs`` is non-empty. Callers apply the
    ``BRIEF_MIN_PRIOR_DAYS`` (>=3) guard before calling."""
    def _log(x):
        return math.log1p(max(0.0, x))
    lc = _log(cost)
    lp = [_log(c) for c in prior_costs]
    med = statistics.median(lp)
    mad = statistics.median([abs(x - med) for x in lp]) or 1e-9
    return (lc - med) / mad


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
    movement, robust_score, anomaly, cause?}``. ``movement`` is today's cost as a
    ratio of the prior-day median (``None`` when there is no baseline). Projects
    are sorted by today's cost descending (biggest burner first). Deterministic:
    identical input yields byte-identical output (floats rounded)."""
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

        # Movement: today's cost vs the project's typical prior day (raw prior
        # median — STATE-1 diagnostic found only 2.6% idle days, so an active-day
        # filter changes movement for ~1/10 projects and is not worth the
        # complexity). Descriptive, not a verdict. Computed from the SAME rounded
        # baseline the reader sees (``baseline_disp``) so "×N vs typical" is always
        # hand-checkable against the displayed baseline, and a sub-cent baseline
        # (rounds to 0.00) reads "no baseline" instead of an absurd unexplained
        # ratio. ``None`` when there is no positive baseline → no divide-by-zero,
        # no fabricated ratio. ``max(0.0, cost)`` mirrors robust_score's guard
        # against a stray negative cost (a "×-0.5" would be meaningless here).
        baseline_disp = round(baseline, 2)
        movement = (round(max(0.0, cost) / baseline_disp, 2)
                    if baseline_disp > 0 else None)

        anomaly = False
        score = 0.0
        cause = None
        if len(prior_rows) >= BRIEF_MIN_PRIOR_DAYS:
            score = robust_score(cost, prior_costs)
            if score > k and cost >= BRIEF_MIN_COST_FLOOR:
                anomaly = True
                if tr is not None:
                    cause = _attribute(tr, prior_rows)

        pb = {
            "project": project,
            "account": account,
            "tokens": tokens,
            "cost": round(cost, 2),
            "cache_pct": round(cache_pct, 1),
            "baseline": baseline_disp,
            "movement": movement,
            "robust_score": round(score, 1),
            "anomaly": anomaly,
        }
        if cause is not None:
            pb["cause"] = cause
        projects.append(pb)

    # Descriptive-first: biggest burners today lead, so "where did my tokens go?"
    # is answered by the first row. Tie-break on (account, project) for a stable,
    # deterministic order.
    projects.sort(key=lambda p: (-p["cost"], p["account"], p["project"]))
    return {"generated_for": today, "projects": projects}


# ── calibration (read-only threshold grounding) ─────────────────────────────
CALIBRATE_K_CANDIDATES = (3, 4, 5, 6, 8)
CALIBRATE_TARGET_RATE = 0.03   # center of the 2-5% target band; suggest k closest to it
CALIBRATE_BAND = (0.02, 0.05)  # in_band iff suggested k's flag_rate lands in [2%, 5%]


def _percentile(sorted_scores, p):
    """Nearest-rank percentile on an ascending-sorted list. idx = ceil(p/100*N)-1.
    Deterministic and hand-checkable. ``sorted_scores`` must be non-empty."""
    import math
    n = len(sorted_scores)
    idx = max(0, min(n - 1, math.ceil(p / 100.0 * n) - 1))
    return sorted_scores[idx]


def calibrate(records, *, k_candidates=CALIBRATE_K_CANDIDATES,
              floor=BRIEF_MIN_COST_FLOOR, min_prior=BRIEF_MIN_PRIOR_DAYS,
              current_k=BRIEF_MAD_K):
    """PURE. Retrospectively score EVERY qualifying project-day in ``records``
    using the SAME ``robust_score`` + prior-window semantics as the live brief,
    then report the score distribution + per-k flag-rate + a SUGGESTED k.

    SUGGESTS ONLY — mutates nothing (no config, no DB). ``records`` are the
    normalized per-project-day dicts ``brief()`` consumes.

    A project-day qualifies when it has >= ``min_prior`` strictly-earlier days
    (identical to brief's ``prior_rows = days < today``). Flag condition is the
    live one: ``score > k AND cost >= floor``.

    Returns a machine-readable dict; ``status='insufficient'`` (suggested_k=None)
    when no project-day clears the guard — never a bogus k."""
    by_project = {}
    for r in records:
        by_project.setdefault((r["account"], r["project"]), []).append(r)

    scored = []            # (score, cost) for every qualifying project-day
    insufficient_projects = []
    for (account, project), rows in by_project.items():
        rows = sorted(rows, key=lambda r: r["date"])
        qualifying_here = 0
        for i, row in enumerate(rows):
            prior_costs = [rows[j]["total_cost_usd"] for j in range(i)]
            if len(prior_costs) >= min_prior:
                scored.append((robust_score(row["total_cost_usd"], prior_costs),
                               row["total_cost_usd"]))
                qualifying_here += 1
        if qualifying_here == 0:
            insufficient_projects.append({"account": account, "project": project,
                                          "days": len(rows)})

    total = len(scored)
    if total == 0:
        return {
            "status": "insufficient",
            "reason": f"no project-day has >= {min_prior} prior days in range",
            "qualifying_project_days": 0,
            "insufficient_projects": sorted(
                insufficient_projects, key=lambda x: (x["account"], x["project"])),
            "current_k": current_k,
            "suggested_k": None,
            "floor": floor,
            "min_prior_days": min_prior,
        }

    scores = sorted(s for s, _ in scored)
    distribution = {
        "count": total,
        "min": round(scores[0], 2),
        "max": round(scores[-1], 2),
        "p50": round(_percentile(scores, 50), 2),
        "p90": round(_percentile(scores, 90), 2),
        "p95": round(_percentile(scores, 95), 2),
        "p99": round(_percentile(scores, 99), 2),
    }

    flag_table = []
    for k in k_candidates:
        flag_count = sum(1 for s, cost in scored if s > k and cost >= floor)
        flag_table.append({
            "k": k,
            "flag_count": flag_count,
            "flag_rate": round(flag_count / total, 4),
        })

    # Suggested k: the candidate whose flag_rate is CLOSEST TO the band center
    # (3%) — centering keeps the threshold off the noisy 5% edge. Ties -> higher
    # k (the more conservative / less noisy choice).
    best = min(flag_table,
               key=lambda e: (abs(e["flag_rate"] - CALIBRATE_TARGET_RATE), -e["k"]))
    rate = best["flag_rate"]
    lo, hi = CALIBRATE_BAND
    in_band = lo <= rate <= hi
    if rate < lo:
        note = (f"flag-rate {rate:.1%} is below the {lo:.0%} floor even at the "
                f"closest k={best['k']}: history too stable to need a higher threshold.")
    elif not in_band and best["k"] == max(k_candidates) and rate > hi:
        note = (f"flag-rate {rate:.1%} exceeds the {hi:.0%} target even at k="
                f"{max(k_candidates)}: investigate the data or consider k>{max(k_candidates)}.")
    elif in_band:
        note = f"flag-rate {rate:.1%} lands in the {lo:.0%}-{hi:.0%} target band."
    else:
        note = f"flag-rate {rate:.1%} is nearest the {CALIBRATE_TARGET_RATE:.0%} center but outside the band."

    return {
        "status": "ok",
        "qualifying_project_days": total,
        "distribution": distribution,
        "flag_table": flag_table,
        "current_k": current_k,
        "suggested_k": best["k"],
        "suggested_flag_rate": rate,
        "in_band": in_band,
        "note": note,
        "target_rate": CALIBRATE_TARGET_RATE,
        "band": [lo, hi],
        "floor": floor,
        "min_prior_days": min_prior,
        "insufficient_projects": sorted(
            insufficient_projects, key=lambda x: (x["account"], x["project"])),
    }
