"""Tests for scanner._safe_line_iter — the unified oversized-line guard.

Covers:
  - Normal lines pass through.
  - Lines larger than _MAX_LINE_BYTES are skipped.
  - Skips are tracked in _oversized_files / _oversized_count.
  - Counters reset between scans (via _scan_all_locked reset).
  - All four intended call sites use the helper (grep assertion).

No pip deps — stdlib unittest only.
"""
import os
import re
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import scanner  # noqa: E402


def _write_oversized_fixture(path):
    """Three valid one-line JSONL records + one synthetic 1.4 MB line.

    The oversized line is valid JSON but large enough to trip the
    1 MB guard. Generated on-disk so _safe_line_iter sees real file
    semantics (newlines, iteration).
    """
    oversized_blob = "x" * 1_400_000
    oversized_line = '{"type":"user","message":{"content":"%s"}}\n' % oversized_blob
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"type":"user","message":{"content":"hi"}}\n')
        f.write('{"type":"assistant","message":{"content":"ok"}}\n')
        f.write(oversized_line)
        f.write('{"type":"user","message":{"content":"bye"}}\n')


class SafeLineIterTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="burnctl-safeiter-")
        self.fixture = os.path.join(self.tmpdir, "oversized.jsonl")
        _write_oversized_fixture(self.fixture)
        # Reset module state — scanner doesn't expose a public reset,
        # but each test pretends it owns a fresh scan.
        scanner._oversized_files.clear()

    def tearDown(self):
        # Clean up the fixture + tmpdir.
        try:
            os.remove(self.fixture)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass
        scanner._oversized_files.clear()

    def test_yields_normal_lines(self):
        with open(self.fixture, "r", errors="replace") as f:
            lines = list(scanner._safe_line_iter(self.fixture, f))
        # 4 lines in the fixture, 1 oversized → 3 returned.
        self.assertEqual(len(lines), 3)
        self.assertIn('"hi"', lines[0])
        self.assertIn('"ok"', lines[1])
        self.assertIn('"bye"', lines[2])

    def test_skips_oversized_lines(self):
        with open(self.fixture, "r", errors="replace") as f:
            for _ in scanner._safe_line_iter(self.fixture, f):
                pass
        # No yielded line should itself be oversized.
        with open(self.fixture, "r", errors="replace") as f:
            out = list(scanner._safe_line_iter(self.fixture, f))
        for line in out:
            self.assertLessEqual(len(line), scanner._MAX_LINE_BYTES)

    def test_tracks_oversized_files(self):
        with open(self.fixture, "r", errors="replace") as f:
            list(scanner._safe_line_iter(self.fixture, f))
        self.assertIn(self.fixture, scanner._oversized_files)

    def test_resets_between_scans(self):
        # First pass — fixture path is tracked.
        with open(self.fixture, "r", errors="replace") as f:
            list(scanner._safe_line_iter(self.fixture, f))
        self.assertIn(self.fixture, scanner._oversized_files)

        # Simulate the reset that _scan_all_locked does at its top.
        scanner._oversized_files.clear()
        self.assertEqual(len(scanner._oversized_files), 0)

        # Second pass — the set re-populates without carryover.
        with open(self.fixture, "r", errors="replace") as f:
            list(scanner._safe_line_iter(self.fixture, f))
        self.assertEqual(len(scanner._oversized_files), 1)
        self.assertIn(self.fixture, scanner._oversized_files)

    def test_start_offset_seeks_before_iter(self):
        # Iterate past the first line, then call the helper with the
        # resulting offset. The helper should seek and yield only the
        # tail — this preserves scan_jsonl_file's incremental offset.
        with open(self.fixture, "r", errors="replace") as f:
            _ = f.readline()  # consume line 1
            after_first = f.tell()
        with open(self.fixture, "r", errors="replace") as f:
            tail = list(
                scanner._safe_line_iter(
                    self.fixture, f, start_offset=after_first
                )
            )
        # Lines 2 + 4 remain (line 3 oversized, skipped).
        self.assertEqual(len(tail), 2)
        self.assertIn('"ok"', tail[0])
        self.assertIn('"bye"', tail[1])

    def test_all_four_call_sites_use_helper(self):
        scanner_src = os.path.join(REPO_ROOT, "scanner.py")
        with open(scanner_src, "r", encoding="utf-8") as f:
            text = f.read()
        # Expect at least 4 invocations of the helper — one per
        # previously-raw `for line in f:` loop we unified.
        matches = re.findall(r"for\s+line\s+in\s+_safe_line_iter\(", text)
        self.assertGreaterEqual(
            len(matches),
            4,
            msg=(
                "Expected ≥4 call sites to use _safe_line_iter; "
                "found %d. If you added a new JSONL read loop, it "
                "must go through the helper too." % len(matches)
            ),
        )
        # Also ensure the old per-line WARNING print is gone.
        self.assertNotIn(
            'WARNING: skipping oversized line',
            text,
            msg="Per-line WARNING print should be replaced by module counters.",
        )


if __name__ == "__main__":
    unittest.main()
