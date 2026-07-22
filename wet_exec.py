"""Real wet executors for loop_driver — kept OUT of loop_driver.py on purpose.

loop_driver.py must contain no subprocess (its no-push/no-exec invariant is
asserted at the source level). The real command runner and git-tree probe live
here and are injected into a wet LoopDriver only at an explicit wet call site.
The contract test suite injects MOCKS instead, so it never restarts pm2 / runs
deploy.sh. Stdlib only.
"""

from __future__ import annotations

import os
import subprocess

REPO = os.path.dirname(os.path.abspath(__file__))


def real_command_runner(cmd, cwd=REPO, timeout=120):
    """Execute a remedy command; return (exit_code, combined_output).

    Used ONLY for allow-listed FRICTION remedies (initially `bash deploy.sh`,
    which is idempotent and /api/health-verified). `shell=True` because remedies
    are fixed, trusted strings from the rule table — never user input."""
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                       timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def real_tree_status(cwd=REPO):
    """Return `git status --porcelain` for the driver's repo — the dirty-tree
    preflight input. Non-empty => uncommitted changes => a wet run is refused
    (loop_runner's `git reset --hard` rollback would discard them)."""
    r = subprocess.run(["git", "status", "--porcelain"], cwd=cwd,
                       capture_output=True, text=True)
    return r.stdout
