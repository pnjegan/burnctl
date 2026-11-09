"""Ingest a user-initiated claude.ai Data Export into burnctl.

Replaces `tools/legacy/chat_title_sync.py`, which read Chrome's History SQLite,
was EDR-flagged, and was dropped from the npm tarball in v4.5.8. The accepted
replacement direction is a user-initiated export:

    claude.ai -> Settings -> Privacy -> Export data  ->  conversations.json
    burnctl import-chats conversations.json --account personal_max

Why an export and not an API read: the Claude Code OAuth token is scoped for
Claude Code, and repurposing it against claude.ai's undocumented internal
endpoints is a Consumer Terms 3.7 risk that would get real users' accounts
flagged. An export is the user's own data, handed over deliberately. Nothing in
this module touches the network.

What lands where:

  * `browser_chat_sessions` -- one row per conversation, in the exact 8-field
    shape `POST /api/browser-chats` enforces (server.py:1386), so the HTTP and
    local paths cannot drift. `/api/browser-chats-recent` reads it unchanged.
  * `browser_samples` -- one row per message, with character counts split by
    sender. This is net-new: the Chrome-History feed never carried content.

Two honest limits, both visible in the data rather than papered over:

  * An export carries no browser and no page-visit count, so `browser` is the
    literal marker `export` and `page_visits` holds the MESSAGE count. Querying
    for real history rows means `WHERE browser <> 'export'`.
  * An export carries no token counts, so `cost_est_usd` and `cost_usd` stay
    NULL. A character count is not a token count and is not multiplied into one
    here.

Stdlib only, zero pip deps.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

# Marker written to browser_chat_sessions.browser for export-derived rows.
EXPORT_BROWSER = "export"

# browser_chat_sessions.title is NOT NULL and the endpoint rejects empty
# strings; claude.ai leaves `name` blank on conversations never given a title.
UNTITLED = "(untitled)"

SENDER_HUMAN = "human"


def load_db(path=None):
    """Open the usage DB. Candidate list matches overhead_audit.load_db(),
    which CLAUDE.md names as the no-hardcoded-path pattern. Never contains a
    maintainer path."""
    if path:
        return sqlite3.connect(path)
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def to_epoch(value):
    """ISO-8601 -> int epoch seconds. None for anything unparseable.

    Export timestamps come as '2026-05-01T05:00:00.000000Z'. Python's
    fromisoformat handles the trailing Z from 3.11, but the explicit swap keeps
    this working on older interpreters too. A naive timestamp is read as UTC,
    which is what the export emits.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _message_text(message):
    """Text of one message, across both export shapes.

    Older entries carry `text` as a plain string. Newer ones carry `content` as
    a list of typed blocks. Both occur in real exports, so both are read; blocks
    that are not text (tool use, attachments) contribute nothing.
    """
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                part = block.get("text")
                if isinstance(part, str):
                    parts.append(part)
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "".join(parts)
    text = message.get("text")
    return text if isinstance(text, str) else ""


def _conversations(obj):
    """Unwrap the export to a list of conversations.

    The file is normally a bare JSON array. Some exports wrap it in an object.
    Anything else is a shape this module does not understand, and guessing at it
    would produce silent partial imports.
    """
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("conversations", "chat_conversations", "data"):
            value = obj.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(
        "unrecognised export shape: expected a JSON array of conversations, "
        "or an object with a 'conversations' array"
    )


def parse_conversations(obj, account):
    """(sessions, messages, skipped) from an export object.

    `account` labels the rows; an export does not name its own account, and
    browser_chat_sessions.account is NOT NULL, so the caller must supply it.

    A conversation with no usable uuid, or with no parseable timestamp
    anywhere, is counted in `skipped` rather than raising: an export is one
    large array, and aborting on entry 400 of 900 would discard the other 899.
    """
    if not account or not str(account).strip():
        raise ValueError("account is required (browser_chat_sessions.account is NOT NULL)")
    account = str(account).strip()

    conversations = _conversations(obj)
    now = int(time.time())
    sessions = []
    messages = []
    skipped = 0

    for conversation in conversations:
        if not isinstance(conversation, dict):
            skipped += 1
            continue
        chat_uuid = str(conversation.get("uuid") or "").strip()
        if not chat_uuid:
            skipped += 1
            continue

        created = to_epoch(conversation.get("created_at"))
        updated = to_epoch(conversation.get("updated_at"))

        raw_messages = conversation.get("chat_messages")
        if not isinstance(raw_messages, list):
            raw_messages = []

        stamps = [t for t in (created, updated) if t is not None]
        pending = []
        for message in raw_messages:
            if not isinstance(message, dict):
                continue
            message_uuid = str(message.get("uuid") or "").strip()
            stamp = to_epoch(message.get("created_at")) or to_epoch(
                message.get("updated_at"))
            if stamp is not None:
                stamps.append(stamp)
            if not message_uuid or stamp is None:
                # message_uuid is UNIQUE and timestamp is NOT NULL; a message
                # missing either cannot be stored idempotently, so it is left
                # out of browser_samples while still counting toward the
                # conversation's window and message total.
                continue
            body = _message_text(message)
            is_human = str(message.get("sender") or "").strip().lower() == SENDER_HUMAN
            pending.append({
                "message_uuid": message_uuid,
                "chat_uuid": chat_uuid,
                "account_id": account,
                "role": str(message.get("sender") or "").strip() or None,
                "input_chars": len(body) if is_human else 0,
                "output_chars": 0 if is_human else len(body),
                "timestamp": stamp,
                "date_local": datetime.fromtimestamp(stamp).strftime("%Y-%m-%d"),
                "received_at": now,
            })

        if not stamps:
            # first_visit and last_visit are both NOT NULL ints; with no
            # timestamp anywhere there is nothing honest to put in them.
            skipped += 1
            continue

        first_visit = min(stamps)
        last_visit = max(stamps)
        if last_visit < first_visit:
            last_visit = first_visit

        title = str(conversation.get("name") or "").strip() or UNTITLED

        sessions.append({
            "chat_uuid": chat_uuid,
            "title": title,
            "account": account,
            "browser": EXPORT_BROWSER,
            "first_visit": first_visit,
            "last_visit": last_visit,
            "duration_min": max(0, round((last_visit - first_visit) / 60)),
            # An export has no page-visit count. The message total is the
            # closest honest analogue, and EXPORT_BROWSER marks the column as
            # carrying that meaning for these rows.
            "page_visits": max(1, len(raw_messages)),
        })
        messages.extend(pending)

    return sessions, messages, skipped


