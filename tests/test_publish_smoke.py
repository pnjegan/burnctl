"""Fresh-environment smoke test for burnctl (docs/goals/PUBLISH-READY.md).

Runs the REAL CLI as a stranger would meet it: a temp HOME, a temp cwd, the
exact set of files the npm tarball ships (package.json ``files`` allow-list) with
**no** ``data/`` dir, no existing DB, no ``~/.burnctl``, and no pm2 daemon. It
answers one question honestly: what does ``burnctl brief`` do on first run?

HEADLINE (docs/goals/PUBLISH-READY.md STATE-3 #1): a fresh ``burnctl brief`` must
exit cleanly with a graceful "no data yet" message — not a traceback, not a
misleading zero report, not files outside its own data dir. It currently does
NOT: it tracebacks (``AttributeError: 'NoneType' ... execute`` — cmd_brief passes
get_conn()'s None straight to compute_daily_snapshots). Per the goal, an honest
red is a valid outcome: the desired behaviour is pinned as an ``expectedFailure``
(tracked as BLOCKER-1 in docs/PUBLISH-READINESS.md), and the *current* traceback
is captured as a hard-passing regression so the failure is on the record rather
than papered over. When BLOCKER-1 is fixed, the expectedFailure flips to an
unexpected success AND the regression-capture test fails — both signal "update me".

ISOLATION (STATE-3 #5): the test never touches the real DB / real ~/.burnctl /
pm2. This is proven STRUCTURALLY — the isolated subprocess's resolved DB path can
only ever be inside the temp dir — which is robust even while the maintainer's
live pm2 daemon writes the real DB concurrently (a naive before/after checksum
would race that daemon). A daemon-aware byte-identical check runs too.

Stdlib only; unittest (matches the repo's other suites). Deterministic: no
wall-clock, no network, no ambient DB in the pass/fail path.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(REPO, "data", "usage.db")


def _sha(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pm2_burnctl_running():
    """True iff a live pm2 process named 'burnctl' exists (it writes REAL_DB on
    its own timer, so a before/after checksum of REAL_DB would race it)."""
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True,
                             timeout=10)
        if out.returncode != 0:
            return False
        return any(p.get("name") == "burnctl" for p in json.loads(out.stdout or "[]"))
    except (FileNotFoundError, ValueError, subprocess.SubprocessError, OSError):
        return False


def _build_fresh_env():
    """Copy exactly the shipped files (package.json ``files``) into a temp dir —
    NO data/, NO DB — with a temp HOME. Returns (tmpdir, home, env)."""
    tmp = tempfile.mkdtemp(prefix="burnctl-smoke-")
    files = json.load(open(os.path.join(REPO, "package.json")))["files"]
    cwd = os.getcwd()
    os.chdir(REPO)          # glob the allow-list relative to the repo
    try:
        for pat in files:
            for src in glob.glob(pat):
                dst = os.path.join(tmp, src)
                os.makedirs(os.path.dirname(dst) or tmp, exist_ok=True)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
    finally:
        os.chdir(cwd)
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home,
           "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    return tmp, home, env


def _run(tmp, env, args, timeout=60):
    """Run `python3 cli.py <args>` inside the isolated env. stdin=/dev/null so no
    command that reads stdin (e.g. statusline) can block the test."""
    with open(os.devnull, "rb") as devnull:
        return subprocess.run(
            [sys.executable, "cli.py", *args],
            cwd=tmp, env=env, stdin=devnull,
            capture_output=True, text=True, timeout=timeout,
        )


class TestFreshInstallSmoke(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.home, cls.env = _build_fresh_env()
        # No data/ shipped -> a genuinely empty first-run environment.
        assert not os.path.isdir(os.path.join(cls.tmp, "data")), \
            "fixture leaked a data/ dir — not a fresh install"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- STATE-3 #5: ISOLATION — the subprocess can never reach the real DB -----
    def test_isolation_resolved_db_is_inside_tmp_not_real(self):
        probe = (
            "import db, json;"
            "print(json.dumps({'DB_PATH': db.DB_PATH,"
            " 'resolved': db.resolved_db_path()}))"
        )
        r = subprocess.run([sys.executable, "-c", probe], cwd=self.tmp,
                           env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        info = json.loads(r.stdout.strip().splitlines()[-1])
        # The package-local DB_PATH must live under the temp install, never /root.
        self.assertTrue(info["DB_PATH"].startswith(self.tmp),
                        f"DB_PATH escaped the sandbox: {info['DB_PATH']}")
        self.assertNotEqual(os.path.realpath(info["DB_PATH"]),
                            os.path.realpath(REAL_DB))
        # A fresh install resolves to NO existing DB.
        self.assertIsNone(info["resolved"],
                          f"fresh env unexpectedly resolved a DB: {info['resolved']}")

    def test_isolation_real_db_untouched(self):
        before = _sha(REAL_DB)
        _run(self.tmp, self.env, ["brief"])
        after = _sha(REAL_DB)
        if before is None:
            return  # no real DB on this machine — nothing to protect
        if before != after:
            # The maintainer's live pm2 daemon writes REAL_DB on its own timer;
            # structural isolation (test above) already proves the subprocess
            # cannot open REAL_DB, so a concurrent change is the daemon, not us.
            self.assertTrue(_pm2_burnctl_running(),
                            "REAL_DB changed with NO live daemon — the smoke test "
                            "may have touched it")
            self.skipTest("REAL_DB changed via the live pm2 daemon; structural "
                          "isolation asserted separately")
        self.assertEqual(before, after)

    def test_no_files_created_outside_data_dir(self):
        # brief crashes before creating anything; assert it wrote nothing into the
        # temp HOME (no ~/.burnctl, no stray dotfiles) — its only permitted write
        # surface is <install>/data, never HOME.
        _run(self.tmp, self.env, ["brief"])
        leaked = [p for p in glob.glob(os.path.join(self.home, "**", "*"),
                                       recursive=True) if os.path.isfile(p)]
        self.assertEqual(leaked, [],
                         f"brief created files under HOME on a fresh run: {leaked}")

    # -- STATE-3 #1: HEADLINE — current behaviour is a BLOCKER (hard record) -----
    def test_fresh_brief_current_behaviour_is_blocker_1(self):
        """CAPTURES the current BLOCKER honestly: fresh `brief` tracebacks. Kept
        green so the suite is green while the red is on the record. Fails (on
        purpose) the day BLOCKER-1 is fixed — update this + the expectedFailure."""
        r = _run(self.tmp, self.env, ["brief"])
        self.assertNotEqual(r.returncode, 0,
                            "brief no longer crashes — BLOCKER-1 may be fixed; "
                            "update test_fresh_brief_is_graceful + this test")
        self.assertIn("Traceback", r.stderr)
        self.assertIn("NoneType", r.stderr)  # get_conn() -> None reaches .execute

    # -- STATE-3 #1: HEADLINE — desired behaviour, not yet met (honest red) ------
    @unittest.expectedFailure
    def test_fresh_brief_is_graceful(self):
        """DESIRED first-run behaviour (BLOCKER-1, docs/PUBLISH-READINESS.md):
        exit 0 with a graceful no-data hint, no traceback. Currently fails ->
        expectedFailure. Flips to an unexpected success when BLOCKER-1 is fixed."""
        r = _run(self.tmp, self.env, ["brief"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        combined = (r.stdout + r.stderr).lower()
        self.assertTrue(any(s in combined for s in ("no data", "no burnctl db",
                        "run `burnctl scan`", "scan first")),
                        f"no graceful no-data hint in output: {r.stdout!r} {r.stderr!r}")


if __name__ == "__main__":
    unittest.main()
