import unittest
import sqlite3
import time
import db


class TestInsightDedup(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER,
                account TEXT,
                project TEXT,
                insight_type TEXT,
                message TEXT,
                detail_json TEXT,
                dismissed INTEGER DEFAULT 0
            )
        """)

    def _insert(self, **kw):
        cols = [
            "created_at", "account", "project", "insight_type",
            "message", "detail_json", "dismissed",
        ]
        defaults = {
            "created_at": int(time.time()),
            "account": "default",
            "project": "P",
            "insight_type": "t",
            "message": "m",
            "detail_json": "{}",
            "dismissed": 0,
        }
        defaults.update(kw)
        self.conn.execute(
            f"INSERT INTO insights ({','.join(cols)}) "
            f"VALUES ({','.join(['?'] * len(cols))})",
            [defaults[c] for c in cols],
        )

    def test_dedup_collapses_identical_message(self):
        """Two rows, same (type, project, message): one returned."""
        self._insert(created_at=100, insight_type="churn", project="P1", message="same")
        self._insert(created_at=200, insight_type="churn", project="P1", message="same")
        rows = db.get_insights(self.conn)
        self.assertEqual(len(rows), 1)

    def test_dedup_keeps_most_recent(self):
        """Surviving row has the later created_at."""
        self._insert(created_at=100, insight_type="churn", project="P1", message="same")
        self._insert(created_at=200, insight_type="churn", project="P1", message="same")
        rows = db.get_insights(self.conn)
        self.assertEqual(rows[0]["created_at"], 200)

    def test_dedup_preserves_different_messages(self):
        """window_risk snapshots with different text stay as distinct rows."""
        self._insert(created_at=100, insight_type="window_risk", project="pm", message="48%")
        self._insert(created_at=200, insight_type="window_risk", project="pm", message="39%")
        rows = db.get_insights(self.conn)
        self.assertEqual(len(rows), 2)

    def test_dedup_respects_limit(self):
        """15 distinct + 5 text-dupes, limit=10 → 10 distinct rows."""
        for i in range(15):
            self._insert(
                created_at=1000 + i, insight_type="t",
                project=f"P{i}", message=f"m{i}",
            )
        for i in range(5):
            self._insert(
                created_at=2000 + i, insight_type="t",
                project="P0", message="m0",
            )
        rows = db.get_insights(self.conn, limit=10)
        self.assertEqual(len(rows), 10)

    def test_dedup_empty_returns_empty(self):
        rows = db.get_insights(self.conn)
        self.assertEqual(rows, [])

    def test_dedup_single_row(self):
        self._insert()
        rows = db.get_insights(self.conn)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