def upsert_sessions(conn, sessions):
    """Upsert session rows. Same statement as POST /api/browser-chats
    (server.py:1421) so the HTTP and local paths stay byte-identical."""
    if not sessions:
        return 0
    rows = [(
        s["chat_uuid"], s["title"], s["account"], s["browser"],
        int(s["first_visit"]), int(s["last_visit"]),
        int(s["duration_min"]), int(s["page_visits"]),
    ) for s in sessions]
    conn.executemany(
        """INSERT INTO browser_chat_sessions
             (chat_uuid, title, account, browser,
              first_visit, last_visit, duration_min, page_visits)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_uuid) DO UPDATE SET
             title = excluded.title,
             last_visit = excluded.last_visit,
             duration_min = excluded.duration_min,
             page_visits = excluded.page_visits,
             pushed_at = strftime('%s','now')""",
        rows,
    )
    return len(rows)


def upsert_messages(conn, messages):
    """Upsert per-message rows into browser_samples, keyed on the UNIQUE
    message_uuid so a re-import refreshes rather than duplicating.

    cost_usd is left NULL on purpose: an export carries characters, not tokens,
    and inventing a conversion would put a fabricated number in a cost column.
    """
    if not messages:
        return 0
    rows = [(
        m["message_uuid"], m["chat_uuid"], m["account_id"], m["role"],
        int(m["input_chars"]), int(m["output_chars"]),
        int(m["timestamp"]), m["date_local"], int(m["received_at"]),
    ) for m in messages]
    conn.executemany(
        """INSERT INTO browser_samples
             (message_uuid, chat_uuid, account_id, role,
              input_chars, output_chars, timestamp, date_local, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(message_uuid) DO UPDATE SET
             input_chars  = excluded.input_chars,
             output_chars = excluded.output_chars,
             role         = excluded.role,
             received_at  = excluded.received_at""",
        rows,
    )
    return len(rows)


def run_import(path, account, conn=None, dry_run=False, db_path=None):
    """Parse `path` and (unless dry_run) write it. Returns a summary dict.

    dry_run is STATE 2: it parses, reports exactly what would be written, and
    touches nothing.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        obj = json.load(fh)

    sessions, messages, skipped = parse_conversations(obj, account)
    summary = {
        "dry_run": bool(dry_run),
        "sessions": len(sessions),
        "messages": len(messages),
        "skipped": skipped,
        "account": account,
        "first_visit": min((s["first_visit"] for s in sessions), default=None),
        "last_visit": max((s["last_visit"] for s in sessions), default=None),
    }
    if dry_run:
        return summary

    owned = conn is None
    if owned:
        conn = load_db(db_path)
        if conn is None:
            raise RuntimeError(
                "no usage.db found (looked in data/usage.db and "
                "~/.burnctl/data/usage.db) -- run burnctl scan first")
    try:
        upsert_sessions(conn, sessions)
        upsert_messages(conn, messages)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        if owned:
            conn.close()
    return summary


def _fmt(epoch):
    if not epoch:
        return "-"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def cmd_import_chats(argv):
    """burnctl import-chats <conversations.json> --account <label>"""
    parser = argparse.ArgumentParser(
        prog="burnctl import-chats",
        description="Import a claude.ai Data Export (conversations.json).")
    parser.add_argument("path", help="path to conversations.json from the export")
    parser.add_argument("--account", required=True,
                        help="account label for these chats, e.g. personal_max")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and report, write nothing")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit the summary as JSON")
    parser.add_argument("--db", default=None, help="explicit path to usage.db")
    args = parser.parse_args(argv)

    if not os.path.exists(args.path):
        print(f"not found: {args.path}", file=sys.stderr)
        return 1
    try:
        summary = run_import(args.path, args.account,
                             dry_run=args.dry_run, db_path=args.db)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(summary, indent=2))
        return 0

    mode = "DRY RUN -- nothing written" if summary["dry_run"] else "imported"
    print()
    print(f"burnctl import-chats  ({mode})")
    print("=" * 58)
    print(f"  account       {summary['account']}")
    print(f"  conversations {summary['sessions']}")
    print(f"  messages      {summary['messages']}")
    print(f"  skipped       {summary['skipped']}")
    print(f"  window        {_fmt(summary['first_visit'])} "
          f"-> {_fmt(summary['last_visit'])}")
    print()
    if summary["skipped"]:
        print(f"  {summary['skipped']} conversation(s) had no uuid or no usable "
              "timestamp and were left out.")
    print("  Export rows carry browser='export'; page_visits holds the message")
    print("  count, and cost columns stay NULL (an export has no token counts).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(cmd_import_chats(sys.argv[1:]))
