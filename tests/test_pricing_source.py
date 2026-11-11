"""pricing.py is the single source of truth for token rates.

These tests exist because burnctl and narthex-agent-eval independently priced the
same JSONL corpus from two tables that disagreed, and nothing failed when they
drifted. The decisive test here is test_legacy_matches_config: it binds
pricing.LEGACY_FAMILY_PRICING to config.MODEL_PRICING so the live rates cannot be
edited without a deliberate, visible change here.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pricing  # noqa: E402
from config import MODEL_PRICING  # noqa: E402


class TestSourceIsDated(unittest.TestCase):
    def test_source_exists_and_is_substantial(self):
        self.assertTrue(pricing.SOURCE)
        self.assertGreater(
            len(pricing.SOURCE), 150,
            "SOURCE must say where the rates came from, not just name a vendor",
        )

    def test_dates_are_iso(self):
        for field in ("SOURCE_DATE", "UPSTREAM_CACHE_DATE"):
            value = getattr(pricing, field)
            self.assertRegex(
                value, r"^\d{4}-\d{2}-\d{2}$",
                "%s must be an ISO date; an undated rate table is a memory, "
                "not a fact" % field,
            )

    def test_source_names_its_upstream_date(self):
        self.assertIn(pricing.UPSTREAM_CACHE_DATE, pricing.SOURCE)


class TestPublishedRates(unittest.TestCase):
    """Rates read 2026-11-11 from the claude-api skill's Current Models table."""

    EXPECTED = {
        "claude-fable-5-1":  (10.00, 50.00),
        "claude-opus-5-5":   (4.00, 20.00),
        "claude-opus-5":     (5.00, 25.00),
        "claude-sonnet-5-5": (2.00, 10.00),
        "claude-sonnet-5":   (2.00, 10.00),
        "claude-haiku-5-5":  (0.10, 0.50),
        "claude-haiku-4-5":  (1.00, 5.00),
    }

    def test_known_rates_pinned(self):
        for model_id, (inp, out) in self.EXPECTED.items():
            with self.subTest(model=model_id):
                self.assertIn(model_id, pricing.PRICES)
                self.assertEqual(pricing.PRICES[model_id]["input"], inp)
                self.assertEqual(pricing.PRICES[model_id]["output"], out)

    def test_every_entry_is_complete_and_positive(self):
        for model_id, rates in pricing.PRICES.items():
            with self.subTest(model=model_id):
                self.assertEqual(set(rates), {"input", "output"})
                self.assertGreater(rates["input"], 0)
                self.assertGreater(rates["output"], 0)
                self.assertGreater(
                    rates["output"], rates["input"],
                    "output has always been dearer than input; a table where "
                    "it is not has probably had a column swapped",
                )

    def test_model_ids_carry_no_date_suffix(self):
        for model_id in pricing.PRICES:
            with self.subTest(model=model_id):
                self.assertNotRegex(
                    model_id, r"-\d{8}$",
                    "model IDs are complete as-is; never date-suffixed",
                )


class TestNormalisation(unittest.TestCase):
    def test_strips_cost_state_suffix(self):
        self.assertEqual(
            pricing.normalise_model("claude-opus-5[1m]"), "claude-opus-5")

    def test_strips_snapshot_date(self):
        self.assertEqual(
            pricing.normalise_model("claude-haiku-4-5-20251001"),
            "claude-haiku-4-5")

    def test_passes_through_exact_id(self):
        self.assertEqual(
            pricing.normalise_model("claude-opus-5-5"), "claude-opus-5-5")

    def test_unknown_returns_none_not_a_guess(self):
        for bad in ("", None, "gpt-4", "claude-opus", "claude-nonesuch-9"):
            with self.subTest(model=bad):
                self.assertIsNone(pricing.normalise_model(bad))

    def test_legacy_family_names_are_not_priceable_here(self):
        """The family keys belong to the legacy table, not the published one.

        scanner.py collapses versions onto these; that is the defect this file
        documents, so resolving them here would paper over it.
        """
        for family in pricing.LEGACY_FAMILY_PRICING:
            with self.subTest(family=family):
                self.assertIsNone(pricing.normalise_model(family))


class TestCostOf(unittest.TestCase):
    def test_unknown_model_is_none_never_zero(self):
        self.assertIsNone(pricing.cost_of("claude-nonesuch-9", {"input": 1000}))

    def test_plain_input_output(self):
        cost = pricing.cost_of(
            "claude-opus-5-5", {"input": 1_000_000, "output": 1_000_000})
        self.assertAlmostEqual(cost, 24.00, places=6)

    def test_missing_token_keys_default_to_zero(self):
        self.assertAlmostEqual(
            pricing.cost_of("claude-sonnet-5-5", {"input": 1_000_000}),
            2.00, places=6)

    def test_empty_tokens_is_zero_not_none(self):
        self.assertEqual(pricing.cost_of("claude-opus-5-5", {}), 0.0)


