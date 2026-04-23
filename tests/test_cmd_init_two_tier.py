"""Tests for cli._detect_plan_two_tier + the cmd_init integration point.

The two-tier helper is where the logic lives, so the four behavior
tests (tier-1 short-circuit, tier-2 success, both-fail, expired-token)
target it directly. A final test asserts cmd_init() still wires the
helper in — a compile-time guard against someone reverting the
call-site swap.

All network calls are stubbed — no real /api/account hits.
"""
import os
import re
import sys
import time
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import cli  # noqa: E402


class _FetchAccountStub:
    """Records whether fetch_account was called + what kwargs were passed.
    Returns (email, org_id, plan, err) supplied at construction."""

    def __init__(self, email=None, org_id=None, plan=None, err=None):
        self.email = email
        self.org_id = org_id
        self.plan = plan
        self.err = err
        self.call_count = 0
        self.last_kwargs = None

    def __call__(self, access_token, timeout=4.0):
        self.call_count += 1
        self.last_kwargs = {"access_token": access_token, "timeout": timeout}
        return (self.email, self.org_id, self.plan, self.err)


def _raising_fetch_account(*_args, **_kwargs):
    raise AssertionError(
        "fetch_account must not be called when tier 1 already answered"
    )


class DetectPlanTwoTierTests(unittest.TestCase):

    def test_tier1_success_skips_tier2(self):
        # When _detect_from_credentials returns a plan, no network call.
        with patch.object(
            cli, "_detect_from_credentials",
            return_value=("max", "jegan@example.com"),
        ), patch(
            "oauth_lookup.fetch_account", side_effect=_raising_fetch_account,
        ):
            plan, email = cli._detect_plan_two_tier()
        self.assertEqual(plan, "max")
        self.assertEqual(email, "jegan@example.com")

    def test_tier1_fail_tier2_success(self):
        # Tier 1 empty → tier 2 called → plan returned from API response.
        # Also verifies the 4s timeout is passed through from
        # _detect_plan_two_tier to fetch_account (the hard cap on
        # first-run hang protection).
        future_ms = int((time.time() + 3600) * 1000)
        stub = _FetchAccountStub(
            email="jegan@example.com",
            org_id="org-abc",
            plan="max",
            err=None,
        )
        with patch.object(
            cli, "_detect_from_credentials", return_value=(None, None),
        ), patch.object(
            cli, "_read_oauth_credentials",
            return_value={"accessToken": "tok-xyz", "expiresAt": future_ms},
        ), patch("oauth_lookup.fetch_account", stub):
            plan, email = cli._detect_plan_two_tier()
        self.assertEqual(plan, "max")
        self.assertEqual(email, "jegan@example.com")
        self.assertEqual(stub.call_count, 1)
        self.assertEqual(stub.last_kwargs["timeout"], 4.0)

    def test_both_tiers_fail_falls_through(self):
        # Tier 1 empty, tier 2 returns network error → (None, email).
        future_ms = int((time.time() + 3600) * 1000)
        stub = _FetchAccountStub(err="network_error:timeout")
        with patch.object(
            cli, "_detect_from_credentials", return_value=(None, None),
        ), patch.object(
            cli, "_read_oauth_credentials",
            return_value={"accessToken": "tok-xyz", "expiresAt": future_ms},
        ), patch("oauth_lookup.fetch_account", stub):
            plan, _email = cli._detect_plan_two_tier()
        self.assertIsNone(plan)
        self.assertEqual(stub.call_count, 1)

    def test_expired_token_skips_tier2(self):
        # Tier 1 empty + expiresAt in the past → tier 2 NOT called.
        past_ms = int((time.time() - 3600) * 1000)
        with patch.object(
            cli, "_detect_from_credentials", return_value=(None, None),
        ), patch.object(
            cli, "_read_oauth_credentials",
            return_value={"accessToken": "tok-xyz", "expiresAt": past_ms},
        ), patch(
            "oauth_lookup.fetch_account", side_effect=_raising_fetch_account,
        ):
            plan, _email = cli._detect_plan_two_tier()
        self.assertIsNone(plan)


class CmdInitIntegrationTests(unittest.TestCase):
    """Source-level guards that the cmd_init call site is wired to the
    two-tier helper and the Y/n confirmation prompt still renders."""

    def test_cmd_init_uses_two_tier_helper(self):
        cli_src = os.path.join(REPO_ROOT, "cli.py")
        with open(cli_src, "r", encoding="utf-8") as f:
            text = f.read()
        # The call inside cmd_init must invoke the two-tier helper, not
        # the single-tier credentials reader.
        self.assertRegex(
            text,
            r"detected_plan,\s*detected_email\s*=\s*_detect_plan_two_tier\(\)",
            msg="cmd_init() should call _detect_plan_two_tier, not _detect_from_credentials",
        )

    def test_yn_confirm_prompt_still_rendered(self):
        cli_src = os.path.join(REPO_ROOT, "cli.py")
        with open(cli_src, "r", encoding="utf-8") as f:
            text = f.read()
        # The Y/n confirmation must remain reachable so auto-detected
        # plans can be manually overridden.
        self.assertIn("Is this correct? [Y/n]", text)


if __name__ == "__main__":
    unittest.main()
