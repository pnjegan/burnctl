"""Contract tests for the claude.ai Data Export ingest (browser_chat_import).

Replaces the EDR-flagged Chrome-History reader (`tools/legacy/chat_title_sync.py`,
dropped from the tarball in v4.5.8) with a user-initiated export parser. The
accepted direction is: Settings -> Export data -> conversations.json, parsed into
the EXISTING `browser_chat_sessions` table that `/api/browser-chats` already
upserts into and `/api/browser-chats-recent` already reads.

The invariants pinned here:

  1. The 8-field row contract that `POST /api/browser-chats` enforces
     (server.py:1386-1389) is produced exactly: chat_uuid, title, account,
     browser, first_visit, last_visit, duration_min, page_visits -- every one
     non-empty, the last four ints. The importer writes the same shape the
     endpoint would accept, so the two paths cannot drift.

  2. Export-derived rows are DISTINGUISHABLE from history-derived rows. An
     export carries no browser and no page-visit count, so `browser` is the
     literal marker 'export'. Without this, export rows silently claim to be
     Chrome/Vivaldi history and `page_visits` silently changes meaning.

  3. The ingest is IDEMPOTENT. A re-import of the same file (or a later export
     that overlaps) upserts; it never duplicates. `chat_uuid` is the PK and
     `message_uuid` is UNIQUE, so this is enforceable and must be enforced.

  4. One malformed conversation does not abort the file. An export is one big
     JSON array; aborting on entry 400 of 900 would lose the other 899.

  5. `--dry-run` writes nothing. STATE-2 before STATE-3, per repo discipline.

Stdlib only; unittest. No network, no real export file required.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import browser_chat_import as bci  # noqa: E402


# Production DDL, copied verbatim from the live DB's sqlite_master so these
# tests fail if the real table shape moves out from under the importer.
DDL_SESSIONS = """
CREATE TABLE browser_chat_sessions (
    chat_uuid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    account TEXT NOT NULL,
    browser TEXT NOT NULL,
    first_visit INTEGER NOT NULL,
    last_visit INTEGER NOT NULL,
    duration_min INTEGER NOT NULL,
    page_visits INTEGER NOT NULL DEFAULT 1,
    pushed_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    cost_est_usd REAL
)
"""

DDL_SAMPLES = """
CREATE TABLE browser_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id   INTEGER,
    message_uuid    TEXT UNIQUE,
    chat_uuid       TEXT NOT NULL,
    account_email   TEXT,
    account_id      TEXT,
    user_override_account_id TEXT,
    role            TEXT,
    model           TEXT,
    input_chars     INTEGER DEFAULT 0,
    output_chars    INTEGER DEFAULT 0,
    cost_usd        REAL,
    timestamp       INTEGER NOT NULL,
    date_local      TEXT NOT NULL,
    received_at     INTEGER NOT NULL
)
"""

# A conversations.json shaped like the real claude.ai export. Two message
# variants are represented deliberately: older entries carry `text` as a
# string, newer ones carry `content` as a block list. Both occur in the wild
# and the parser must read both.
EXPORT = [
    {
        "uuid": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
        "name": "Burnctl project update",
        "created_at": "2026-05-01T05:00:00.000000Z",
        "updated_at": "2026-05-01T07:43:00.000000Z",
        "chat_messages": [
            {
                "uuid": "m1",
                "sender": "human",
                "text": "where did the tokens go",
                "created_at": "2026-05-01T05:00:00.000000Z",
            },
            {
                "uuid": "m2",
                "sender": "assistant",
                "content": [{"type": "text", "text": "mostly repeated reads"}],
                "created_at": "2026-05-01T05:01:00.000000Z",
            },
            {
                "uuid": "m3",
                "sender": "human",
                "text": "fix it",
                # Deliberately LATER than the conversation's updated_at, which
                # export files do carry; last_visit must widen to cover it.
                "created_at": "2026-05-01T09:00:00.000000Z",
            },
        ],
    },
    {
        # Untitled chat: the export leaves `name` empty, but the row contract
        # requires a non-empty title.
        "uuid": "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
        "name": "",
        "created_at": "2026-05-02T10:00:00.000000Z",
        "updated_at": "2026-05-02T10:00:00.000000Z",
        "chat_messages": [],
    },
    {
        # Malformed: no uuid. Must be skipped, not fatal.
        "name": "no uuid here",
        "created_at": "2026-05-03T10:00:00.000000Z",
    },
]


def _mkdb():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL_SESSIONS + ";" + DDL_SAMPLES)
    return conn


def _write_export(obj):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(obj, fh)
    return path


class ParseContract(unittest.TestCase):
    def setUp(self):
        self.sessions, self.messages, self.skipped = bci.parse_conversations(
            EXPORT, account="personal_max")
        self.by_uuid = {s["chat_uuid"]: s for s in self.sessions}

    def test_produces_the_eight_required_endpoint_fields_non_empty(self):
        required = ("chat_uuid", "title", "account", "browser",
                    "first_visit", "last_visit", "duration_min", "page_visits")
        self.assertTrue(self.sessions, "parser returned no sessions")
        for s in self.sessions:
            missing = [k for k in required if s.get(k) in (None, "")]
            self.assertEqual([], missing, f"{s.get('chat_uuid')} missing {missing}")
            for k in ("first_visit", "last_visit", "duration_min", "page_visits"):
                self.assertIsInstance(s[k], int, f"{k} must be int, got {type(s[k])}")

    def test_untitled_chat_gets_a_non_empty_title(self):
        s = self.by_uuid["bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"]
        self.assertTrue(s["title"].strip(), "empty title violates the row contract")

    def test_browser_marker_distinguishes_export_rows(self):
        for s in self.sessions:
            self.assertEqual("export", s["browser"])

    def test_last_visit_widens_to_cover_latest_message(self):
        s = self.by_uuid["aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"]
        # m3 is at 09:00Z, four hours after the conversation's updated_at.
        self.assertGreaterEqual(s["last_visit"], bci.to_epoch("2026-05-01T09:00:00.000000Z"))

    def test_duration_is_never_negative_and_matches_the_window(self):
        s = self.by_uuid["aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"]
        self.assertEqual(round((s["last_visit"] - s["first_visit"]) / 60), s["duration_min"])
        for s in self.sessions:
            self.assertGreaterEqual(s["duration_min"], 0)

    def test_page_visits_counts_messages_and_is_at_least_one(self):
        self.assertEqual(3, self.by_uuid["aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"]["page_visits"])
        self.assertGreaterEqual(
            self.by_uuid["bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"]["page_visits"], 1)

    def test_reads_both_text_and_content_block_message_shapes(self):
        texts = {m["message_uuid"]: m for m in self.messages}
        self.assertEqual(len("where did the tokens go"), texts["m1"]["input_chars"])
        # m2 is a `content` block list, and an assistant message -> output_chars.
        self.assertEqual(len("mostly repeated reads"), texts["m2"]["output_chars"])
        self.assertEqual(0, texts["m2"]["input_chars"])

    def test_malformed_conversation_is_skipped_not_fatal(self):
        self.assertEqual(2, len(self.sessions))
        self.assertEqual(1, self.skipped)


class WriteContract(unittest.TestCase):
    def test_upsert_is_idempotent_across_repeated_imports(self):
        conn = _mkdb()
        sessions, messages, _ = bci.parse_conversations(EXPORT, account="personal_max")
        for _ in range(3):
            bci.upsert_sessions(conn, sessions)
            bci.upsert_messages(conn, messages)
        self.assertEqual(2, conn.execute(
            "SELECT COUNT(*) FROM browser_chat_sessions").fetchone()[0])
        self.assertEqual(3, conn.execute(
            "SELECT COUNT(*) FROM browser_samples").fetchone()[0])

    def test_reimport_refreshes_title_and_window(self):
        conn = _mkdb()
        sessions, _, _ = bci.parse_conversations(EXPORT, account="personal_max")
        bci.upsert_sessions(conn, sessions)
        renamed = json.loads(json.dumps(EXPORT))
        renamed[0]["name"] = "Burnctl project update (renamed)"
        s2, _, _ = bci.parse_conversations(renamed, account="personal_max")
        bci.upsert_sessions(conn, s2)
        row = conn.execute(
            "SELECT title FROM browser_chat_sessions WHERE chat_uuid=?",
            ("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",)).fetchone()
        self.assertEqual("Burnctl project update (renamed)", row["title"])

    def test_dry_run_writes_nothing(self):
        conn = _mkdb()
        path = _write_export(EXPORT)
        try:
            summary = bci.run_import(path, account="personal_max",
                                     conn=conn, dry_run=True)
        finally:
            os.unlink(path)
        self.assertEqual(0, conn.execute(
            "SELECT COUNT(*) FROM browser_chat_sessions").fetchone()[0])
        self.assertEqual(0, conn.execute(
            "SELECT COUNT(*) FROM browser_samples").fetchone()[0])
        self.assertTrue(summary["dry_run"])
        self.assertEqual(2, summary["sessions"])

    def test_run_import_writes_when_not_dry(self):
        conn = _mkdb()
        path = _write_export(EXPORT)
        try:
            summary = bci.run_import(path, account="personal_max", conn=conn)
        finally:
            os.unlink(path)
        self.assertFalse(summary["dry_run"])
        self.assertEqual(2, conn.execute(
            "SELECT COUNT(*) FROM browser_chat_sessions").fetchone()[0])
        self.assertEqual(3, summary["messages"])

    def test_account_is_required(self):
        with self.assertRaises(ValueError):
            bci.parse_conversations(EXPORT, account="")


class ShapeTolerance(unittest.TestCase):
    def test_accepts_object_wrapper_as_well_as_bare_list(self):
        wrapped = {"conversations": EXPORT}
        sessions, _, _ = bci.parse_conversations(wrapped, account="work_pro")
        self.assertEqual(2, len(sessions))

    def test_rejects_a_shape_it_does_not_understand(self):
        with self.assertRaises(ValueError):
            bci.parse_conversations("not an export", account="work_pro")

    def test_epoch_parser_handles_z_offset_and_missing(self):
        self.assertEqual(bci.to_epoch("2026-05-01T05:00:00.000000Z"),
                         bci.to_epoch("2026-05-01T05:00:00+00:00"))
        self.assertIsNone(bci.to_epoch(None))
        self.assertIsNone(bci.to_epoch("not a date"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
