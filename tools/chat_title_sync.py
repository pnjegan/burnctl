#!/usr/bin/env python3
"""chat_title_sync.py — Push claude.ai chat URLs from local Chromium History
DBs to the burnctl dashboard's /api/browser-chats endpoint.

What it does
  Scans Chrome / Vivaldi / Chromium History DBs across all configured
  profiles, extracts URLs matching claude.ai/chat/<uuid> (and the
  /projects/<uuid>/chat/<uuid> nested form), and POSTs them in batches.

Configure
  --config <path>   default ~/claudash/chat_title_sync.conf
  JSON shape (abbreviated):
    {
      "sync_token": "<paste from `burnctl claude-ai --sync-token`>",
      "endpoint":   "http://127.0.0.1:8080/api/browser-chats",
      "profile_map": [{"browser":"Chrome","profile_dir":"Default",
                       "account_id":"work_pro"}]
    }

Discover profiles
  python3 chat_title_sync.py --list-profiles

Schedule (snippets in README, NOT here)
  macOS    launchd plist  (see README §chat_title_sync — scheduling)
  Linux    systemd timer  (see README §chat_title_sync — scheduling)
  Windows  schtasks /create  (see README §chat_title_sync — scheduling)

Known limitations
  1. duration_min inflation per F7: span = (last_visit - first_visit) // 60
     reflects browser-recorded earliest→latest visit, not active time on page.
     Matches v4.4.0 semantics intentionally.
  2. Project chats prefix-encoded in title as "[proj:<8 hex>] <title>"
     pending a server schema migration adding browser_chat_sessions.project_uuid.
  3. WAL caveat: SQLite immutable-mode read may miss the last few seconds of
     browser activity. Acceptable — collector runs every 30 min.
  4. UPSERT immutability: server-side upsert keeps account/browser/first_visit
     at first-write; only title/last_visit/duration_min/page_visits refresh.

TODO (separate commits, not this one):
  - README scheduling snippets (next session turn).
  - Server-side X-Sync-Token enforcement on /api/browser-chats.
  - Schema migration adding browser_chat_sessions.project_uuid.
"""

import argparse
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ── Constants ──

# Microseconds since 1601-01-01 UTC → Unix epoch (seconds since 1970-01-01 UTC).
# unix_seconds = chromium_us // 1_000_000 - CHROMIUM_EPOCH_OFFSET.
CHROMIUM_EPOCH_OFFSET = 11_644_473_600

# F10: single regex for top-level chats AND project chats.
# Group 1 = project_uuid (None for top-level); Group 2 = chat_uuid (always set).
CLAUDE_CHAT_RE = re.compile(
    r"^https?://claude\.ai"
    r"(?:/projects/([0-9a-f-]{36}))?"
    r"/chat/([0-9a-f-]{36})"
    r"(?:[/?#]|$)"
)

DEFAULT_CONFIG_PATH = "~/claudash/chat_title_sync.conf"
DEFAULT_ENDPOINT = "http://127.0.0.1:8080/api/browser-chats"

# Sanity bounds on visit timestamps (per investigation finding #2).
# 2024-01-01 00:00:00 UTC = 1704067200.
SANE_MIN_EPOCH = 1704067200

BATCH_SIZE = 100
POST_TIMEOUT = 15
RETRY_5XX_SLEEP = 2

# (browser_name, linux_subpath, mac_subpath, windows_subpath_under_LOCALAPPDATA)
BROWSERS = [
    ("Chrome",
     ".config/google-chrome",
     "Library/Application Support/Google/Chrome",
     "Google\\Chrome\\User Data"),
    ("Vivaldi",
     ".config/vivaldi",
     "Library/Application Support/Vivaldi",
     "Vivaldi\\User Data"),
    ("Chromium",
     ".config/chromium",
     "Library/Application Support/Chromium",
     "Chromium\\User Data"),
]

# Per investigation finding #9: pre-filter at SQL level by LIKE; apply F10
# regex in Python (no SQLite REGEXP by default).
URLS_QUERY = """
SELECT
  urls.url,
  urls.title,
  MIN(visits.visit_time) AS first_visit_us,
  MAX(visits.visit_time) AS last_visit_us,
  COUNT(visits.id)       AS page_visits
FROM urls
JOIN visits ON visits.url = urls.id
WHERE urls.url LIKE 'https://claude.ai/%'
GROUP BY urls.url
"""


# ── Argparse ──

