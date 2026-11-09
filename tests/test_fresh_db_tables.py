"""Every table a shipped module queries must exist in a freshly-created DB.

This closes a bug class, not one bug. `tests/test_fresh_env_commands.py` runs
every CLI command in a fresh *environment* but against the *existing* database,
so a command that queries a table which `db.init_db()` does not create passes
here and crashes for a new user. That is how `burnctl realstory` shipped an
unguarded `SELECT ... FROM compliance_events` while the maintainer's DB had held
the table for months.

Monkey-patches db.DB_PATH to a tempfile-backed DB. Stdlib only.
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tables created on demand by a module rather than by init_db(). Each entry
# needs a reason: a bare name here silently re-opens the hole this file closes.
CREATED_AT_RUNTIME = {
    # fix_measurement.py builds this itself on first use, via an f-string on
    # its _TABLE constant, and guards with CREATE TABLE IF NOT EXISTS.
    "burnctl_fix_measurements",
}

# Not tables: SQL keywords the regex can land on (`ON CONFLICT ... DO UPDATE SET`
# captures "SET"), sqlite internals, and pragma functions used as table sources.
NOT_TABLES = {
    "set", "select", "values", "where", "sqlite_master", "sqlite_sequence",
}


def _shipped_modules():
    """Root-level .py files that package.json actually publishes."""
    files = json.load(open(os.path.join(REPO, "package.json")))["files"]
    return sorted(f for f in files if f.endswith(".py"))


def _tables_referenced(src):
    """Table names appearing after FROM / JOIN / INTO / UPDATE in SQL strings."""
    found = set()
    for m in re.finditer(r"\b(?:FROM|JOIN|INSERT\s+INTO|INTO|UPDATE)\s+([A-Za-z_]\w*)", src):
        found.add(m.group(1))
    # Drop common-table-expression names. A WITH chain names its second and
    # later CTEs after a comma, not after WITH -- insights.py builds one as
    # concatenated string literals ("), project_avg AS ("), so matching only
    # `WITH <name> AS (` leaves every later CTE looking like a missing table.
    for m in re.finditer(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", src):
        found.discard(m.group(1))
    return {t for t in found
            if t.lower() not in NOT_TABLES
            and not t.lower().startswith("pragma")}


class FreshDbTables(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)  # let init_db create it fresh
        self._orig = db.DB_PATH
        db.DB_PATH = self.db_path
        db.init_db()
        self.conn = sqlite3.connect(self.db_path)
        self.tables = {
            r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self._orig
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_compliance_events_exists_on_fresh_install(self):
        """burnctl realstory queries it unguarded at cli.py:1355."""
        self.assertIn(
            "compliance_events", self.tables,
            "init_db() does not create compliance_events, so `burnctl realstory` "
            "raises OperationalError: no such table on any fresh install",
        )

    def test_realstory_compliance_query_runs_on_fresh_install(self):
        """The exact query cli.py runs, against a fresh DB."""
        try:
            self.conn.execute(
                "SELECT pattern_id, status, COUNT(*) AS n "
                "FROM compliance_events WHERE project=? "
                "GROUP BY pattern_id, status ORDER BY pattern_id, status",
                ("any-project",),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            self.fail(f"realstory's compliance query fails on a fresh DB: {exc}")

    def test_every_table_queried_by_shipped_code_exists(self):
        """Class-level guard: no shipped module may query a table init_db omits."""
        missing = {}
        for rel in _shipped_modules():
            path = os.path.join(REPO, rel)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                refs = _tables_referenced(fh.read())
            gone = sorted(refs - self.tables - CREATED_AT_RUNTIME)
            if gone:
                missing[rel] = gone
        self.assertEqual(
            missing, {},
            "shipped modules query tables that a fresh init_db() does not create; "
            "either add them to db.py or, if a module creates one itself, add it to "
            f"CREATED_AT_RUNTIME with a reason: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
