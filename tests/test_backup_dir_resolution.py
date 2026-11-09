"""The default backup directory must be portable, and overridable.

It used to be a hardcoded `/root/backups/<brand>`: unwritable for every
non-root user, printed on every run, and a branding leak that held
burnctl-auditor Check 3 at FAIL. These tests pin the resolution order so the
hardcoded host path cannot come back.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cli  # noqa: E402

ENV_VARS = ("BURNCTL_BACKUP_DIR", "CLAUDASH_BACKUP_DIR")


class BackupDirResolution(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_VARS}
        for k in ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_is_under_the_home_directory(self):
        got = cli._default_backup_dir()
        self.assertTrue(got.startswith(os.path.expanduser("~")),
                        f"default must live under $HOME, got {got!r}")
        self.assertTrue(got.endswith(os.path.join(".burnctl", "backups")), got)

    def test_default_is_not_a_hardcoded_root_path(self):
        got = cli._default_backup_dir()
        self.assertNotEqual(got, "/root/backups/claudash")
        self.assertNotIn("claudash", got.lower(),
                         "the default must carry no pre-rebrand branding")

    def test_default_contains_no_branding(self):
        self.assertNotIn("claudash", cli._default_backup_dir().lower())

    def test_primary_env_var_wins(self):
        os.environ["BURNCTL_BACKUP_DIR"] = "/srv/backups/burnctl"
        self.assertEqual(cli._default_backup_dir(), "/srv/backups/burnctl")

    def test_legacy_env_var_still_honoured_for_upgraders(self):
        os.environ["CLAUDASH_BACKUP_DIR"] = "/srv/legacy"
        self.assertEqual(cli._default_backup_dir(), "/srv/legacy")

    def test_primary_takes_precedence_over_legacy(self):
        os.environ["BURNCTL_BACKUP_DIR"] = "/srv/new"
        os.environ["CLAUDASH_BACKUP_DIR"] = "/srv/old"
        self.assertEqual(cli._default_backup_dir(), "/srv/new")

    def test_tilde_in_an_override_is_expanded(self):
        os.environ["BURNCTL_BACKUP_DIR"] = "~/custom-backups"
        got = cli._default_backup_dir()
        self.assertFalse(got.startswith("~"), f"tilde not expanded: {got!r}")
        self.assertEqual(got, os.path.expanduser("~/custom-backups"))


if __name__ == "__main__":
    unittest.main()
