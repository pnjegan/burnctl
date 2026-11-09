"""The audit classifier must exempt detectors and prose without swallowing real hits.

Check 2 and Check 3 both carry exemptions, and an exemption that is too broad
turns the gate green while a real leak ships. These tests pin the boundary on
synthetic input, so they keep working after the live findings are fixed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import audit_checks as ac  # noqa: E402

TQ = chr(34) * 3


class ProseDetection(unittest.TestCase):
    def test_comment_is_prose(self):
        self.assertEqual(ac._prose_lines(["# a comment"]), {1})

    def test_multiline_docstring_body_is_prose(self):
        lines = [
            "def f():",
            f"    {TQ}Explains the deliberate path.",
            "    More prose here.",
            f"    {TQ}",
            "    return 1",
        ]
        self.assertEqual(ac._prose_lines(lines), {2, 3, 4})

    def test_single_line_docstring_does_not_open_a_region(self):
        lines = [f"    {TQ}one liner{TQ}", "    x = 1"]
        self.assertNotIn(2, ac._prose_lines(lines),
                         "a closed one-line docstring must not swallow the code after it")

    def test_hash_inside_a_string_is_not_a_comment(self):
        self.assertEqual(ac._prose_lines(['x = "# not a comment"']), set())


class ExemptionBoundary(unittest.TestCase):
    """The rules that decide finding vs exempt, applied directly."""

    def test_bare_literal_is_a_detection_pattern(self):
        for line in ('    "~/projects/burnctl",', "    '/root/projects/burnctl',"):
            self.assertTrue(ac.BARE_LITERAL_RE.match(line), line)

    def test_path_inside_an_expression_is_not_a_bare_literal(self):
        line = '    os.path.expanduser("~/projects/burnctl/data/usage.db"),'
        self.assertFalse(
            ac.BARE_LITERAL_RE.match(line),
            "a path inside a call is a real hardcode and must stay flagged")

    def test_return_of_a_branded_path_is_not_exempt(self):
        line = '    return "/root/backups/claudash"'
        self.assertEqual(ac._prose_lines([line]), set())
        self.assertIsNone(
            next((r for sub, r in ac.BRANDING_EXEMPT_SUBSTRINGS.items()
                  if sub in line), None),
            "returning a branded path must not match any branding exemption")

    def test_every_exemption_carries_a_reason(self):
        for mapping, name in ((ac.PATH_EXEMPT_SUBSTRINGS, "PATH_EXEMPT_SUBSTRINGS"),
                              (ac.BRANDING_EXEMPT_SUBSTRINGS, "BRANDING_EXEMPT_SUBSTRINGS"),
                              (ac.BRANDING_EXEMPT, "BRANDING_EXEMPT")):
            for key, reason in mapping.items():
                self.assertTrue(
                    isinstance(reason, str) and len(reason) > 20,
                    f"{name}[{key!r}] needs a real reason, not {reason!r}")


class DriftPattern(unittest.TestCase):
    def test_real_drift_matches(self):
        for line in ('"SELECT waste_type FROM waste_events"',
                     '"SELECT x FROM browser_activity"',
                     '"baseline_waste_events"'):
            self.assertTrue(ac.DRIFT_RE.search(line), line)

    def test_real_columns_are_not_drift(self):
        """token_cost and fix_id are real columns; bare names must not match."""
        for line in ('"SELECT SUM(token_cost) FROM waste_events"',
                     '"SELECT * FROM fix_measurements WHERE fix_id = ?"',
                     '    fix_id = int(sys.argv[2])',
                     '    "start_time": cur["start_time"],'):
            self.assertIsNone(ac.DRIFT_RE.search(line),
                              f"false positive on {line!r}")


if __name__ == "__main__":
    unittest.main()
