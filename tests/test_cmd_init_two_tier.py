"""Tests for cli._detect_plan_two_tier + the cmd_init integration point.

v5 clean architecture: the former tier-2 (a network call to the consumer
endpoint claude.ai/api/account with the OAuth Bearer token) was REMOVED.
Plan detection is now local-only — it reads ~/.claude/.credentials.json and,
if that doesn't reveal the plan, falls through to the wizard question. These
tests assert that single-tier behavior AND that no network lookup is ever
attempted (a guard against re-introducing the credential path).
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import cli  # noqa: E402


class DetectPlanLocalOnlyTests(unittest.TestCase):

    def test_local_success_returns_plan(self):
        # When _detect_from_credentials returns a plan, it is used verbatim.
        with patch.object(
            cli, "_detect_from_credentials",
            return_value=("max", "jegan@example.com"),
        ):
            plan, email = cli._detect_plan_two_tier()
        self.assertEqual(plan, "max")
        self.assertEqual(email, "jegan@example.com")

    def test_local_empty_falls_through(self):
        # No plan locally → (None, email) so the wizard asks. Email is
        # preserved even when the plan is unknown.
        with patch.object(
            cli, "_detect_from_credentials", return_value=(None, "jegan@example.com"),
        ):
            plan, email = cli._detect_plan_two_tier()
        self.assertIsNone(plan)
        self.assertEqual(email, "jegan@example.com")

    def test_unknown_plan_value_falls_through(self):
        # A plan string not in PLAN_DEFAULTS is treated as "unknown".
        with patch.object(
            cli, "_detect_from_credentials", return_value=("enterprise", None),
        ):
            plan, _email = cli._detect_plan_two_tier()
        self.assertIsNone(plan)

    def test_no_network_lookup_module_used(self):
        # The credential-path helpers must no longer exist on cli — proof
        # the tier-2 network lookup cannot be reached.
        self.assertFalse(hasattr(cli, "_read_oauth_credentials"))

    def test_no_consumer_endpoint_in_source(self):
        cli_src = os.path.join(REPO_ROOT, "cli.py")
        with open(cli_src, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("claude.ai/api/account", text)
        self.assertNotIn("from oauth_lookup import", text)


class CmdInitIntegrationTests(unittest.TestCase):
    """Source-level guards that the cmd_init call site is wired to the
    plan-detection helper and the Y/n confirmation prompt still renders."""

    def test_cmd_init_uses_detect_helper(self):
        cli_src = os.path.join(REPO_ROOT, "cli.py")
        with open(cli_src, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertRegex(
            text,
            r"detected_plan,\s*detected_email\s*=\s*_detect_plan_two_tier\(\)",
            msg="cmd_init() should call _detect_plan_two_tier",
        )

    def test_yn_confirm_prompt_still_rendered(self):
        cli_src = os.path.join(REPO_ROOT, "cli.py")
        with open(cli_src, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Is this correct? [Y/n]", text)


if __name__ == "__main__":
    unittest.main()