def _parse_args(argv):
    # argparse style follows cli.py:219-224 (mac-sync.py uses inline
    # constants and has no argparse — closest sibling pattern is cli.py).
    p = argparse.ArgumentParser(
        prog="chat_title_sync",
        description=(
            "Collect claude.ai chat URLs from local browser History DBs "
            "and POST them to the burnctl dashboard."
        ),
        epilog=(
            "Examples:\n"
            "  python3 chat_title_sync.py --config ~/claudash/chat_title_sync.conf\n"
            "  python3 chat_title_sync.py --list-profiles\n"
            "  python3 chat_title_sync.py --dry-run -vv"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="Path to JSON config file (default: %(default)s).",
    )
    p.add_argument(
        "--list-profiles",
        action="store_true",
        help="List browser profile dirs on this machine and exit. "
             "Does NOT read History DBs.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect rows but do NOT POST. Prints what would be sent.",
    )
    p.add_argument(
        "--show-titles",
        action="store_true",
        help="At -vv, log full chat titles (PII; opt-in for debugging only). "
             "Without this flag titles are truncated to 20 chars in DEBUG logs.",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity: default=WARNING, -v=INFO, -vv=DEBUG.",
    )
    return p.parse_args(argv)


def _setup_logging(verbose_count):
    level = logging.WARNING
    if verbose_count >= 2:
        level = logging.DEBUG
    elif verbose_count == 1:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


# ── Config loading ──

def _load_config(path):
    """Load and validate JSON config. Calls sys.exit(2) on any error."""
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        print(f"config error: file not found: {expanded}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(expanded, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"config error: cannot parse {expanded}: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"config error: {expanded} is not a JSON object", file=sys.stderr)
        sys.exit(2)

    token = (data.get("sync_token") or "").strip()
    if not token:
        # F1 contract: this exact stderr text is part of the operator UX.
        print("config error: X-Sync-Token not configured", file=sys.stderr)
        sys.exit(2)

    endpoint = (data.get("endpoint") or DEFAULT_ENDPOINT).strip()
    profile_map = data.get("profile_map") or []
    if not isinstance(profile_map, list):
        print("config error: profile_map must be a list", file=sys.stderr)
        sys.exit(2)

    return {
        "sync_token": token,
        "endpoint": endpoint,
        "profile_map": profile_map,
    }


def _mask_token(token):
    """Mask all but first 4 + last 2 chars. Never log raw token."""
    if not token:
        return "<empty>"
    if len(token) <= 6:
        return "***"
    return token[:4] + "..." + token[-2:]


# ── Profile discovery ──

def _browser_root(browser_entry):
    """Return the per-platform root dir under which profile dirs live, or None."""
    _name, posix_sub, mac_sub, win_sub = browser_entry
    sysname = platform.system()
    if sysname == "Darwin":
        return Path.home() / mac_sub
    if sysname == "Linux":
        return Path.home() / posix_sub
    if sysname == "Windows":
        local_app = os.environ.get("LOCALAPPDATA")
        if not local_app:
            return None
        return Path(local_app) / win_sub
    return None


def _is_profile_dir(p):
    """Profile dirs contain a History sqlite file."""
    try:
        return p.is_dir() and (p / "History").is_file()
    except OSError:
        return False


def _discover_profiles():
    """Yield (browser_name, profile_dir_name, history_path) for each profile.

    Globs for "Default" and "Profile *" — does NOT hardcode "Default".
    """
    for entry in BROWSERS:
        name = entry[0]
        root = _browser_root(entry)
        if not root or not root.exists():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda c: c.name)
        except OSError as e:
            logging.warning("cannot list %s: %s", root, e)
            continue
        for child in children:
            if child.name != "Default" and not child.name.startswith("Profile "):
                continue
            if _is_profile_dir(child):
                yield (name, child.name, child / "History")


# ── --list-profiles ──

def _cmd_list_profiles(args):
    cfg_map = []
    expanded = os.path.expanduser(args.config)
    if os.path.exists(expanded):
        try:
            cfg = _load_config(args.config)
            cfg_map = cfg.get("profile_map") or []
        except SystemExit:
            cfg_map = []  # bad config — list still works without it.

    keys = set()
    for m in cfg_map:
        if isinstance(m, dict):
            keys.add((m.get("browser"), m.get("profile_dir")))

    found_any = False
    for browser, profile_dir, history_path in _discover_profiles():
        found_any = True
        in_map = "yes" if (browser, profile_dir) in keys else "no"
        print(
            f"{browser:8s}  profile={profile_dir:15s}  "
            f"path={history_path.parent}  in config map: {in_map}"
        )
    if not found_any:
        print("No supported browser profiles found on this machine.")
    return 0


# ── History DB read (F6) ──

