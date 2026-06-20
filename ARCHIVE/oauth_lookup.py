"""Shared helpers for calling the claude.ai OAuth API with a Bearer token.

Extracted from tools/oauth_sync.py so both the standalone sync script
and cli.py's first-run wizard can reuse the same implementation
without duplicating HTTP + parsing logic.

Stdlib only. No pip dependencies. Never raises on network errors —
errors are returned as string tags the caller classifies.
"""
import json
import ssl
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# Tight default — used by cli.py during first-run wizard where we
# must not hang on a slow network. The standalone sync script in
# tools/oauth_sync.py passes a longer timeout explicitly.
DEFAULT_TIMEOUT = 4.0


def _bearer_request(url, access_token, timeout=DEFAULT_TIMEOUT):
    """Authenticated GET to claude.ai using the OAuth access token.

    Returns:
        (data_dict, None) on success.
        (None, "expired") on HTTP 401/403.
        (None, "http_<code>") on other HTTP errors.
        (None, "network_error:<ExceptionType>") on connection errors
        or JSON decode failure.
    """
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "burnctl-oauth-lookup/1.0")
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), None
    except HTTPError as e:
        if e.code in (401, 403):
            return None, "expired"
        return None, f"http_{e.code}"
    except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
        return None, f"network_error:{type(e).__name__}"


def fetch_account(access_token, timeout=DEFAULT_TIMEOUT):
    """GET https://claude.ai/api/account → (email, org_id, plan, err).

    `plan` is one of {"max", "pro"} when the memberships[].
    organization.capabilities[] list contains a matching substring;
    defaults to "max" otherwise. `err` is None on success or one of
    the error tags documented on _bearer_request.

    Default timeout is DEFAULT_TIMEOUT (4s) — tight enough to not
    block first-run UX, loose enough to survive a typical wifi RTT.
    """
    data, err = _bearer_request(
        "https://claude.ai/api/account", access_token, timeout=timeout
    )
    if err or not data:
        return None, None, None, err
    email = data.get("email_address") or data.get("email") or ""
    org_id = ""
    plan = "max"
    memberships = data.get("memberships") or data.get("organizations") or []
    if isinstance(memberships, list) and memberships:
        first = memberships[0]
        org = first.get("organization") if isinstance(first, dict) else None
        if isinstance(org, dict):
            org_id = org.get("uuid") or ""
            caps = org.get("capabilities") or []
            if isinstance(caps, list):
                joined = " ".join(str(c).lower() for c in caps)
                if "max" in joined:
                    plan = "max"
                elif "pro" in joined:
                    plan = "pro"
        elif isinstance(first, dict):
            org_id = first.get("uuid") or first.get("id") or ""
    return email, org_id, plan, None
