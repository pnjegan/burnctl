"""Tests for version_check.classify_version() and is_bad_version().

classify_version returns a 2-tuple (severity, short_reason) where
severity is one of: 'critical', 'warning', or None.

Run: python3 -m unittest tests.test_version_check -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestClassifyVersion(unittest.TestCase):

    def _classify(self, v):
        from version_check import classify_version
        return classify_version(v)

    def test_2_1_118_is_critical(self):
        sev, reason = self._classify("2.1.118")
        self.assertEqual(sev, "critical")
        self.assertIn("52578", reason)

    def test_2_1_119_is_warning(self):
        sev, reason = self._classify("2.1.119")
        self.assertEqual(sev, "warning")
        self.assertIn("52578", reason)

    def test_2_1_120_is_clean(self):
        sev, reason = self._classify("2.1.120")
        self.assertIsNone(sev)
        self.assertIsNone(reason)

    def test_cache_regression_range_critical(self):
        """69-89 range should all classify as critical."""
        for patch in (69, 75, 88, 89):
            sev, reason = self._classify(f"2.1.{patch}")
            self.assertEqual(sev, "critical", f"2.1.{patch} should be critical")
            self.assertIn("cache regression", reason)

    def test_just_outside_cache_range(self):
        """68 and 90 are clean — boundary check."""
        sev, _ = self._classify("2.1.68")
        self.assertIsNone(sev)
        sev, _ = self._classify("2.1.90")
        self.assertIsNone(sev)

    def test_malformed_version_is_clean(self):
        """Non-semver strings return (None, None) instead of crashing."""
        sev, reason = self._classify("not-a-version")
        self.assertIsNone(sev)
        self.assertIsNone(reason)

    def test_empty_string_is_clean(self):
        sev, reason = self._classify("")
        self.assertIsNone(sev)
        self.assertIsNone(reason)

    def test_different_major_is_clean(self):
        """v3.x should not match v2.1.x rules even with same patch numbers."""
        sev, _ = self._classify("3.1.118")
        self.assertIsNone(sev)


class TestIsBadVersion(unittest.TestCase):
    """is_bad_version is the legacy 2-tuple API — only covers the
    cache-regression range. 118/119 are NOT flagged here (by design);
    classify_version is the severity-aware replacement."""

    def _check(self, v):
        from version_check import is_bad_version
        return is_bad_version(v)

    def test_cache_range_true(self):
        bad, reason = self._check("2.1.89")
        self.assertTrue(bad)
        self.assertIsNotNone(reason)

    def test_2_1_118_not_flagged_by_legacy(self):
        """By design — is_bad_version covers the old range only."""
        bad, reason = self._check("2.1.118")
        self.assertFalse(bad)
        self.assertIsNone(reason)

    def test_malformed_returns_false(self):
        bad, reason = self._check("garbage")
        self.assertFalse(bad)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
