"""burnctl loop runner — stateless worker->checker loop over the six-axis frame.

Consumes the committed criteria (V1-V6 contract tests) + docs/six-axis-checker-frame.md
to grade a worker RUN in fresh context and decide whether a claimed "done" is real.

DETECT-NOT-ENFORCE (absolute): the only brake stops THIS runner's own loop. It never
pauses, kills, or throttles a Claude Code session. No autonomous push. The human holds
goal-in (defines the GoalSpec) and accept-out (the final reproducing gate); the checker's
output FEEDS that gate — it never self-ships.

Module-path test invocation only, never `unittest discover` (B1 collision).
Stdlib only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.abspath(__file__))

# The six axes, in frame order — used to validate coverage and label output.
AXES = ("1 criteria-pass", "2 non-vacuity", "3 real-binding",
        "4 scope-compliance", "5 state+budget", "6 ledger+repro")


@dataclasses.dataclass
class GoalSpec:
    name: str
    workdir: str                 # the run's working tree (a git repo)
    scope_paths: list            # relative paths the worker MAY write
    criteria_module: str         # module-path to re-run (never discover)
    criteria_expected: int       # expected test count (a drop reads as red)
    bound_symbols: list          # e.g. ["calc.add"] — criteria must import+call these
    fault: dict                  # {"file","inject_after"(regex),"line"} non-vacuity fault
    reproduce: str               # verbatim Reproduce command (run from workdir)
    pythonpath_extra: str = ""   # extra PYTHONPATH (e.g. REPO) for real-code deps
    abort_ceiling: int = 3


# ─────────────────────────── shell helpers ───────────────────────────

def _run(cmd, cwd, extra_path=""):
    env = dict(os.environ)
    pp = os.pathsep.join(p for p in (cwd, extra_path, env.get("PYTHONPATH", "")) if p)
    env["PYTHONPATH"] = pp
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def _unittest(module, cwd, extra_path=""):
    r = _run([sys.executable, "-m", "unittest", module, "-v"], cwd, extra_path)
    out = r.stderr + r.stdout
    m = re.search(r"Ran (\d+) test", out)
    return r.returncode, (int(m.group(1)) if m else -1), out


def _axis(name, passed, signal, evidence):
    return {"axis": name, "pass": bool(passed), "signal": signal, "evidence": evidence}


def _banned_patterns():
    """The X-surface guard reuses the REAL G5 gate's compiled patterns (single
    source of truth) rather than duplicating credential literals in this file —
    a worker must never carry or drift its own copy of the publish gate."""
    tools = os.path.join(REPO, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_banned_strings as gate
    return gate.BANNED  # ((label, compiled_regex), ...)


# ─────────────────────────── the six axis graders ───────────────────────────
# Each reads a CONCRETE signal (command output / git stat / grep) — never the
# worker's say-so. If an axis cannot be graded from a signal, it returns FAIL with
# evidence "ungradable" (the runner never passes on trust).

def grade_axis1_criteria(goal):
    rc, n, _out = _unittest(goal.criteria_module, goal.workdir, goal.pythonpath_extra)
    ok = (rc == 0 and n == goal.criteria_expected)
    return _axis(AXES[0], ok, f"python -m unittest {goal.criteria_module}",
                 f"rc={rc} ran={n} expected={goal.criteria_expected}")


def grade_axis2_nonvacuity(goal):
    """Fault the bound file IN A SCRATCH COPY and require the criteria to go RED.
    Never mutates the real tree. A criterion that stays green under its own fault
    is vacuous."""
    scratch = tempfile.mkdtemp(prefix="ax2-")
    try:
        target = goal.fault["file"]
        # copy the fault target + the criteria test into scratch
        for rel in {target, _module_to_path(goal.criteria_module)}:
            src = os.path.join(goal.workdir, rel)
            if not os.path.exists(src):
                return _axis(AXES[1], False, "scratch fault", f"ungradable: missing {rel}")
            dst = os.path.join(scratch, rel)
            os.makedirs(os.path.dirname(dst) or scratch, exist_ok=True)
            shutil.copy(src, dst)
        # inject the fault
        fp = os.path.join(scratch, target)
        s = Path(fp).read_text()
        m = re.search(goal.fault["inject_after"], s)
        if not m:
            return _axis(AXES[1], False, "scratch fault",
                         f"ungradable: inject_after not found in {target}")
        s = s[:m.end()] + goal.fault["line"] + "\n" + s[m.end():]
        Path(fp).write_text(s)
        # the criteria must now FAIL
        rc, _n, _out = _unittest(goal.criteria_module, scratch, goal.pythonpath_extra)
        # and the real tree must be untouched
        clean = Path(os.path.join(goal.workdir, target)).read_text() != s
        ok = (rc != 0 and clean)
        return _axis(AXES[1], ok, f"inject '{goal.fault['line'].strip()}' into {target} (scratch)",
                     f"faulted rc={rc} (red expected nonzero); real-tree-untouched={clean}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def grade_axis3_binding(goal):
    """The criteria must import+call the real bound symbols, not reimplement them."""
    path = os.path.join(goal.workdir, _module_to_path(goal.criteria_module))
    src = Path(path).read_text()
    problems = []
    for sym in goal.bound_symbols:
        mod, _, attr = sym.partition(".")
        imported = bool(re.search(rf"\bimport {mod}\b", src) or
                        re.search(rf"\bfrom {mod} import\b", src))
        called = bool(re.search(rf"\b{mod}\.{attr}\s*\(", src) or
                      re.search(rf"\bfrom {mod} import [^\n]*\b{attr}\b", src))
        reimpl = bool(re.search(rf"^\s*def {attr}\s*\(", src, re.M))
        if not imported:
            problems.append(f"{sym}: not imported")
        if not called:
            problems.append(f"{sym}: not called")
        if reimpl:
            problems.append(f"{sym}: REIMPLEMENTED in test (def {attr})")
    return _axis(AXES[2], not problems, "grep import/call/no-reimpl of bound_symbols",
                 "; ".join(problems) if problems else f"binds real {goal.bound_symbols}")


def grade_axis4_scope(goal, sha):
    r = _run(["git", "show", "--stat", "--name-only", "--format=", sha], goal.workdir)
    changed = [ln.strip() for ln in (r.stderr + r.stdout).splitlines() if ln.strip()]
    out_of_scope = [f for f in changed if f not in goal.scope_paths]
    pats = _banned_patterns()
    banned_hits = []
    for f in changed:
        p = os.path.join(goal.workdir, f)
        if os.path.exists(p):
            body = Path(p).read_text(errors="replace")
            banned_hits += [label for label, pat in pats if pat.search(body)]
    ok = (not out_of_scope and not banned_hits)
    ev = []
    if out_of_scope:
        ev.append(f"out-of-scope writes: {out_of_scope}")
    if banned_hits:
        ev.append(f"banned strings: {banned_hits}")
    return _axis(AXES[3], ok, f"git show --stat {sha[:8]} vs scope + banned-scan",
                 "; ".join(ev) if ev else f"changed {changed} all in scope, no banned/X")


def grade_axis5_discipline(goal, sha, worker_log, iterations, pushed):
    states = [s for s, _ in worker_log]
    seq_ok = states[:3] == ["STATE1", "STATE2", "STATE3"]
    # one fix per commit: exactly one non-initial commit reachable from sha
    r = _run(["git", "rev-list", "--count", "HEAD"], goal.workdir)
    n_commits = int((r.stdout or "0").strip() or 0)
    one_fix = (n_commits == 2)  # initial empty + the run's single commit
    no_push = (pushed is False)
    within = (iterations <= goal.abort_ceiling)
    ok = seq_ok and one_fix and no_push and within
    return _axis(AXES[4], ok, "STATE-seq + commit-count + no-push + iters<=ceiling",
                 f"seq={states[:3]} commits={n_commits} push={pushed} iters={iterations}/{goal.abort_ceiling}")


def grade_axis6_repro(goal):
    parts = goal.reproduce.replace("$WORKDIR", goal.workdir)
    r = _run(["bash", "-lc", parts], goal.workdir, goal.pythonpath_extra)
    out = r.stderr + r.stdout
    ok = (r.returncode == 0 and "OK" in out)
    return _axis(AXES[5], ok, f"reproduce: {goal.reproduce}",
                 f"rc={r.returncode} reproduced={'OK' in out}")


def check_run(goal, sha, worker_log, iterations, pushed):
    """The STATELESS checker. Sees only the committed tree + ledger inputs."""
    return [
        grade_axis1_criteria(goal),
        grade_axis2_nonvacuity(goal),
        grade_axis3_binding(goal),
        grade_axis4_scope(goal, sha),
        grade_axis5_discipline(goal, sha, worker_log, iterations, pushed),
        grade_axis6_repro(goal),
    ]


def _module_to_path(module):
    return module.replace(".", os.sep) + ".py"


# ─────────────────────────── worker (STATE 1->2->3) ───────────────────────────

def run_worker(goal, artifacts_fn):
    """STATE 1 read-only -> STATE 2 dry-run -> STATE 3 write+commit+assert+rollback."""
    log = [("STATE1", "read-only discovery (no writes)")]
    artifacts = artifacts_fn()                        # {relpath: content}
    log.append(("STATE2", f"dry-run diff: {sorted(artifacts)}"))
    for rel, content in artifacts.items():
        p = Path(goal.workdir) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _run(["git", "add", "-A"], goal.workdir)
    _run(["git", "commit", "-q", "-m", f"feat: {goal.name}"], goal.workdir)
    sha = _run(["git", "rev-parse", "HEAD"], goal.workdir).stdout.strip()
    # post-write assert: criteria must pass, else auto-rollback
    rc, _n, _out = _unittest(goal.criteria_module, goal.workdir, goal.pythonpath_extra)
    if rc != 0:
        _run(["git", "reset", "--hard", "HEAD~1"], goal.workdir)
        log.append(("STATE3", "post-write assert RED -> auto-rollback"))
        return {"ok": False, "log": log, "sha": None}
    log.append(("STATE3", f"committed {sha[:8]} + post-write assert green"))
    return {"ok": True, "log": log, "sha": sha}


# ─────────────────────────── loop orchestrator + brake ───────────────────────────

def run_loop(goal, artifacts_fn):
    last = None
    for it in range(1, goal.abort_ceiling + 1):
        w = run_worker(goal, artifacts_fn)
        if not w["ok"]:
            last = {"iteration": it, "worker": w, "axes": None}
            continue
        axes = check_run(goal, w["sha"], w["log"], it, pushed=False)
        last = {"iteration": it, "worker": w, "axes": axes}
        if all(a["pass"] for a in axes):
            return _ledger(goal, last, green=True, halted=False)
    # BRAKE: ceiling hit -> stop THIS runner's loop (never CC); no ship.
    return _ledger(goal, last, green=False, halted=True)


def _ledger(goal, last, green, halted):
    axes = last.get("axes") or []
    return {
        "goal": goal.name,
        "iterations": last["iteration"],
        "abort_ceiling": goal.abort_ceiling,
        "halted_by_brake": halted,
        "worker_states": [s for s, _ in last["worker"]["log"]],
        "axes": axes,
        "overall_green": green,
        "reproduce_checklist": [a["signal"] for a in axes] + [goal.reproduce],
        "accept_out": "HUMAN-GATED — checker output feeds the human accept gate; no self-ship",
    }


# ─────────────────────────── synthetic SAFE goal (dry-run target) ───────────────

def _new_repo():
    wd = tempfile.mkdtemp(prefix="loop-run-")
    _run(["git", "init", "-q"], wd)
    _run(["git", "config", "user.email", "runner@local"], wd)
    _run(["git", "config", "user.name", "loop-runner"], wd)
    # Ignore bytecode so it never pollutes the scope/commit-count signals when
    # the worker's `git add -A` runs after unittest has written __pycache__.
    (Path(wd) / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    _run(["git", "add", ".gitignore"], wd)
    _run(["git", "commit", "-q", "-m", "init"], wd)
    return wd


_CALC = "def add(a, b):\n    return a + b\n"
_GOOD_TEST = (
    "import unittest\n"
    "import calc\n\n"
    "class TestCalc(unittest.TestCase):\n"
    "    def test_two_plus_two(self):\n"
    "        self.assertEqual(calc.add(2, 2), 4)\n"
    "    def test_ten_plus_five(self):\n"
    "        self.assertEqual(calc.add(10, 5), 15)\n\n"
    "if __name__ == '__main__':\n"
    "    unittest.main()\n"
)


def synthetic_goal(workdir):
    return GoalSpec(
        name="synthetic-calc-criterion",
        workdir=workdir,
        scope_paths=["calc.py", "test_calc_contract.py"],
        criteria_module="test_calc_contract",
        criteria_expected=2,
        bound_symbols=["calc.add"],
        fault={"file": "calc.py", "inject_after": r"def add\([^)]*\):\n",
               "line": "    return 0  # FAULT"},
        reproduce="PYTHONPATH=$WORKDIR python3 -m unittest test_calc_contract -v",
    )


# Worker artifact factories: clean + one defect per honesty axis.
def artifacts_clean():
    return {"calc.py": _CALC, "test_calc_contract.py": _GOOD_TEST}


def artifacts_defect_reimpl():
    # Axis 3: the test reimplements add() instead of importing calc.
    t = ("import unittest\n\n"
         "def add(a, b):\n    return a + b\n\n"
         "class TestCalc(unittest.TestCase):\n"
         "    def test_two_plus_two(self):\n"
         "        self.assertEqual(add(2, 2), 4)\n"
         "    def test_ten_plus_five(self):\n"
         "        self.assertEqual(add(10, 5), 15)\n")
    return {"calc.py": _CALC, "test_calc_contract.py": t}


def artifacts_defect_vacuous():
    # Axis 2: the test calls calc.add but asserts nothing the fault can break.
    t = ("import unittest\n"
         "import calc\n\n"
         "class TestCalc(unittest.TestCase):\n"
         "    def test_two_plus_two(self):\n"
         "        calc.add(2, 2)  # no assertion -> fault cannot make this red\n"
         "    def test_ten_plus_five(self):\n"
         "        calc.add(10, 5)\n")
    return {"calc.py": _CALC, "test_calc_contract.py": t}


def artifacts_defect_out_of_scope():
    # Axis 4: writes a file outside the declared scope.
    a = artifacts_clean()
    a["secret_extra.py"] = "X = 1\n"
    return a


# ─────────────────────────── CLI ───────────────────────────

def _print_ledger(led):
    print(json.dumps(led, indent=2))
    print("\nAXES:")
    for a in led["axes"]:
        print(f"  [{'PASS' if a['pass'] else 'RED '}] {a['axis']:<18} {a['evidence']}")
    print(f"\noverall_green={led['overall_green']} halted_by_brake={led['halted_by_brake']}"
          f" iterations={led['iterations']}/{led['abort_ceiling']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="green run on the synthetic goal")
    ap.add_argument("--demo-defect", choices=["reimpl", "vacuous", "out_of_scope"],
                    help="inject a defect; checker must RED on the matching axis")
    ap.add_argument("--grade-real", action="store_true",
                    help="read-only: re-run real V1-V6 criteria via module-path (Axis 1)")
    args = ap.parse_args(argv)

    if args.grade_real:
        print("Stateless checker — Axis 1 (criteria-pass) re-run of real V1-V6 (read-only):")
        for module, expected in (("tests.test_cost_anomaly_contract", 8),
                                  ("tests.test_waste_events_contract", 8),
                                  ("tests.test_core_clean_scan_contract", 5)):
            rc, n, _ = _unittest(module, REPO)
            print(f"  [{'PASS' if rc == 0 and n == expected else 'RED '}] {module}: "
                  f"rc={rc} ran={n}/{expected}")
        return 0

    wd = _new_repo()
    try:
        goal = synthetic_goal(wd)
        if args.demo_defect:
            fn = {"reimpl": artifacts_defect_reimpl,
                  "vacuous": artifacts_defect_vacuous,
                  "out_of_scope": artifacts_defect_out_of_scope}[args.demo_defect]
            led = run_loop(goal, fn)
        else:
            led = run_loop(goal, artifacts_clean)
        _print_ledger(led)
        return 0 if led["overall_green"] or args.demo_defect else 1
    finally:
        shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