class TestCacheRates(unittest.TestCase):
    def test_published_cache_read_wins_over_multiplier(self):
        """Opus 5.5 publishes $0.20, while 0.10x of $4.00 input would be $0.40.

        A flat multiplier overstates it by 2x. narthex's prices.mjs applies the
        flat factor and inherits that error.
        """
        self.assertEqual(pricing.cache_read_rate("claude-opus-5-5"), 0.20)
        flat = (pricing.PRICES["claude-opus-5-5"]["input"]
                * pricing.CACHE_MULT["cache_read"])
        self.assertEqual(flat, 0.40)
        self.assertNotEqual(pricing.cache_read_rate("claude-opus-5-5"), flat)

    def test_multiplier_used_where_no_published_rate(self):
        self.assertAlmostEqual(
            pricing.cache_read_rate("claude-opus-5"), 0.50, places=6)

    def test_one_hour_write_is_dearer_than_five_minute(self):
        five = pricing.cache_write_rate("claude-opus-5-5", "5m")
        hour = pricing.cache_write_rate("claude-opus-5-5", "1h")
        self.assertGreater(hour, five)

    def test_cache_read_entries_are_all_real_models(self):
        for model_id in pricing.CACHE_READ:
            with self.subTest(model=model_id):
                self.assertIn(model_id, pricing.PRICES)


class TestLegacyDrift(unittest.TestCase):
    def test_legacy_matches_config(self):
        """The live table and the recorded legacy table must stay identical.

        This is the guard. If someone edits config.py:MODEL_PRICING without
        updating pricing.py, this fails and forces the repricing decision to be
        made deliberately instead of by accident.
        """
        for family, rates in pricing.LEGACY_FAMILY_PRICING.items():
            with self.subTest(family=family):
                self.assertIn(family, MODEL_PRICING)
                self.assertEqual(
                    rates, MODEL_PRICING[family],
                    "config.py:MODEL_PRICING[%r] has changed. Update "
                    "pricing.LEGACY_FAMILY_PRICING to match and re-read the "
                    "drift report." % family,
                )

    def test_every_family_has_an_assumed_current_model(self):
        self.assertEqual(
            set(pricing.LEGACY_FAMILY_PRICING),
            set(pricing.LEGACY_FAMILY_ASSUMED_AS))
        for model_id in pricing.LEGACY_FAMILY_ASSUMED_AS.values():
            with self.subTest(model=model_id):
                self.assertIn(model_id, pricing.PRICES)

    def test_drift_is_an_overstatement_not_an_understatement(self):
        """Every live family rate is currently higher than the published one.

        Pinned deliberately: if a future table makes burnctl UNDER-report, that
        is a different and more dangerous failure and should break this test.
        """
        for family, info in pricing.legacy_drift().items():
            for field, factor in info["factors"].items():
                with self.subTest(family=family, field=field):
                    self.assertIsNotNone(factor)
                    self.assertGreater(factor, 1.0)

    def test_opus_cache_read_drift_is_the_worst_of_them(self):
        """96%+ of burnctl's tokens are cache reads, so this factor dominates."""
        factors = pricing.legacy_drift()["claude-opus"]["factors"]
        self.assertAlmostEqual(factors["cache_read"], 7.50, places=2)
        self.assertGreater(factors["cache_read"], factors["input"])


class TestReconciliationWithNarthex(unittest.TestCase):
    """Facts shared with narthex-agent-eval scripts/agent-eval/prices.mjs.

    That file is outside this repo and scope-fenced by its own harness, so it
    cannot be imported or edited from here. These pin the values the two tables
    must agree on, so a change on this side is visible when they are compared.
    """

    def test_shared_multipliers(self):
        self.assertEqual(pricing.CACHE_MULT["cache_read"], 0.10)
        self.assertEqual(pricing.CACHE_MULT["cache_5m"], 1.25)
        self.assertEqual(pricing.CACHE_MULT["cache_1h"], 2.00)

    def test_models_narthex_also_prices(self):
        for model_id, (inp, out) in {
            "claude-fable-5-1":  (10, 50),
            "claude-opus-5-5":   (4, 20),
            "claude-opus-5":     (5, 25),
            "claude-sonnet-5":   (2, 10),
            "claude-haiku-4-5":  (1, 5),
        }.items():
            with self.subTest(model=model_id):
                self.assertEqual(pricing.PRICES[model_id]["input"], inp)
                self.assertEqual(pricing.PRICES[model_id]["output"], out)

    def test_normalisation_agrees_with_narthex_examples(self):
        """The two cases narthex's own comment calls out."""
        self.assertEqual(
            pricing.normalise_model("claude-haiku-4-5-20251001"),
            "claude-haiku-4-5")
        self.assertEqual(
            pricing.normalise_model("claude-opus-5[1m]"), "claude-opus-5")


class TestPromptBands(unittest.TestCase):
    def test_haiku_band_recorded(self):
        band = pricing.PROMPT_BAND_OVERRIDES["claude-haiku-5-5"]
        self.assertEqual(band["over_tokens"], 100_000)
        self.assertGreater(band["input"], pricing.PRICES["claude-haiku-5-5"]["input"])

    def test_band_keys_are_real_models(self):
        for model_id in pricing.PROMPT_BAND_OVERRIDES:
            with self.subTest(model=model_id):
                self.assertIn(model_id, pricing.PRICES)


class TestNoRegexCatastrophe(unittest.TestCase):
    def test_normalise_handles_odd_input_without_raising(self):
        for odd in ("-" * 200, "claude-" + "9" * 50, "[1m]", "x-20260101",
                    "claude-opus-5-5[1m][1m]"):
            with self.subTest(model=odd):
                self.assertIsNone(pricing.normalise_model(odd))


if __name__ == "__main__":
    unittest.main()
