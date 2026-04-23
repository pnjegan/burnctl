import unittest
from fix_tracker import determine_verdict


class TestVerdictSessionsGate(unittest.TestCase):
    def test_low_sessions_waste_worsened_returns_worsened(self):
        """Fix 12 repro: sessions=0, waste+40% must return worsened."""
        delta = {"waste_events": {"pct_change": 40.0}}
        self.assertEqual(determine_verdict(delta, "max", 0), "worsened")

    def test_low_sessions_waste_improving_returns_improving(self):
        """Symmetric: strong improvement beats low-session gate."""
        delta = {"waste_events": {"pct_change": -30.0}}
        self.assertEqual(determine_verdict(delta, "max", 1), "improving")

    def test_low_sessions_no_signal_returns_insufficient_data(self):
        """Genuine low-data + neutral signals: honest shrug."""
        delta = {
            "waste_events": {"pct_change": 0.0},
            "cost_usd": {"pct_change": 0},
            "avg_turns_per_session": {"pct_change": 0},
            "waste_free_ratio": {"pct_change": 0},
        }
        self.assertEqual(determine_verdict(delta, "max", 1), "insufficient_data")

    def test_high_sessions_no_signal_returns_neutral(self):
        """Plenty of data, no threshold crossed: neutral, not insufficient."""
        delta = {
            "waste_events": {"pct_change": 0.0},
            "cost_usd": {"pct_change": 0},
            "avg_turns_per_session": {"pct_change": 0},
            "waste_free_ratio": {"pct_change": 0},
        }
        self.assertEqual(determine_verdict(delta, "max", 10), "neutral")

    def test_api_plan_cost_worsened(self):
        """api plan uses cost signal, not waste."""
        delta = {
            "waste_events": {"pct_change": 0.0},
            "cost_usd": {"pct_change": 25.0},
        }
        self.assertEqual(determine_verdict(delta, "api", 5), "worsened")


if __name__ == "__main__":
    unittest.main()
