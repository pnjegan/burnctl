"""burnctl fix-scoreboard — detect → fix → measure → prove.

Adaptation note: the spec assumed `status='applied'` and a delta_json
with `cost_saved_usd` / `improvement_pct` — reality is different.

Real `fixes.status` values on production data:
  confirmed (= the "applied" equivalent), measuring

Real `fix_measurements.verdict` values:
  improving, neutral, worsened, insufficient_data

Real `delta_json` keys:
  tokens_saved (int, top-level)
  improvement_multiplier (float)
  api_equivalent_savings_monthly (float, monthly USD)
  avg_cost_per_session: {before, after, pct_change}
  cost_usd: {before, after, pct_change}
  waste_events: {before, after, pct_change}
  ...
"""
import os
import sqlite3
import json


def load_db():
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            conn = sqlite3.connect(p)
            conn.row_factory = sqlite3.Row
            return conn
    return None


def _verdict_icon(verdict):
    return {
        "improving": "✅",
        "worsened": "❌",
        "neutral": "➡️",
        "insufficient_data": "⏳",
    }.get(verdict, "⏳")


def run_fix_scoreboard():
    print()
    print("burnctl fix-scoreboard")
    print("=" * 64)
    print("The detect → fix → measure → prove loop.")
    print("ccusage shows spend. burnctl proves ROI.")
    print("Reported as-of last measurement per fix.\n")

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return

    cur = conn.cursor()

    # Pull latest measurement per fix so each fix shows once.
    # Note: real schema has `created_at` (no `applied_at`); we use that.
    # Fix F (CORR-10/11): also pull latest metrics_json so the render can
    # re-derive delta from a point-in-time snapshot instead of re-capturing
    # live — keeps headline values stable between renders.
    cur.execute("""
        SELECT
          f.id, f.project, f.waste_pattern, f.status, f.created_at,
          fm.verdict, fm.delta_json, fm.measured_at, fm.metrics_json,
          COALESCE(f.baseline_corrupted, 0) AS baseline_corrupted
        FROM fixes f
        LEFT JOIN fix_measurements fm
          ON fm.fix_id = f.id
          AND fm.measured_at = (
            SELECT MAX(measured_at) FROM fix_measurements WHERE fix_id = f.id
          )
        WHERE f.status IN ('confirmed', 'measuring', 'applied')
        ORDER BY f.id DESC
    """)
    fixes = cur.fetchall()

    if not fixes:
        print("No fixes recorded yet.")
        print("Run `burnctl audit` to surface waste patterns,")
        print("then `burnctl fix add` to record a fix you've applied.")
        conn.close()
        return

    total_tokens_saved = 0
    total_monthly_savings = 0.0
    wins = losers = neutral = pending = 0

    print(f"{'#':<4} {'Project':<14} {'Pattern':<22} {'Verdict':<13} Impact")
    print("-" * 78)

    from fix_tracker import compute_delta

    baseline_corrupt_count = 0
    skipped_no_measurement = 0
    for (fid, proj, pattern, status, created_at,
         verdict, delta_json, measured_at, metrics_json,
         baseline_corrupted) in fixes:

        # Fix F: skip fixes with no measurement yet — cannot render a
        # point-in-time delta without stored metrics_json.
        if metrics_json is None:
            skipped_no_measurement += 1
            continue

        try:
            current_metrics = json.loads(metrics_json)
        except (json.JSONDecodeError, TypeError):
            skipped_no_measurement += 1
            continue

        # Re-derive delta + verdict at render time from the stored
        # point-in-time snapshot. This replaces reading fm.delta_json so
        # the headline is stable between renders (no live capture drift).
        delta, verdict, _ = compute_delta(conn, fid, current=current_metrics)
        if delta is None:
            skipped_no_measurement += 1
            continue

        tokens_saved = int(delta.get("tokens_saved") or 0)
        monthly_savings = float(delta.get("api_equivalent_savings_monthly") or 0)
        improvement_mult = delta.get("improvement_multiplier")

        if baseline_corrupted:
            # Snapshot-timing bug pre-v3.3 — baseline was captured AFTER
            # the fix was applied. Honest display: show "baseline N/A"
            # instead of inventing a delta. Do not count toward totals.
            baseline_corrupt_count += 1
            icon = "⚠️"
            proj_s = (proj or "unknown")[:13]
            pattern_s = (pattern or "")[:21]
            print(f"{fid:<4} {proj_s:<14} {pattern_s:<22} {icon} baseline N/A  (pre-v3.3 snapshot-timing bug)")
            continue

        if verdict == "improving":
            wins += 1
            total_tokens_saved += tokens_saved
            total_monthly_savings += monthly_savings
            mult_s = f"{improvement_mult:.2f}x" if improvement_mult else ""
            impact = (
                f"-{tokens_saved:,} tok"
                + (f", ${monthly_savings:.2f}/mo" if monthly_savings else "")
                + (f"  {mult_s}" if mult_s else "")
            )
        elif verdict == "worsened":
            losers += 1
            impact = "regression — revisit"
        elif verdict == "neutral":
            neutral += 1
            impact = "no measurable change"
        elif verdict == "insufficient_data":
            pending += 1
            impact = f"need more sessions  (status={status})"
        else:
            pending += 1
            impact = f"awaiting measurement  (status={status})"

        icon = _verdict_icon(verdict)
        proj_s = (proj or "unknown")[:13]
        pattern_s = (pattern or "")[:21]
        verdict_s = verdict or "pending"
        print(f"{fid:<4} {proj_s:<14} {pattern_s:<22} {icon} {verdict_s:<11} {impact}")

    conn.close()
    print()
    print("=" * 64)
    print(f"Summary: {len(fixes)} fix(es) recorded")
    print(f"  ✅ Improving: {wins}")
    print(f"  ❌ Worsened:  {losers}")
    print(f"  ➡️  Neutral:   {neutral}")
    print(f"  ⏳ Pending:   {pending}")
    if baseline_corrupt_count:
        print(f"  ⚠️  Baseline N/A: {baseline_corrupt_count} "
              f"(pre-v3.3 snapshot-timing bug — cannot compute delta)")
    if total_tokens_saved > 0:
        print()
        print(f"  Tokens saved (sum of improving fixes): {total_tokens_saved:,}")
    if total_monthly_savings > 0:
        print(f"  API-equivalent monthly savings:       ${total_monthly_savings:.2f}")
    print()
    print("Next steps:")
    if pending > 0:
        print(f"  {pending} fix(es) measuring — run `burnctl measure <id>` for fresher delta")
    print("  `burnctl audit` to surface more waste patterns")
    print("  `burnctl fix add` to record a fix")
    print()


if __name__ == "__main__":
    run_fix_scoreboard()
