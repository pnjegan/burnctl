"""Tests for the end-of-scan summary output in scanner._scan_all_locked.

Verifies:
  - Clean scan (no oversized content) prints exactly one summary line.
  - When _oversized_files is non-empty, a second summary line fires
    with the distinct file count.
  - When _oversized_files is empty, the second line stays silent.

Captures real stderr via io.StringIO + sys.stderr swap (stdlib only).
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import db  # noqa: E402
import scanner  # noqa: E402


def _write_jsonl(path, lines):
    """Write a list of dicts as newline-delimited JSON."""
    with open(path, "w", encoding="utf-8") as f:
        for item in lines:
            if isinstance(item, str):
                f.write(item)
                if not item.endswith("\n"):
                    f.write("\n")
            else:
                f.write(json.dumps(item) + "\n")


class ScanSummaryTests(unittest.TestCase):

    def setUp(self):
        # Isolate every run in its own tmpdir so parallel test invocations
        # never collide on db.DB_PATH or the data_paths folder.
        self.tmpdir = tempfile.mkdtemp(prefix="burnctl-scansummary-")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.data_dir = os.path.join(self.tmpdir, "claude_data")
        os.makedirs(self.data_dir)

        # Monkey-patch db.DB_PATH so init_db + get_conn use our temp DB.
        self._orig_db_path = db.DB_PATH
        db.DB_PATH = self.db_path
        db.init_db()

        # Point the seeded account's data_paths at our empty test dir so
        # _scan_all_locked walks it and nothing else on the host.
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE accounts SET data_paths = ?",
            (json.dumps([self.data_dir]),),
        )
        conn.commit()
        conn.close()

        # Clear the oversized-file set. _scan_all_locked resets it at its
        # top too — this guards against cross-test carryover if that
        # behavior ever changes.
        scanner._oversized_files.clear()

    def tearDown(self):
        db.DB_PATH = self._orig_db_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        scanner._oversized_files.clear()

    def _run_and_capture_stderr(self):
        """Execute _scan_all_locked with stderr redirected to a StringIO.
        Returns the captured text."""
        buf = io.StringIO()
        saved = sys.stderr
        sys.stderr = buf
        try:
            scanner._scan_all_locked()
        finally:
            sys.stderr = saved
        return buf.getvalue()

    def test_clean_scan_shows_single_summary_line(self):
        # Empty data dir → no files walked → zero new rows.
        out = self._run_and_capture_stderr()
        self.assertIn("[scanner] Scanned 0 files, 0 new rows added", out)
        # No oversized summary line.
        self.assertNotIn("Skipped", out)

    def test_oversized_summary_fires_when_files_nonempty(self):
        # Write one JSONL with one normal line + one 1.4 MB line.
        # The same physical file is read by multiple scan passes, so we
        # assert on distinct-file count, not per-line count.
        fixture = os.path.join(self.data_dir, "chat.jsonl")
        oversized_blob = "x" * 1_400_000
        _write_jsonl(
            fixture,
            [
                {"type": "user", "message": {"content": "hi"}},
                '{"type":"user","message":{"content":"%s"}}' % oversized_blob,
            ],
        )
        out = self._run_and_capture_stderr()
        # First summary line always present.
        self.assertIn("[scanner] Scanned", out)
        self.assertIn("new rows added", out)
        # Second line must report exactly one Claude Code file.
        self.assertIn(
            "[scanner] Skipped oversized content in 1 Claude Code file(s)",
            out,
        )
        self.assertIn("run `burnctl doctor` for details", out)

    def test_oversized_summary_silent_when_zero(self):
        # JSONL with only normal-sized lines → no guard trips.
        fixture = os.path.join(self.data_dir, "chat.jsonl")
        _write_jsonl(
            fixture,
            [
                {"type": "user", "message": {"content": "hi"}},
                {"type": "assistant", "message": {"content": "ok"}},
            ],
        )
        out = self._run_and_capture_stderr()
        self.assertIn("[scanner] Scanned", out)
        self.assertNotIn("Skipped", out)
        self.assertNotIn("oversized", out)

    def test_files_walked_counted_even_when_no_rows_added(self):
        # _parse_line rejects rows where both input_tokens and
        # output_tokens are zero (scanner.py:175-176), so this JSONL
        # is walked but contributes zero DB rows. The summary must
        # still report "Scanned 1 files" — that's the whole point of
        # switching from files_scanned (rows-inserted gate) to
        # files_walked (unconditional .jsonl visit).
        fixture = os.path.join(self.data_dir, "empty_usage.jsonl")
        _write_jsonl(
            fixture,
            [
                {
                    "sessionId": "sess-1",
                    "timestamp": "2026-04-23T10:00:00Z",
                    "type": "assistant",
                    "message": {
                        "model": "claude-sonnet",
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
                {
                    "sessionId": "sess-1",
                    "timestamp": "2026-04-23T10:01:00Z",
                    "type": "assistant",
                    "message": {
                        "model": "claude-sonnet",
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            ],
        )
        out = self._run_and_capture_stderr()
        self.assertIn("[scanner] Scanned 1 files, 0 new rows added", out)


if __name__ == "__main__":
    unittest.main()