def _open_history_ro(history_path):
    """Open History DB read-only.

    Primary: sqlite3 URI mode=ro&immutable=1 — no locks, no temp copy.
    Fallback: shutil.copy2 to a NamedTemporaryFile, open the copy.
    Matches sibling collector pattern for cookies DB
    (see tools/mac-sync.py:183-185 for tempfile.NamedTemporaryFile usage,
    and tools/mac-sync.py:117-128 for the copy-then-open shape).

    Returns (sqlite3.Connection, tmp_path_or_None). Caller MUST close
    the connection and unlink tmp_path if not None.
    """
    uri = f"file:{history_path}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        return conn, None
    except sqlite3.OperationalError as e:
        logging.warning(
            "immutable mode failed, falling back to copy: %s (%s)",
            history_path, e,
        )

    # Fallback: copy History only. Do NOT copy WAL/SHM — F6 design.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".history.db")
    tmp.close()
    try:
        shutil.copy2(history_path, tmp.name)
    except OSError as e:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise sqlite3.OperationalError(f"cannot copy History DB: {e}") from e

    try:
        conn = sqlite3.connect(tmp.name, timeout=5)
    except sqlite3.Error:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    return conn, tmp.name


def _scan_profile(history_path):
    """Yield raw row dicts from one profile's History DB.

    Pre-filtered by SQL `LIKE 'https://claude.ai/%'` per finding #9.
    Caller applies the F10 regex.
    """
    try:
        conn, tmp_path = _open_history_ro(history_path)
    except sqlite3.OperationalError as e:
        logging.error("cannot open History DB %s: %s", history_path, e)
        return

    try:
        try:
            cur = conn.execute(URLS_QUERY)
            rows = cur.fetchall()
        except sqlite3.Error as e:
            logging.error("query failed on %s: %s", history_path, e)
            return

        for row in rows:
            yield {
                "url": row[0] or "",
                "title": row[1] or "",
                "first_visit_us": int(row[2] or 0),
                "last_visit_us": int(row[3] or 0),
                "page_visits": int(row[4] or 0),
            }
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Row processing ──

def _chromium_us_to_unix(us):
    return us // 1_000_000 - CHROMIUM_EPOCH_OFFSET


def _truncate_title(title, show_full):
    if show_full:
        return title
    return (title[:20] + "...") if len(title) > 20 else title


