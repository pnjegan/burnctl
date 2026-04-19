"""burnctl peak_hour — peak hour detection + drain-rate context.

Window: Mon-Fri 13:00-19:00 UTC (= 5am-11am PT).
  Source: Thariq Shihipar (Anthropic), X post 2026-03-26
  Confirmed: DevOps.com, GitHub anthropics/claude-code issue #41930

2.4x multiplier: applies to Opus 4.7 specifically.
  Source: cnighswonger/claude-code-cache-fix readme
  Cross-checked: ArkNill/claude-code-hidden-problem-analysis
                 (71-call sample, 2.4x avg / 2.6x cross-validated)

For other models we say "limits drain faster" without a number,
since no verified multiplier exists.

Pure stdlib. No DB read. Time math only.
"""

import datetime


PEAK_START_UTC = 13  # 13:00 UTC = 05:00 PT
PEAK_END_UTC = 19    # 19:00 UTC = 11:00 PT


def get_peak_status():
    """Return dict describing whether we're currently in peak hours."""
    now = datetime.datetime.now(datetime.timezone.utc)
    is_weekday = now.weekday() < 5  # Mon=0 .. Sun=6
    is_peak_hour = PEAK_START_UTC <= now.hour < PEAK_END_UTC
    in_peak = is_weekday and is_peak_hour

    if in_peak:
        end_dt = now.replace(hour=PEAK_END_UTC, minute=0, second=0, microsecond=0)
        mins_left = int((end_dt - now).total_seconds() / 60)
        return {
            "in_peak": True,
            "now_utc": now.strftime("%H:%M UTC"),
            "mins_until_off_peak": mins_left,
            "message": (
                f"⚠️  PEAK HOURS  {now.strftime('%H:%M UTC')} "
                f"(ends {PEAK_END_UTC:02d}:00 UTC, {mins_left}m remaining)"
            ),
            "detail": (
                "Session limits drain faster during peak hours "
                "(Mon-Fri 13:00-19:00 UTC). "
                "Opus 4.7 users: ~2.4x normal drain rate. "
                "Shift heavy sessions to after 19:00 UTC."
            ),
        }

    # Off-peak — compute time to next peak window
    if not is_weekday:
        # Weekend: skip to Monday
        days_ahead = (7 - now.weekday()) % 7 or 7
        next_peak = now.replace(
            hour=PEAK_START_UTC, minute=0, second=0, microsecond=0
        ) + datetime.timedelta(days=days_ahead)
    elif now.hour >= PEAK_END_UTC:
        # After today's peak — try tomorrow
        tomorrow = now + datetime.timedelta(days=1)
        if tomorrow.weekday() < 5:
            next_peak = tomorrow.replace(
                hour=PEAK_START_UTC, minute=0, second=0, microsecond=0
            )
        else:
            days_ahead = (7 - tomorrow.weekday()) % 7
            next_peak = (tomorrow + datetime.timedelta(days=days_ahead)).replace(
                hour=PEAK_START_UTC, minute=0, second=0, microsecond=0
            )
    else:
        # Before today's peak
        next_peak = now.replace(
            hour=PEAK_START_UTC, minute=0, second=0, microsecond=0
        )

    mins_to_peak = int((next_peak - now).total_seconds() / 60)
    hours_to_peak = mins_to_peak // 60
    mins_rem = mins_to_peak % 60
    time_str = (
        f"{hours_to_peak}h {mins_rem}m" if hours_to_peak > 0 else f"{mins_rem}m"
    )

    return {
        "in_peak": False,
        "now_utc": now.strftime("%H:%M UTC"),
        "mins_until_peak": mins_to_peak,
        "message": (
            f"✓  Off-peak  {now.strftime('%H:%M UTC')} "
            f"(next peak in {time_str})"
        ),
        "detail": "Good time for heavy sessions. Full session limits active.",
    }


def print_peak_status():
    """Used by cli `burnctl peak-hours` and prepended to `burnctl burnrate`."""
    status = get_peak_status()
    print()
    print(status["message"])
    print(f"   {status['detail']}")
    print()


if __name__ == "__main__":
    print_peak_status()
