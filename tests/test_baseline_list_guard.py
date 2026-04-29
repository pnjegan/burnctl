"""Regression tests for baseline_scanner._scan_mcps list/dict guards.

Mac smoke test (v4.5.3) crashed with:
    [scanner] baseline scan failed: 'list' object has no attribute 'keys'

Two failure modes covered:
  1. Top-level JSON is a list (data.get(...) raises AttributeError)
  2. mcpServers/servers value is a list (servers_map.keys() raises AttributeError)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Ensure project root on sys.path (mirrors other tests)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import baseline_scanner


class TestMcpScannerListGuard(unittest.TestCase):

    def _write_json(self, tmpdir: str, name: str, content) -> str:
        path = os.path.join(tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f)
        return path

    def test_baseline_handles_list_top_level(self):
        """A list at the top level of an MCP config must not crash _scan_mcps."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_json(tmp, "list-top.json", [{"foo": "bar"}])
            with patch.object(baseline_scanner, "MCP_CONFIG_CANDIDATES", [cfg]):
                result = baseline_scanner._scan_mcps()
        self.assertEqual(result, [])

    def test_baseline_handles_list_servers_value(self):
        """A list value for mcpServers must not crash _scan_mcps."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_json(tmp, "list-servers.json", {"mcpServers": ["a", "b"]})
            with patch.object(baseline_scanner, "MCP_CONFIG_CANDIDATES", [cfg]):
                result = baseline_scanner._scan_mcps()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
