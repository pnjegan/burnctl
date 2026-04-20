"""burnctl daily QA — automated functional regression suite.

Runs every burnctl command from a fresh /tmp/ directory and every dashboard
HTTP endpoint. Scores each as WOW / OK / DOD. Writes a timestamped report
plus a rolling `latest.md`, and detects regressions vs the previous run.

Designed to be run as a cron job or invoked by `burnctl qa`. Exits 0 if all
WOW, 1 if any OK, 2 if any DOD — so cron monitors can page on DOD.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


QA_DIR = Path.home() / "projects" / "burnctl" / "qa-reports"
DASHBOARD = "http://localhost:8080"
NPX_TIMEOUT = 90  # seconds per command — npx cold-start can be slow
CURL_TIMEOUT = 10

# Claude Code version ranges (same as version_check.py)
BAD_VERSION_RE = re.compile(r"^2\.1\.(6[9]|[78][0-9])$")

WOW = "WOW"
OK = "OK"
DOD = "DOD"


# ─────────────────────────────────────────────────────────
# Runners
# ─────────────────────────────────────────────────────────

def run_npx(cmd, cwd):
    """Run `npx burnctl@latest <cmd>` in cwd. Returns (exit, out)."""
    try:
        proc = subprocess.run(
            ["npx", "burnctl@latest"] + cmd.split(),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=NPX_TIMEOUT,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, f"[timeout after {NPX_TIMEOUT}s]"
    except Exception as e:
        return -2, f"[runner error: {e}]"


def run_curl(path, raw=False):
    """Fetch DASHBOARD + path. Returns (status_code, body)."""
    url = DASHBOARD + path
    try:
        with urllib.request.urlopen(url, timeout=CURL_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except urllib.error.URLError as e:
        return -1, f"[url error: {e.reason}]"
    except Exception as e:
        return -2, f"[runner error: {e}]"


# ─────────────────────────────────────────────────────────
# Check helpers
# ─────────────────────────────────────────────────────────

def has_traceback(output):
    return "Traceback" in output or "ModuleNotFoundError" in output or "SyntaxError:" in output


def has_maintainer_leak(output):
    # fresh /tmp run MUST NOT show real session data
    return any(s in output for s in (
        "$227.99",  # known maintainer session cost
        "~/projects/burnctl",
        "/root/projects/burnctl",
    ))


def has_claudash_in_user_output(output):
    # "Claudash" in user-visible output = branding leak
    return bool(re.search(r"\bClaudash\b", output))


# ─────────────────────────────────────────────────────────
# Per-command scorers
# ─────────────────────────────────────────────────────────

def score_audit(exit_code, output):
    if exit_code != 0 or has_traceback(output):
        return DOD, "crash or non-zero exit"
    if "Sessions analyzed" in output or "sessions scanned" in output.lower():
        m = re.search(r"Sessions analyzed:\s*(\d+)", output)
        n = m.group(1) if m else "?"
        return WOW, f"{n} sessions analyzed"
    return OK, "ran but no 'Sessions analyzed' marker"


def score_resume_audit(exit_code, output):
    if exit_code != 0 or has_traceback(output):
        return DOD, "crash or non-zero exit"
    m = re.search(r"(\d+)\s+session\(s\) with cache-bust signals \(of (\d+) analyzed\)", output)
    if not m:
        # valid when JSONL sample is tiny — still count as OK
        return OK, "no flag-count line found"
    flagged, total = int(m.group(1)), int(m.group(2))
    if total == 0:
        return OK, f"0 sessions analyzed"
    ratio = flagged / total
    if ratio > 0.40:
        return DOD, f"{flagged}/{total} flagged ({ratio*100:.1f}%) — noise above 40%"
    if ratio > 0.20:
        return OK, f"{flagged}/{total} flagged ({ratio*100:.1f}%)"
    return WOW, f"{flagged}/{total} flagged ({ratio*100:.1f}%)"


def score_peak_hours(exit_code, output):
    if exit_code != 0 or has_traceback(output):
        return DOD, "crash or non-zero exit"
    if "Peak" in output or "Off-peak" in output:
        m = re.search(r"(Peak|Off-peak)\s+(\d\d:\d\d\s+UTC)", output)
        return WOW, m.group(0) if m else "peak-state reported"
    return OK, "no Peak/Off-peak marker"


def score_version_check(exit_code, output):
    if exit_code != 0 or has_traceback(output):
        return DOD, "crash or non-zero exit"
    m = re.search(r"Claude Code version:\s*([\d.]+)", output)
    if not m:
        return OK, "no Claude Code version line"
    v = m.group(1)
    if BAD_VERSION_RE.match(v):
        # on bad version, interceptor nudge is expected — still WOW if present
        return WOW, f"v{v} (bad range)"
    # clean version — must NOT show "interceptor NOT installed"
    if "interceptor NOT installed" in output:
        return DOD, f"v{v} clean but still shows interceptor warning"
    return WOW, f"v{v} clean"


def score_no_db_command(exit_code, output, name):
    """For commands that should say "No burnctl database found" from /tmp."""
    if has_traceback(output):
        return DOD, "traceback"
    if has_maintainer_leak(output):
        return DOD, "maintainer DB leak — shows real data from /tmp"
    if has_claudash_in_user_output(output):
        return DOD, "contains 'Claudash' in user-visible output"
    if "No burnctl database found" in output or "no burnctl DB found" in output:
        return WOW, "clean 'no database' message"
    if exit_code != 0:
        return DOD, f"exit {exit_code}"
    # It ran with no error — could be showing fresh-install audit output
    return OK, "ran without explicit 'no DB' marker"


def score_work_timeline(exit_code, output):
    """Strict: work-timeline from /tmp MUST say no DB (BUG-1 regression guard)."""
    if has_traceback(output):
        return DOD, "traceback"
    if has_maintainer_leak(output):
        return DOD, "BUG-1 regression — maintainer DB leak"
    if has_claudash_in_user_output(output):
        return DOD, "'Claudash' in user-visible output"
    if "no burnctl DB found" in output or "No burnctl database found" in output:
        return WOW, "no-DB message correct"
    if "SURFACE PATTERN" in output or "Work Intelligence" in output:
        return DOD, "showing real timeline from fresh /tmp"
    return OK, "ran without expected marker"


def score_api_health(status, body):
    if status != 200:
        return DOD, f"HTTP {status}"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return DOD, "non-JSON response"
    v = data.get("version", "?")
    # compare against package.json on disk (what should be installed locally)
    try:
        pkg = json.loads((Path(__file__).resolve().parent / "package.json").read_text())
        expected = pkg["version"]
    except Exception:
        expected = None
    if expected and v != expected:
        return DOD, f"version mismatch: /api/health={v}, package.json={expected}"
    return WOW, f"v{v}"


def score_api_stats(status, body):
    if status != 200:
        return DOD, f"HTTP {status}"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return DOD, "non-JSON"
    cost = data.get("total_cost_usd", 0)
    turns = data.get("total_turns", 0)
    if cost is None or cost <= 0:
        return DOD, f"total_cost_usd={cost} (expected > 0)"
    return WOW, f"${cost:,.2f} across {turns:,} turns"


def score_api_projects(status, body):
    if status != 200:
        return DOD, f"HTTP {status}"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return DOD, "non-JSON"
    names = [p.get("name", "") for p in data] if isinstance(data, list) else []
    if "Claudash" in names:
        return DOD, "'Claudash' still in /api/projects"
    return WOW, f"{len(names)} projects, no Claudash leak"


# ─────────────────────────────────────────────────────────
# Test plan
# ─────────────────────────────────────────────────────────

TESTS = [
    # npx commands — run from fresh /tmp
    ("audit",            "npx",  "audit",                 score_audit),
    ("resume-audit",     "npx",  "resume-audit",          score_resume_audit),
    ("peak-hours",       "npx",  "peak-hours",            score_peak_hours),
    ("version-check",    "npx",  "version-check",         score_version_check),
    ("variance",         "npx",  "variance",              lambda e, o: score_no_db_command(e, o, "variance")),
    ("subagent-audit",   "npx",  "subagent-audit",        lambda e, o: score_no_db_command(e, o, "subagent-audit")),
    ("overhead-audit",   "npx",  "overhead-audit",        lambda e, o: score_no_db_command(e, o, "overhead-audit")),
    ("compact-audit",    "npx",  "compact-audit",         lambda e, o: score_no_db_command(e, o, "compact-audit")),
    ("fix-scoreboard",   "npx",  "fix-scoreboard",        lambda e, o: score_no_db_command(e, o, "fix-scoreboard")),
    ("work-timeline",    "npx",  "work-timeline",         score_work_timeline),
    ("work-timeline 7d", "npx",  "work-timeline --days 7", score_work_timeline),
    # HTTP endpoints
    ("api/health",       "curl", "/api/health",           score_api_health),
    ("api/stats",        "curl", "/api/stats",            score_api_stats),
    ("api/projects",     "curl", "/api/projects",         score_api_projects),
]


# ─────────────────────────────────────────────────────────
# Runner + reporter
# ─────────────────────────────────────────────────────────

def run_all_tests():
    """Execute every TEST, return list of result dicts."""
    qa_tmp = Path("/tmp") / f"burnctl-qa-{os.getpid()}"
    qa_tmp.mkdir(exist_ok=True)
    results = []
    for name, kind, arg, scorer in TESTS:
        t0 = time.monotonic()
        if kind == "npx":
            exit_code, output = run_npx(arg, qa_tmp)
        else:
            exit_code, output = run_curl(arg)
        elapsed = time.monotonic() - t0
        status, evidence = scorer(exit_code, output)
        results.append({
            "name": name,
            "kind": kind,
            "arg": arg,
            "status": status,
            "evidence": evidence,
            "exit_code": exit_code,
            "elapsed_sec": round(elapsed, 2),
            "output_head": output[:500],
        })
    # best-effort cleanup
    try:
        for p in qa_tmp.iterdir():
            p.unlink()
        qa_tmp.rmdir()
    except OSError:
        pass
    return results


def load_prior_results(path):
    """Parse a prior latest.md into {name: status}. Returns {} on any error."""
    if not path.exists():
        return {}
    prior = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^(\S[\S ]+?)\s{2,}(WOW|OK|DOD)\s", line)
        if m:
            prior[m.group(1).strip()] = m.group(2)
    return prior


def detect_regressions(current, prior):
    """Return list of names that regressed from WOW/OK → DOD."""
    regressions = []
    for r in current:
        prev = prior.get(r["name"])
        if prev in (WOW, OK) and r["status"] == DOD:
            regressions.append((r["name"], prev, r["status"]))
    return regressions


def format_report(results, regressions, prior_path):
    wow_count = sum(1 for r in results if r["status"] == WOW)
    ok_count = sum(1 for r in results if r["status"] == OK)
    dod_count = sum(1 for r in results if r["status"] == DOD)
    total = len(results)

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        pkg = json.loads((Path(__file__).resolve().parent / "package.json").read_text())
        version = pkg["version"]
    except Exception:
        version = "?"

    lines = []
    lines.append(f"# burnctl Daily QA — {ts}")
    lines.append("")
    lines.append(f"**Version:** v{version}   **Summary:** {wow_count}/{total} WOW · {ok_count} OK · {dod_count} DOD")
    lines.append("")
    lines.append("```")
    lines.append(f"burnctl Daily QA — {ts}")
    lines.append(f"v{version} | {wow_count}/{total} WOW | {ok_count} OK | {dod_count} DOD")
    lines.append("")
    for r in results:
        name = r["name"]
        status = r["status"]
        ev = r["evidence"]
        lines.append(f"{name:<20} {status:<4} {ev}")
    lines.append("")
    if regressions:
        lines.append("REGRESSIONS vs previous run:")
        for name, prev, now in regressions:
            lines.append(f"  [WARN] {name} was {prev}, now {now}")
    else:
        if prior_path.exists():
            lines.append("REGRESSIONS vs previous run: none")
        else:
            lines.append("REGRESSIONS vs previous run: (no prior run)")
    lines.append("```")
    lines.append("")
    lines.append(f"Full elapsed: {sum(r['elapsed_sec'] for r in results):.1f}s")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    for r in results:
        lines.append(f"### {r['name']} — {r['status']}")
        lines.append(f"- kind: `{r['kind']}`  arg: `{r['arg']}`  exit: `{r['exit_code']}`  elapsed: {r['elapsed_sec']}s")
        lines.append(f"- evidence: {r['evidence']}")
        lines.append("")
    return "\n".join(lines)


def main():
    QA_DIR.mkdir(parents=True, exist_ok=True)
    prior_path = QA_DIR / "latest.md"
    prior = load_prior_results(prior_path)

    print("burnctl daily_qa — running 14 checks...")
    results = run_all_tests()
    regressions = detect_regressions(results, prior)
    report = format_report(results, regressions, prior_path)

    # write timestamped + latest
    ts_utc = datetime.datetime.now(datetime.timezone.utc)
    stamp = ts_utc.strftime("%Y-%m-%d-%H")
    ts_path = QA_DIR / f"{stamp}.md"
    ts_path.write_text(report)
    prior_path.write_text(report)

    # print summary to stdout
    print(report)
    print(f"\nSaved: {ts_path}")
    print(f"Saved: {prior_path}")

    # exit code reflects severity (for cron monitoring)
    if any(r["status"] == DOD for r in results):
        sys.exit(2)
    if any(r["status"] == OK for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
