"""Proves the daily_qa cost-anomaly self-brake.

The brake withholds burnctl's OWN publish (DOD -> exit 2) when a red
cost_anomaly sits on a session active in the last 24h. It must NOT fire on a
red flag whose session is old — detect_all re-stamps historical flags every
scan, so a naive detected_at window would brake forever. These tests pin both
sides: fires on a live runaway, silent on stale history.

Detect-not-enforce: the brake is a QA exit code; no Claude Code session is
ever touched.
"""

import sqlite3
import time
import unittest

import daily_qa

DAY = 86400


def _db(session_ts, severity="red", pattern="cost_anomaly"):
    """In-memory DB shaped like the columns the brake query touches."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions (session_id TEXT, timestamp INTEGER, cost_usd REAL)")
    conn.execute(
        "CREATE TABLE waste_events "
        "(session_id TEXT, pattern_type TEXT, severity TEXT, detected_at INTEGER)"
    )
    conn.execute("INSERT INTO sessions VALUES ('S', ?, 420.0)", (session_ts,))
    # detected_at is 'now' on purpose — a re-scan today; the brake must key off
    # session activity, not this timestamp.
    conn.execute(
        "INSERT INTO waste_events VALUES ('S', ?, ?, ?)",
        (pattern, severity, int(time.time())),
    )
    conn.commit()
    return conn


class TestDailyQaBrake(unittest.TestCase):
    def test_fires_on_red_flag_for_session_active_now(self):
        conn = _db(int(time.time()) - 3600)  # active 1h ago = live runaway
        status, evidence = daily_qa.check_cost_anomaly_brake(conn)
        self.assertEqual(status, daily_qa.DOD, evidence)
        conn.close()

    def test_silent_on_stale_session(self):
        conn = _db(int(time.time()) - 10 * DAY)  # old session, re-stamped today
        status, evidence = daily_qa.check_cost_anomaly_brake(conn)
        self.assertNotEqual(status, daily_qa.DOD, evidence)
        conn.close()

    def test_silent_on_amber_flag(self):
        conn = _db(int(time.time()) - 3600, severity="amber")  # not red
        status, evidence = daily_qa.check_cost_anomaly_brake(conn)
        self.assertNotEqual(status, daily_qa.DOD, evidence)
        conn.close()


if __name__ == "__main__":
    unittest.main()