def _process_row(raw, account_id, browser, sane_max):
    """Validate + transform one raw row into a POST-ready chat dict.

    Returns a tuple (result, skip_reason) where:
      - (dict, None) on success
      - (None, "regex") if URL doesn't match F10 (LIKE filter is broader)
      - (None, "sane")  if timestamps fall outside the sane range
    """
    url = raw["url"]
    m = CLAUDE_CHAT_RE.match(url)
    if not m:
        return None, "regex"

    project_uuid = m.group(1)
    chat_uuid = m.group(2)

    first_visit = _chromium_us_to_unix(raw["first_visit_us"])
    last_visit = _chromium_us_to_unix(raw["last_visit_us"])

    if not (SANE_MIN_EPOCH <= first_visit <= sane_max) \
       or not (SANE_MIN_EPOCH <= last_visit <= sane_max):
        # Don't include the URL in the warning — chat_uuid is enough to grep.
        logging.warning(
            "timestamp out of sane range, skipping chat=%s "
            "(first=%d last=%d)",
            chat_uuid, first_visit, last_visit,
        )
        return None, "sane"

    duration_min = max(0, (last_visit - first_visit) // 60)

    title = (raw["title"] or "").strip() or "(untitled)"
    if project_uuid:
        title = f"[proj:{project_uuid[:8]}] {title}"

    return {
        "chat_uuid": chat_uuid,
        "title": title,
        "account": account_id,
        "browser": browser,
        "first_visit": int(first_visit),
        "last_visit": int(last_visit),
        "duration_min": int(duration_min),
        "page_visits": int(raw["page_visits"]),
    }, None


# ── POST batching ──

def _post_batch(endpoint, token, batch):
    """POST one batch. Returns (ok, status_code).

    HTTP style follows tools/mac-sync.py:337-369 (Request + urlopen,
    JSON body, X-Sync-Token header). On URLError / OSError this raises;
    caller handles connection-refused as exit-1.
    """
    body = json.dumps({"chats": batch}).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Sync-Token": token,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            status = resp.status
            try:
                resp.read()
            except OSError:
                pass
            return (200 <= status < 300, status)
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except OSError:
            err_body = ""
        logging.error(
            "POST %s -> HTTP %s body=%s",
            endpoint, e.code, err_body[:500],
        )
        return (False, e.code)


def _push_chats(endpoint, token, chats):
    """POST chats in batches of BATCH_SIZE. Returns True if all batches OK."""
    all_ok = True
    total = len(chats)
    n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = chats[i: i + BATCH_SIZE]
        idx = i // BATCH_SIZE + 1

        try:
            ok, status = _post_batch(endpoint, token, batch)
        except (URLError, OSError) as e:
            # F-spec: connection refused → exit 1 immediately, no retries.
            logging.error("endpoint unreachable: %s (%s)", endpoint, e)
            return False

        if not ok and 500 <= status < 600:
            logging.warning(
                "POST batch %d/%d 5xx (HTTP %d), retrying once after %ds",
                idx, n_batches, status, RETRY_5XX_SLEEP,
            )
            time.sleep(RETRY_5XX_SLEEP)
            try:
                ok, status = _post_batch(endpoint, token, batch)
            except (URLError, OSError) as e:
                logging.error(
                    "endpoint unreachable on retry: %s (%s)", endpoint, e,
                )
                return False

        if not ok:
            logging.error(
                "POST batch %d/%d failed (HTTP %s); continuing with next batch",
                idx, n_batches, status,
            )
            all_ok = False
            continue

        logging.info(
            "POST sent: batch %d/%d (%d chats) -> %d",
            idx, n_batches, len(batch), status,
        )

    return all_ok


# ── Sync command ──

def _cmd_sync(args):
    cfg = _load_config(args.config)
    token = cfg["sync_token"]
    endpoint = cfg["endpoint"]
    profile_map = cfg["profile_map"]

    logging.info(
        "config loaded; token=%s endpoint=%s profiles_in_map=%d",
        _mask_token(token), endpoint, len(profile_map),
    )

    # Build (browser, profile_dir) -> account_id lookup.
    map_lookup = {}
    for entry in profile_map:
        if not isinstance(entry, dict):
            continue
        b = (entry.get("browser") or "").strip()
        pd = (entry.get("profile_dir") or "").strip()
        aid = (entry.get("account_id") or "").strip()
        if b and pd and aid:
            map_lookup[(b, pd)] = aid

    sane_max = int(time.time()) + 86400  # F-spec: now + 1 day.
    all_chats = []
    profiles_seen = 0
    profiles_used = 0

    for browser, profile_dir, history_path in _discover_profiles():
        profiles_seen += 1
        account_id = map_lookup.get((browser, profile_dir))
        if not account_id:
            logging.info(
                "skipping profile not in map: %s/%s", browser, profile_dir,
            )
            continue
        profiles_used += 1

        rows_seen = 0
        rows_eligible = 0
        skipped = {"regex": 0, "sane": 0}

        try:
            for raw in _scan_profile(history_path):
                rows_seen += 1
                processed, reason = _process_row(
                    raw, account_id, browser, sane_max,
                )
                if processed is None:
                    skipped[reason] = skipped.get(reason, 0) + 1
                    continue
                rows_eligible += 1
                all_chats.append(processed)
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    title_show = _truncate_title(
                        processed["title"], args.show_titles,
                    )
                    logging.debug(
                        "eligible chat=%s account=%s title=%s",
                        processed["chat_uuid"], account_id, title_show,
                    )
        except sqlite3.Error as e:
            logging.error(
                "scan failed for %s/%s: %s", browser, profile_dir, e,
            )
            continue

        logging.info(
            "profile %s/%s: seen=%d eligible=%d skipped_regex=%d skipped_sane=%d",
            browser, profile_dir, rows_seen, rows_eligible,
            skipped.get("regex", 0), skipped.get("sane", 0),
        )

    logging.info(
        "collected %d chats from %d/%d profiles",
        len(all_chats), profiles_used, profiles_seen,
    )

    if not all_chats:
        print("collected 0 chats — nothing to send.")
        return 0

    if args.dry_run:
        n_batches = (len(all_chats) + BATCH_SIZE - 1) // BATCH_SIZE
        print(
            f"DRY RUN: would POST {len(all_chats)} chats to {endpoint} "
            f"in {n_batches} batch(es) of up to {BATCH_SIZE}"
        )
        return 0

    ok = _push_chats(endpoint, token, all_chats)
    if not ok:
        print(
            f"sent {len(all_chats)} chats to {endpoint} with errors",
            file=sys.stderr,
        )
        return 1

    print(f"sent {len(all_chats)} chats to {endpoint}")
    return 0


# ── Entrypoint ──

def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    _setup_logging(args.verbose)
    if args.list_profiles:
        return _cmd_list_profiles(args)
    return _cmd_sync(args)


if __name__ == "__main__":
    sys.exit(main())
