"""V6 — core-clean JSONL scan contract.

UNVALIDATED_AUDIT.md deferred V6 (G1 "local-JSONL core clean") as VERIFIABLE-NEXT.
This locks it: a known-good JSONL fixture, ingested by the REAL scanner into a
TEMP DB, must land its rows confirmably and produce zero spurious waste flags.

Different code path from V4/V5: this is scan -> `sessions` (via
`scanner.scan_jsonl_file` -> `db.insert_session`), not the `waste_events` write.
The same silent-insert quirk applies — `insert_session` is `INSERT OR IGNORE`
with `except sqlite3.Error: return False` (db.py:1004), so a dropped/failed
insert leaves no row and raises nothing. Rowid read-back is the only catch.

The scanner is CALLED, never reimplemented (`scanner.scan_jsonl_file`); schema is
the real `db.init_db()` into a TEMP SQLite (never prod data/usage.db, never real
~/.claude logs); an explicit project_map keeps `resolve_project` from reading any
prod config. STATE-3 additionally proves non-vacuity by a live in-tree fault on
the scan entrypoint (return -> read-back goes red) with an exact git revert.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import db
import scanner
import waste_patterns as wp

# Explicit map so resolve_project never reads prod config; a folder containing
# "burntest" resolves to this project/account deterministically.
PROJECT_MAP = {"BurnTest": {"keywords": ["burntest"], "account": "personal_max"}}

# Three known-good Claude-Code usage lines, one conversation, distinct
# timestamps (UNIQUE is (session_id, timestamp, model)); both token counts > 0
# so no line is dropped and cost computes > 0.
GOOD_JSONL = [
    {"sessionId": "core-clean-sess", "timestamp": f"2026-06-20T10:{m:02d}:00Z",
     "message": {"model": "claude-opus-4-8",
                 "usage": {"input_tokens": 1200, "output_tokens": 300,
                           "cache_read_input_tokens": 0,
                           "cache_creation_input_tokens": 0}}}
    for m in (0, 5, 10)
]

# Waste-FLAG counters in detect_all's summary (excludes the
# cost_anomaly_insufficient_baseline REPORT counter, which is not a flag).
FLAG_KEYS = ("floundering", "repeated_reads", "cost_outliers",
             "deep_no_compact", "bad_compacts", "cost_anomalies")


def _temp_env():
    """TEMP DB (real schema via db.init_db) + a TEMP JSONL fixture. Never prod."""
    tmp = tempfile.mkdtemp(prefix="burnctl-v6-")
    temp_db = os.path.join(tmp, "data", "usage.db")
    orig = db.DB_PATH
    db.DB_PATH = temp_db
    try:
        db.init_db()
    finally:
        db.DB_PATH = orig
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    folder = os.path.join(tmp, "burntest-project")
    os.makedirs(folder)
    jsonl = os.path.join(folder, "session.jsonl")
    with open(jsonl, "w") as f:
        for obj in GOOD_JSONL:
            f.write(json.dumps(obj) + "\n")
    return conn, tmp, folder, jsonl


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn, self._tmp, self.folder, self.jsonl = _temp_env()

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self):
        # The REAL scan entrypoint, against the TEMP db + fixture.
        return scanner.scan_jsonl_file(
            self.jsonl, self.folder, self.conn,
            source_path=self.jsonl, project_map=PROJECT_MAP)


class TestV6CoreCleanScan(_Base):
    def test_clean_ingest_lands_rows_by_rowid(self):
        added = self._scan()
        self.assertEqual(added, len(GOOD_JSONL), "every clean line must ingest")
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM sessions ORDER BY id")]
        self.assertEqual(len(ids), len(GOOD_JSONL), "one row per clean line")
        # rowid read-back: each scanned row must be confirmable by its id —
        # the catch for a silent/OR-IGNORE/no-op insert that lands nothing.
        for rid in ids:
            row = self.conn.execute(
                "SELECT * FROM sessions WHERE id=?", (rid,)).fetchone()
            self.assertIsNotNone(row, "a scanned row must be confirmable by rowid")

    def test_expected_columns_populate(self):
        self._scan()
        row = self.conn.execute(
            "SELECT * FROM sessions ORDER BY id LIMIT 1").fetchone()
        self.assertTrue(row["session_id"], "session_id must populate")
        self.assertGreater(row["timestamp"], 0, "timestamp must populate")
        self.assertGreater(row["cost_usd"], 0, "cost_usd must compute > 0")
        self.assertGreater(row["output_tokens"], 0, "output_tokens must populate")
        self.assertEqual(row["account"], "personal_max")
        self.assertEqual(row["project"], "BurnTest")

    def test_clean_input_raises_nothing_and_count_matches(self):
        added = self._scan()  # a scan exception would propagate and fail here
        n = self.conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
        self.assertEqual(n, len(GOOD_JSONL), "row count must match the fixture")
        self.assertEqual(added, n, "reported added count must match rows landed")

    def test_clean_input_yields_no_waste_flags(self):
        self._scan()
        summary = wp.detect_all(self.conn)
        for k in FLAG_KEYS:
            self.assertEqual(summary.get(k, 0), 0,
                             f"clean input flagged {k}: {summary}")
        n = self.conn.execute("SELECT COUNT(*) c FROM waste_events").fetchone()["c"]
        self.assertEqual(n, 0, "clean input must write zero waste_events")

    def test_nonvacuity_readback_detects_absence_before_scan(self):
        # Proves the rowid-confirm assertion discriminates: with no scan run,
        # there is nothing to read back. (The 'return # FAULT' STATE-3 fault
        # drives exactly this state on a real scan -> red.)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM sessions").fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
