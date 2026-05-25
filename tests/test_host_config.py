"""Tests for config.BURNCTL_HOST / BURNCTL_PORT env-var resolution.

Covers the precedence chain introduced in v4.5.8:
    BURNCTL_HOST > BURNCTL_VPS_IP (legacy) > CLAUDASH_VPS_IP (legacy) > "localhost"
and the analogous BURNCTL_PORT chain.

Stdlib unittest only (the project ships zero pip dependencies, so the
suite must run under `python3 -m unittest`; pytest is not assumed).
Each test clears all chain vars, sets only the ones under test, then
importlib.reload(config) so the module-level constants are re-evaluated
against the patched environment. os.environ is saved and restored around
every test — the unittest equivalent of pytest's monkeypatch.
"""
import importlib
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config  # noqa: E402

# Every env var that participates in either resolution chain.
_HOST_VARS = ("BURNCTL_HOST", "BURNCTL_VPS_IP", "CLAUDASH_VPS_IP")
_PORT_VARS = ("BURNCTL_PORT", "BURNCTL_VPS_PORT", "CLAUDASH_VPS_PORT")


class HostConfigTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _HOST_VARS + _PORT_VARS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(config)  # leave the module in its real-env state

    def _reload_with(self, **env):
        for name in _HOST_VARS + _PORT_VARS:
            os.environ.pop(name, None)
        for name, value in env.items():
            os.environ[name] = value
        return importlib.reload(config)

    # ── Host precedence ──

    def test_no_env_defaults_to_localhost(self):
        cfg = self._reload_with()
        self.assertEqual(cfg.BURNCTL_HOST, "localhost")

    def test_burnctl_host_wins_over_burnctl_vps_ip(self):
        cfg = self._reload_with(BURNCTL_HOST="new", BURNCTL_VPS_IP="old")
        self.assertEqual(cfg.BURNCTL_HOST, "new")

    def test_burnctl_host_wins_over_claudash_vps_ip(self):
        cfg = self._reload_with(BURNCTL_HOST="new", CLAUDASH_VPS_IP="legacy")
        self.assertEqual(cfg.BURNCTL_HOST, "new")

    def test_burnctl_vps_ip_wins_over_claudash_vps_ip(self):
        cfg = self._reload_with(BURNCTL_VPS_IP="mid", CLAUDASH_VPS_IP="legacy")
        self.assertEqual(cfg.BURNCTL_HOST, "mid")

    def test_claudash_vps_ip_used_when_only_legacy_set(self):
        cfg = self._reload_with(CLAUDASH_VPS_IP="legacy")
        self.assertEqual(cfg.BURNCTL_HOST, "legacy")

    # ── Port precedence ──

    def test_no_env_port_defaults_to_8080(self):
        cfg = self._reload_with()
        self.assertEqual(cfg.BURNCTL_PORT, 8080)

    def test_burnctl_port_wins_over_legacy(self):
        cfg = self._reload_with(BURNCTL_PORT="9000", BURNCTL_VPS_PORT="8081")
        self.assertEqual(cfg.BURNCTL_PORT, 9000)

    def test_port_is_int(self):
        cfg = self._reload_with(BURNCTL_PORT="8082")
        self.assertEqual(cfg.BURNCTL_PORT, 8082)
        self.assertIsInstance(cfg.BURNCTL_PORT, int)


if __name__ == "__main__":
    unittest.main()
