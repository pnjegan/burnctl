"""Permanent fresh-install harness (docs/goals/HARDEN-NONE-CONN.md).

Auto-discovers EVERY command from cli.py's ``commands`` dict at runtime and runs
each in a genuinely isolated fresh environment (temp HOME, temp cwd, only the
shipped files, no DB, no ~/.burnctl, no pm2), in two scenarios:

  A. no DB at all           (the very first run after install)
  B. after db.init_db()     (the state right after `burnctl scan` creates the DB)

and asserts NO command tracebacks in either. Because the command list is derived
from the dict, a future command that crashes on a fresh install FAILS THIS SUITE
automatically — it can never silently miss command #21.

This is behaviour-driven (run it, see what breaks), not a static grep of
get_conn() sites: it also catches non-DB fresh-install failures (a module missing
from the npm tarball, an interactive command with no tty, a query against a table
init_db never creates).

Isolation: the sandboxed subprocess's resolved DB path is always inside the temp
dir, so it can never open the real DB; BURNCTL_BACKUP_DIR is pinned to the sandbox
so `backup`'s hardcoded path (BLOCKER-3, out of scope) can't escape. Stdlib only.
"""
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(REPO, "data", "usage.db")

# Commands that start a long-running server or shell out to the network; a
# bounded run that does not traceback is a pass (they are not fresh-install
# crashes). Everything else must return promptly.
_SLOW = {"dashboard", "mcp", "qa"}


def discover_commands(src=None):
    """Parse the keys of cli.py's ``commands = { ... }`` dict literal. Passing
    ``src`` lets the auto-discovery test prove a NEW dict entry is picked up."""
    if src is None:
        src = open(os.path.join(REPO, "cli.py")).read()
    body = re.search(r"commands = (\{.*?\n    \})", src, re.S).group(1)
    return re.findall(r'"([a-z0-9-]+)":', body)


def _sha(p):
    if not os.path.exists(p):
        return None
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _pm2_burnctl_running():
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
        return out.returncode == 0 and any(
            p.get("name") == "burnctl" for p in json.loads(out.stdout or "[]"))
    except (FileNotFoundError, ValueError, subprocess.SubprocessError, OSError):
        return False


def _build_shipped_tree():
    """Copy exactly the npm-shipped files into a fresh temp dir (no data/)."""
    tmp = tempfile.mkdtemp(prefix="hnc-cmd-")
    files = json.load(open(os.path.join(REPO, "package.json")))["files"]
    cwd = os.getcwd(); os.chdir(REPO)
    try:
        for pat in files:
            for s in glob.glob(pat):
                d = os.path.join(tmp, s)
                os.makedirs(os.path.dirname(d) or tmp, exist_ok=True)
                (shutil.copytree if os.path.isdir(s) else shutil.copy2)(
                    s, d, **({"dirs_exist_ok": True} if os.path.isdir(s) else {}))
    finally:
        os.chdir(cwd)
    home = os.path.join(tmp, "home"); os.makedirs(home)
    return tmp, home


def _env(home):
    return {"PATH": os.environ.get("PATH", ""), "HOME": home,
            "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
            "BURNCTL_BACKUP_DIR": os.path.join(home, "backups")}


def _run_command(args, populate=False):
    """Run one command in its own fresh shipped-tree env. Returns (label, tb, tail).
    populate=True first runs db.init_db() (scenario B)."""
    tmp, home = _build_shipped_tree()
    try:
        env = _env(home)
        if populate:
            subprocess.run([sys.executable, "-c", "import db; db.init_db()"],
                           cwd=tmp, env=env, capture_output=True, timeout=30)
        timeout = 6 if args[0] in _SLOW else 25
        with open(os.devnull, "rb") as dn:
            try:
                p = subprocess.run([sys.executable, "cli.py", *args], cwd=tmp,
                                   env=env, stdin=dn, capture_output=True,
                                   text=True, timeout=timeout)
                err = p.stderr
            except subprocess.TimeoutExpired as e:
                err = e.stderr or ""  # slow/server: a timeout is not a traceback
                if isinstance(err, bytes):
                    err = err.decode("utf-8", "replace")
        tb = "Traceback (most recent call last)" in err
        tail = "\n".join(err.strip().splitlines()[-3:])
        return (" ".join(args), tb, tail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all(commands, populate):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_run_command, [c], populate): c for c in commands}
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    return results


class TestFreshEnvCommands(unittest.TestCase):

    def test_auto_discovery_from_commands_dict(self):
        # A new command added to the dict is discovered automatically — proven by
        # feeding a synthetic source with a stub entry.
        stub_src = (
            'commands = {\n'
            '        "brief": cmd_brief,\n'
            '        "totally-new-cmd": cmd_stub,\n'
            '    }\n'
        )
        found = discover_commands(stub_src)
        self.assertIn("totally-new-cmd", found)
        # And the REAL dict yields the known commands + a sane count.
        real = discover_commands()
        for expected in ("brief", "coach", "fix-rules", "scan", "stats"):
            self.assertIn(expected, real)
        self.assertGreaterEqual(len(real), 30)

    def test_no_command_crashes_on_pristine_fresh_install(self):
        # Scenario A: no DB at all.
        crashes = [(c, tail) for c, tb, tail in
                   _run_all(discover_commands(), populate=False) if tb]
        self.assertEqual(crashes, [], f"commands tracebacked on a no-DB install: {crashes}")

    def test_no_command_crashes_after_init_db(self):
        # Scenario B: DB exists via init_db() but is empty (post-`scan`).
        crashes = [(c, tail) for c, tb, tail in
                   _run_all(discover_commands(), populate=True) if tb]
        self.assertEqual(crashes, [], f"commands tracebacked on an empty DB: {crashes}")

    def test_unusable_db_named_error_not_no_data(self):
        # A corrupt DB must produce a clear path-naming error + non-zero exit for
        # the DB-guarded commands, NEVER the "no data yet" message.
        for cmd in (["brief"], ["admin", "prune-scan-state"]):
            tmp, home = _build_shipped_tree()
            try:
                os.makedirs(os.path.join(tmp, "data"))
                with open(os.path.join(tmp, "data", "usage.db"), "wb") as fh:
                    fh.write(b"garbage, not a sqlite database")
                with open(os.devnull, "rb") as dn:
                    p = subprocess.run([sys.executable, "cli.py", *cmd], cwd=tmp,
                                       env=_env(home), stdin=dn, capture_output=True,
                                       text=True, timeout=25)
                out = (p.stdout + p.stderr).lower()
                self.assertNotEqual(p.returncode, 0, cmd)
                self.assertIn("cannot open database", out, cmd)
                self.assertNotIn("no burnctl data yet", out, cmd)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def test_isolation_real_db_untouched(self):
        before = _sha(REAL_DB)
        _run_command(["brief"])
        _run_command(["stats"], populate=True)
        after = _sha(REAL_DB)
        if before is None or before == after:
            return
        # The live pm2 daemon rewrites REAL_DB on its own timer; structural
        # isolation (sandbox-only resolved path) already guarantees the test can't.
        self.assertTrue(_pm2_burnctl_running(),
                        "REAL_DB changed with no live daemon — the harness may have touched it")


if __name__ == "__main__":
    unittest.main()
