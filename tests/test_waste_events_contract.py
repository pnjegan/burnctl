"""Write-path contract for waste_events — V4 / V5a / V5b.

UNVALIDATED_AUDIT.md deferred these as VERIFIABLE-NEXT: SESSION-STATE's *CIC*
block claims the persist path is "idempotent UPSERT (no dupes)", "rowid
read-back", and "ADD-only (other patterns untouched)" — but those were only ever
proven once, by the agent that did the prod write. This locks them as a
re-runnable criterion.

WHY this path matters most: the stateless checker leans hardest on the write.
`db.insert_waste_event` (db.py) has no try/except, but every caller wraps it
`try/except -> print(stderr)`, so in the persist path a no-op or raising insert
is SWALLOWED — no row, nothing fails loudly. Read-back is the only catch. If
read-back can be fooled, every "done" the checker certifies is a lie.

Shape mirrors tests/test_cost_anomaly_contract.py: every criterion carries a
POSITIVE case proving the real path holds, plus an in-file NON-VACUITY case
proving the verification actually discriminates (the runaway-fixture lesson).
STATE-3 additionally re-runs this whole module against a faulted db.py copy per
fault (UPSERT->plain INSERT, silent no-op, destructive rewrite) — each must go
red. See the commit/SESSION-STATE for that VERIFY table + reproduce command.

The write path is CALLED, never reimplemented. Schema comes from the real
db.init_db() into a TEMP SQLite (never prod data/usage.db); the idempotency key
is read from the live schema via PRAGMA, so the criteria survive a schema-add.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import db

# A pattern_type label for the test rows. The write path is pattern-agnostic
# (insert_waste_event does not validate against the allowlist), so any value
# exercises the same contract.
PT = "cost_anomaly"
KEY_COLS = {"session_id", "pattern_type"}  # asserted to BE the real UNIQUE key


def _real_schema_db():
    """Temp on-disk SQLite built by the REAL db.init_db(); never prod.

    DB_PATH is restored immediately so nothing else can resolve to the temp DB.
    Returns (conn, tmpdir); caller removes tmpdir.
    """
    tmpdir = tempfile.mkdtemp(prefix="burnctl-waste-contract-")
    temp_db = os.path.join(tmpdir, "data", "usage.db")
    orig = db.DB_PATH
    db.DB_PATH = temp_db
    try:
        db.init_db()
    finally:
        db.DB_PATH = orig
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    return conn, tmpdir


def _write(conn, sid, pattern=PT, severity="red", cost=100.0, detail=None):
    """Drive the REAL write path (not a reimplementation)."""
    db.insert_waste_event(conn, sid, "P", "a", pattern, severity, 10, cost,
                          detail if detail is not None else {})
    conn.commit()


def _readback_by_rowid(conn, sid, pattern=PT):
    """Confirm a write by reading the row back BY ROWID (waste_events.id).

    There is no dedicated read-back helper in the write path, so this is the
    verification a human-at-the-gate performs. Returns the row, or None if the
    write left nothing — which is exactly how a swallowed/no-op insert is caught.
    """
    locator = conn.execute(
        "SELECT id FROM waste_events WHERE session_id=? AND pattern_type=?",
        (sid, pattern),
    ).fetchone()
    if locator is None:
        return None
    return conn.execute(
        "SELECT * FROM waste_events WHERE id=?", (locator["id"],)
    ).fetchone()


def _unique_key_cols(conn):
    """The idempotency key, read from the LIVE schema (no hand-copied DDL)."""
    for idx in conn.execute("PRAGMA index_list('waste_events')"):
        if idx["unique"]:
            cols = {c["name"] for c in conn.execute(
                f"PRAGMA index_info('{idx['name']}')")}
            if cols == KEY_COLS:
                return cols
    return None


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn, self._tmp = _real_schema_db()

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)


# ── V4 — idempotent UPSERT on (session_id, pattern_type) ──────────────────────
class TestV4IdempotentUpsert(_Base):
    def test_idempotency_key_is_the_real_schema_unique(self):
        # Symbolic: the key the contract depends on actually exists, UNIQUE.
        self.assertEqual(_unique_key_cols(self.conn), KEY_COLS)

    def test_same_key_twice_yields_exactly_one_row(self):
        _write(self.conn, "S", severity="amber", cost=10.0)
        _write(self.conn, "S", severity="red", cost=999.0)  # same key, re-write
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM waste_events "
            "WHERE session_id='S' AND pattern_type=?", (PT,)).fetchone()["c"]
        self.assertEqual(n, 1, "UPSERT must keep exactly ONE row per key")
        row = _readback_by_rowid(self.conn, "S")
        self.assertEqual(row["severity"], "red", "UPSERT must reflect the re-write")
        self.assertAlmostEqual(row["token_cost"], 999.0)

    def test_nonvacuous_plain_insert_of_dup_key_is_rejected(self):
        # NON-VACUITY: a non-UPSERT plain INSERT of the same key is rejected by
        # the UNIQUE constraint. This is the failure a UPSERT->plain-INSERT fault
        # walks into — proving the V4 assertion above is not vacuous.
        _write(self.conn, "S")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO waste_events "
                "(session_id, pattern_type, severity, turn_count, token_cost, "
                " detected_at, detail_json) VALUES ('S', ?, 'red', 1, 1.0, 1, '{}')",
                (PT,))


# ── V5a — every insert is confirmed by rowid read-back ────────────────────────
class TestV5aRowidReadback(_Base):
    def test_insert_confirmed_by_rowid_readback_with_payload(self):
        _write(self.conn, "S", detail={"k": "v"})
        row = _readback_by_rowid(self.conn, "S")
        self.assertIsNotNone(row, "a real write must be confirmable by rowid")
        self.assertEqual(json.loads(row["detail_json"]), {"k": "v"})

    def test_nonvacuous_readback_detects_absence(self):
        # NON-VACUITY: read-back of a key that was never written returns None
        # (caught), not a false confirm. The 'silent no-op' fault relies on
        # exactly this to go red.
        self.assertIsNone(_readback_by_rowid(self.conn, "GHOST"))


# ── V5b — ADD-only: no UPDATE/DELETE rewrites an existing row in the write path ─
class TestV5bAddOnly(_Base):
    def test_new_write_leaves_existing_row_byte_identical(self):
        _write(self.conn, "A", cost=10.0)
        a_before = tuple(_readback_by_rowid(self.conn, "A"))
        _write(self.conn, "B", cost=20.0)  # a DIFFERENT key
        a_after = tuple(_readback_by_rowid(self.conn, "A"))
        self.assertEqual(a_after, a_before,
                         "writing a new row must not rewrite an existing one")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM waste_events").fetchone()["c"], 2,
            "row count must grow by one — nothing deleted")

    def test_upsert_preserves_rowid_identity(self):
        # ADD-only at row level: a same-key re-write UPDATES in place; it must
        # NOT delete-and-reinsert (which would mint a new rowid).
        _write(self.conn, "A", cost=10.0)
        rid1 = _readback_by_rowid(self.conn, "A")["id"]
        _write(self.conn, "A", cost=50.0)
        rid2 = _readback_by_rowid(self.conn, "A")["id"]
        self.assertEqual(rid1, rid2,
                         "UPSERT must preserve the rowid (no destructive rewrite)")

    def test_nonvacuous_destructive_rewrite_changes_rowid(self):
        # NON-VACUITY: prove rowid-stability discriminates — a delete-then-
        # reinsert (the rewrite the V5b fault introduces) DOES mint a new rowid,
        # which the assertion above would catch.
        _write(self.conn, "A", cost=10.0)
        rid1 = _readback_by_rowid(self.conn, "A")["id"]
        self.conn.execute(
            "DELETE FROM waste_events WHERE session_id='A' AND pattern_type=?", (PT,))
        self.conn.execute(
            "INSERT INTO waste_events "
            "(session_id, pattern_type, severity, turn_count, token_cost, "
            " detected_at, detail_json) VALUES ('A', ?, 'red', 1, 10.0, 1, '{}')",
            (PT,))
        self.conn.commit()
        rid2 = _readback_by_rowid(self.conn, "A")["id"]
        self.assertNotEqual(rid1, rid2,
                            "delete+reinsert mints a new rowid — check is non-vacuous")


if __name__ == "__main__":
    unittest.main()
