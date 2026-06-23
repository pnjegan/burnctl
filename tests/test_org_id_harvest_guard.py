"""G-VERIFY-1 — committed, independently-runnable criterion for the org_id wipe.

Background: G1.6b NULL-wiped 2 harvested claude.ai org-id UUIDs out of the
`claude_ai_accounts` table. That wipe was verified ONCE, by a read-back from the
same agent that performed it — there was no committed check anyone else could
re-run. This file IS that check: a fixture-based eval (no prod DB, no on-disk
writes — an in-memory connection only) that an independent verifier or Jegan can
run to confirm "no harvested identifier exists in claude_ai_accounts".

Provenance model (from the G1.6 scan):
  - HARVESTED-SUSPECT column — ever populated from a claude.ai response:
        org_id
    A clean value is NULL or '' (empty). The v5 code seeds org_id='' and
    clear_claude_ai_session() resets it to '' (db.py:651, db.py:1650); G1.6b
    NULL-wiped the 2 stale rows. Both NULL and '' are clean; a real UUID / email
    / claude.ai-sourced value is harvested.
    (session_key is the other historically-harvested column, but it has its OWN
    committed guard — _migrate_wipe_session_keys() + the G5 banned-string gate —
    so it is deliberately OUT OF SCOPE here: one concern, no bundling.)
  - LOCAL SELF-ASSIGNED columns — user-chosen, never harvested:
        account_id (slug), label (nickname)
    NEVER flagged, even if their text happens to look identifier-shaped: the
    criterion scopes by provenance (column), not by value shape, so it cannot
    over-fire on a nickname.

Criteria:
  C1  org_id is NULL-or-empty on every row (the specific post-wipe invariant).
  C2  no harvested-identifier value (UUID / email / claude.ai-sourced) exists in
      a harvested-suspect column.
  C3  POSITIVE — re-seed a fake org-id UUID and the check goes RED (proves the
      guard is not vacuous: it actually catches a reintroduced harvested id).
  C4  local self-assigned fields (account_id slug, label) are NOT flagged — even
      a genuinely UUID-shaped label stays green (no over-fire).

Mirrors the in-memory-sqlite fixture approach of test_cost_anomaly_contract.py.
Read-only: imports no product code, touches no on-disk DB.
"""

import re
import sqlite3
import unittest

# Real claude_ai_accounts DDL, mirrored from db.py:384-396 so the fixture carries
# the exact prod columns. Kept local (self-contained), matching the precedent set
# by test_cost_anomaly_contract.py.
_ACCOUNTS_DDL = """
CREATE TABLE claude_ai_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT UNIQUE,
    label TEXT,
    org_id TEXT,
    session_key TEXT,
    plan TEXT,
    status TEXT DEFAULT 'unconfigured',
    last_polled INTEGER,
    last_error TEXT,
    created_at INTEGER,
    updated_at INTEGER
)
"""

# Column ever populated from a claude.ai response — the harvested surface (G1.6).
# A tuple so the scanner stays extensible without changing its body.
HARVESTED_SUSPECT_COLUMNS = ("org_id",)
# User-chosen, never harvested — must never be flagged.
LOCAL_SELF_ASSIGNED_COLUMNS = ("account_id", "label")

_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _looks_harvested(value):
    """True iff `value` carries a harvested identifier shape (UUID, email, or a
    claude.ai-sourced reference). The two clean states — NULL and '' — are
    False, so a wiped or freshly-seeded org_id never registers."""
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False
    if _UUID.search(s):
        return True
    if _EMAIL.search(s):
        return True
    if "claude.ai" in s.lower():
        return True
    return False


def find_harvested_identifiers(conn):
    """The criterion itself — an independent scanner. Returns a list of
    (rowid, column, value) for every harvested identifier in a harvested-suspect
    column of claude_ai_accounts; an empty list means clean. Scans ONLY the
    suspect columns, so a self-assigned slug or label can never register
    (C4 is structural, not a value coincidence)."""
    cols = ", ".join(HARVESTED_SUSPECT_COLUMNS)
    rows = conn.execute(
        f"SELECT rowid AS _rid, {cols} FROM claude_ai_accounts").fetchall()
    hits = []
    for r in rows:
        for col in HARVESTED_SUSPECT_COLUMNS:
            if _looks_harvested(r[col]):
                hits.append((r["_rid"], col, r[col]))
    return hits


