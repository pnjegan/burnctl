"""claude.ai account status helpers.

v5 clean architecture (2026-06-20): the consumer-endpoint polling that
used to live here was REMOVED. burnctl no longer calls claude.ai's
consumer API, no longer reads or stores any session credential, and no
longer derives the 5-hour-window % from a browser cookie. Browser
attribution now comes only from the no-cookie extension
(document.title + URL + timestamp → /api/extension/samples).

What remains is a tiny in-memory status registry so the dashboard's
existing claude.ai panels render without error. Nothing populates it any
more, so the getters simply return empty/zero — a graceful, credential-
free degradation. The old polling/setup functions (poll_all, poll_single,
fetch_usage, verify_session, fetch_org_id, setup_account, _safe_request)
were deleted along with the credential path; see ARCHIVE/ for the retired
collectors.
"""

import threading

_last_poll_time = 0
_account_statuses = {}
_state_lock = threading.Lock()


def get_last_poll_time():
    with _state_lock:
        return _last_poll_time


def get_account_statuses():
    with _state_lock:
        return dict(_account_statuses)
