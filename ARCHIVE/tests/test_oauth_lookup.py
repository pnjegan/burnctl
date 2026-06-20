"""Tests for oauth_lookup.fetch_account / _bearer_request.

Covers:
  - Happy path, plan inferred as "max" from memberships capabilities.
  - Happy path, plan inferred as "pro".
  - HTTP 401/403 → err == "expired".
  - socket.timeout → err starts with "network_error:".
  - timeout= kwarg is honored end-to-end (passed through to urlopen).

Stubs urllib.request.urlopen with a fake context manager so no real
network call happens. Stdlib unittest only.
"""
import io
import json
import os
import socket
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import oauth_lookup  # noqa: E402


class _StubResponse:
    """Minimal urlopen-return-value replacement: read() + context manager."""

    def __init__(self, body):
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _stub_urlopen_body(body_dict):
    """Factory returning a urlopen replacement that yields body_dict as JSON."""
    def _stub(req, timeout=None, context=None):
        _stub.last_timeout = timeout
        return _StubResponse(json.dumps(body_dict))
    _stub.last_timeout = None
    return _stub


def _stub_urlopen_http_error(code):
    """Factory returning a urlopen replacement that raises HTTPError(code)."""
    from urllib.error import HTTPError

    def _stub(req, timeout=None, context=None):
        raise HTTPError(
            url="https://claude.ai/api/account",
            code=code,
            msg="stub error",
            hdrs=None,
            fp=io.BytesIO(b""),
        )
    return _stub


def _stub_urlopen_timeout():
    """Factory returning a urlopen replacement that raises socket.timeout."""
    def _stub(req, timeout=None, context=None):
        raise socket.timeout("stub timeout")
    return _stub


class OauthLookupTests(unittest.TestCase):

    def test_happy_path_max_plan(self):
        body = {
            "email_address": "jegan@example.com",
            "memberships": [
                {
                    "organization": {
                        "uuid": "org-abc",
                        "capabilities": ["claude_max_subscription"],
                    }
                }
            ],
        }
        with patch("oauth_lookup.urlopen", _stub_urlopen_body(body)):
            email, org_id, plan, err = oauth_lookup.fetch_account("tok-xyz")
        self.assertEqual(email, "jegan@example.com")
        self.assertEqual(org_id, "org-abc")
        self.assertEqual(plan, "max")
        self.assertIsNone(err)

    def test_happy_path_pro_plan(self):
        body = {
            "email_address": "bob@example.com",
            "memberships": [
                {
                    "organization": {
                        "uuid": "org-pqr",
                        "capabilities": ["claude_pro_subscription"],
                    }
                }
            ],
        }
        with patch("oauth_lookup.urlopen", _stub_urlopen_body(body)):
            _email, _org, plan, err = oauth_lookup.fetch_account("tok-xyz")
        self.assertEqual(plan, "pro")
        self.assertIsNone(err)

    def test_expired_token_returns_err(self):
        # 401 and 403 both map to "expired".
        for code in (401, 403):
            with patch("oauth_lookup.urlopen", _stub_urlopen_http_error(code)):
                email, org, plan, err = oauth_lookup.fetch_account("tok-dead")
            self.assertIsNone(email, msg="code %d" % code)
            self.assertIsNone(org, msg="code %d" % code)
            self.assertIsNone(plan, msg="code %d" % code)
            self.assertEqual(err, "expired", msg="code %d" % code)

    def test_http_500_maps_to_http_tag(self):
        with patch("oauth_lookup.urlopen", _stub_urlopen_http_error(500)):
            _e, _o, _p, err = oauth_lookup.fetch_account("tok-xyz")
        self.assertEqual(err, "http_500")

    def test_network_timeout_returns_err(self):
        with patch("oauth_lookup.urlopen", _stub_urlopen_timeout()):
            email, org, plan, err = oauth_lookup.fetch_account("tok-xyz")
        self.assertIsNone(email)
        self.assertIsNone(org)
        self.assertIsNone(plan)
        self.assertTrue(
            err and err.startswith("network_error:"),
            msg=f"expected network_error:* tag, got {err!r}",
        )

    def test_timeout_parameter_honored(self):
        # Default 4s.
        stub = _stub_urlopen_body({"memberships": []})
        with patch("oauth_lookup.urlopen", stub):
            oauth_lookup.fetch_account("tok-xyz")
        self.assertEqual(stub.last_timeout, 4.0)

        # Caller-overridden 15s (what tools/oauth_sync.py uses).
        stub = _stub_urlopen_body({"memberships": []})
        with patch("oauth_lookup.urlopen", stub):
            oauth_lookup.fetch_account("tok-xyz", timeout=15)
        self.assertEqual(stub.last_timeout, 15)


if __name__ == "__main__":
    unittest.main()