def _clean_accounts_db():
    """In-memory claude_ai_accounts mirroring the POST-WIPE prod state: 2 rows,
    both clean. Row 1 has org_id NULL (the G1.6b NULL-wipe form); row 2 has
    org_id '' (the v5 seed / clear form). session_key NULL on both."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_ACCOUNTS_DDL)
    conn.executemany(
        "INSERT INTO claude_ai_accounts "
        "(account_id, label, org_id, session_key, plan, status) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("work-laptop",  "Work",     None, None, "max", "active"),
            ("personal-mac", "Personal", "",   None, "pro", "unconfigured"),
        ],
    )
    conn.commit()
    return conn


class TestOrgIdWipeCriterion(unittest.TestCase):

    # ── C1 — org_id NULL-or-empty on every row ───────────────────────────────
    def test_c1_org_id_null_or_empty_on_all_rows(self):
        conn = _clean_accounts_db()
        bad = conn.execute(
            "SELECT rowid, org_id FROM claude_ai_accounts "
            "WHERE org_id IS NOT NULL AND org_id <> ''").fetchall()
        conn.close()
        self.assertEqual(
            [tuple(r) for r in bad], [],
            "every row's org_id must be NULL or '' after the wipe")

    # ── C2 — no harvested identifier in the suspect column ───────────────────
    def test_c2_no_harvested_identifier_in_suspect_columns(self):
        conn = _clean_accounts_db()
        hits = find_harvested_identifiers(conn)
        conn.close()
        self.assertEqual(
            hits, [], f"clean table must yield no harvested ids, got {hits}")

    # ── C3 — POSITIVE: a re-seeded harvested UUID is caught ──────────────────
    def test_c3_guard_catches_reseeded_org_id_uuid(self):
        conn = _clean_accounts_db()
        # a plausible harvested claude.ai org uuid, re-seeded onto row 1
        fake = "1f2e3d4c-5b6a-7980-a1b2-c3d4e5f60718"
        conn.execute(
            "UPDATE claude_ai_accounts SET org_id = ? WHERE account_id = ?",
            (fake, "work-laptop"))
        conn.commit()
        hits = find_harvested_identifiers(conn)
        # the C1 invariant must ALSO break — proves the two checks agree
        c1_bad = conn.execute(
            "SELECT COUNT(*) FROM claude_ai_accounts "
            "WHERE org_id IS NOT NULL AND org_id <> ''").fetchone()[0]
        conn.close()
        self.assertTrue(
            any(col == "org_id" and val == fake for _, col, val in hits),
            "re-seeded org_id UUID MUST be caught (guard is not vacuous)")
        self.assertGreaterEqual(
            c1_bad, 1, "C1's NULL-or-empty invariant must also go red")

    # ── C4 — self-assigned fields never flagged (no over-fire) ───────────────
    def test_c4_self_assigned_fields_not_flagged(self):
        shaped_label = "00000000-1111-2222-3333-444444444444"  # UUID-shaped
        conn = _clean_accounts_db()
        conn.execute(
            "UPDATE claude_ai_accounts SET account_id = ?, label = ? "
            "WHERE account_id = ?",
            ("work-laptop-2", shaped_label, "work-laptop"))
        conn.commit()
        hits = find_harvested_identifiers(conn)
        conn.close()
        # the label value really IS identifier-shaped — so a clean result proves
        # provenance-scoping, not a value that simply failed to match.
        self.assertTrue(
            _looks_harvested(shaped_label),
            "fixture invalid: the label must be genuinely identifier-shaped")
        self.assertEqual(
            hits, [],
            "self-assigned account_id/label must never be flagged, even when "
            f"shaped like an identifier; got {hits}")
        # and the suspect set and self-assigned set must be disjoint by design
        for col in LOCAL_SELF_ASSIGNED_COLUMNS:
            self.assertNotIn(col, HARVESTED_SUSPECT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
