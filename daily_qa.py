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
REPO_DIR = Path(__file__).resolve().parent
DASHBOARD = "http://localhost:8080"
NPX_TIMEOUT = 90  # seconds per command — npx cold-start can be slow
CURL_TIMEOUT = 10
LOCAL_CMD_TIMEOUT = 30

# Trend table thresholds — absolute percentage-point move considered drift
TREND_DRIFT_PCT = 10.0

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


_DEFAULT_LEAK_PATTERNS = (
    "$227.99",  # known maintainer session cost
    "~/projects/burnctl",
    "/root/projects/burnctl",
)


def _load_leak_patterns():
    """Load maintainer-leak substrings from .burnctlignore next to this file.

    File format: one substring per line, lines starting with `#` ignored.
    Falls back to _DEFAULT_LEAK_PATTERNS when the file is absent, empty,
    or unreadable. Making this loadable from disk lets other users of
    burnctl add their own hostnames / project paths without forking the
    QA script.
    """
    f = REPO_DIR / ".burnctlignore"
    if not f.exists():
        return _DEFAULT_LEAK_PATTERNS
    try:
        patterns = tuple(
            line.strip()
            for line in f.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    except OSError:
        return _DEFAULT_LEAK_PATTERNS
    return patterns or _DEFAULT_LEAK_PATTERNS


def has_maintainer_leak(output):
    """True if a known maintainer substring appears in user-visible output.

    Load list is cached per-process via _load_leak_patterns() — if you
    edit .burnctlignore, re-run daily_qa (single-shot design).
    """
    patterns = _load_leak_patterns()
    return any(s in output for s in patterns)


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
    if re.search(r"peak", output, re.IGNORECASE):
        m = re.search(r"(PEAK HOURS|Peak|Off-peak)\s+(\d\d:\d\d\s+UTC)", output)
        return WOW, m.group(0) if m else "peak-state reported"
    return OK, "no peak-state marker"


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


def score_smoke(exit_code, output):
    """Generic smoke test: ran to completion, no traceback, no leaks.

    A command that fails with `unknown command` on `npx burnctl@latest` is
    pending publish (added locally but not yet on npm). Mark OK — this
    is by design to avoid a catch-22 on pre-publish gate runs.
    """
    if has_traceback(output):
        return DOD, "traceback"
    if has_maintainer_leak(output):
        return DOD, "maintainer-path leak in output"
    if "unknown command" in output:
        return OK, "pending publish — unknown in published version"
    if exit_code != 0:
        return DOD, f"exit {exit_code}"
    return WOW, "ran clean"


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

def check_browser_session_health():
    """v4.3.0 check 18 — browser session patterns (local, no npx/curl).

    Scoring (per published spec):
      WOW: avg session < 30 min AND no session > 60 min
      OK:  avg 30-60 min OR one session > 60 min OR thin data
      DOD: avg > 60 min OR any session > 2h today

    On thin data (<3 sessions): OK, not DOD. Matches truth-first rule —
    don't claim WOW we can't back up, don't page on DOD for no data.
    """
    try:
        from browser_sessions import get_browser_summary
    except ImportError as e:
        return OK, f"browser_sessions import failed: {e}"

    try:
        summary = get_browser_summary(days=1)
    except Exception as e:
        return DOD, f"get_browser_summary crashed: {e}"

    accounts = (summary or {}).get("accounts") or {}
    if not accounts or summary.get("thin_data"):
        return OK, "browser data collecting (<3 sessions or no snapshots)"

    dod_issues = []
    avg_max = 0.0
    long_today_any = False
    for aid, data in accounts.items():
        if data.get("thin_data"):
            continue
        longest = data.get("longest_session_min", 0) or 0
        avg = data.get("avg_duration_min", 0) or 0
        if longest > 120:
            dod_issues.append(f"{aid}: {longest}min session today (>2hr)")
        if avg > 60:
            dod_issues.append(f"{aid}: avg {avg}min (>60min avg)")
        if longest > 60:
            long_today_any = True
        if avg > avg_max:
            avg_max = avg

    if dod_issues:
        return DOD, "; ".join(dod_issues)
    if avg_max > 30 or long_today_any:
        return OK, f"avg session {avg_max:.0f}min, longest>60min={long_today_any}"
    return WOW, f"avg session {avg_max:.0f}min — healthy"


def check_researcher_staleness():
    """v4.5.3 M-3 — flag a silent burnctl-researcher cron failure.

    burnctl-researcher is expected to refresh research-reports/ daily at
    06:30 UTC. We look for either `research-reports/latest.md` (the canonical
    pointer) or, failing that, the newest dated report in the directory.
    If neither exists or the freshest is older than 25 h we DOD so the
    human notices before pitch-day relies on stale intel.
    """
    rr_dir = Path(__file__).parent / "research-reports"
    if not rr_dir.is_dir():
        return DOD, "research-reports/ directory missing — burnctl-researcher not set up"
    target = rr_dir / "latest.md"
    if not target.exists():
        # Fallback: newest *.md by mtime
        dated = sorted(
            (p for p in rr_dir.glob("*.md") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not dated:
            return DOD, "research-reports/ is empty — run burnctl-researcher manually"
        target = dated[0]
    try:
        age_s = time.time() - target.stat().st_mtime
    except OSError as e:
        return DOD, f"could not stat {target.name}: {e}"
    hours = age_s / 3600.0
    label = target.name
    if hours > 25:
        return DOD, (
            f"research-reports/{label} is {hours:.1f} hours old — "
            "burnctl-researcher cron may have failed"
        )
    # Freshness sliding scale: anything under 25 h is good; under 12 h is ideal.
    if hours > 12:
        return OK, f"research-reports/{label} is {hours:.1f}h old (fresh but >12h)"
    return WOW, f"research-reports/{label} refreshed {hours:.1f}h ago"


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
    ("claudemd-audit",  "npx",  "claudemd-audit",        score_smoke),
    ("mcp-audit",       "npx",  "mcp-audit",             score_smoke),
    ("why-limit",       "npx",  "why-limit",             score_smoke),
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

    # v4.3.0 check 18 — browser session health (in-process, not npx/curl)
    t0 = time.monotonic()
    status, evidence = check_browser_session_health()
    results.append({
        "name": "browser-session-health",
        "kind": "local",
        "arg": "browser_sessions.get_browser_summary",
        "status": status,
        "evidence": evidence,
        "exit_code": 0 if status != DOD else 2,
        "elapsed_sec": round(time.monotonic() - t0, 2),
        "output_head": evidence[:500],
    })

    # v4.5.3 M-3 — researcher report freshness (catches silent cron failure).
    t0 = time.monotonic()
    status, evidence = check_researcher_staleness()
    results.append({
        "name": "researcher-staleness",
        "kind": "local",
        "arg": "research-reports/latest.md mtime",
        "status": status,
        "evidence": evidence,
        "exit_code": 0 if status != DOD else 2,
        "elapsed_sec": round(time.monotonic() - t0, 2),
        "output_head": evidence[:500],
    })

    return results


def capture_local_metrics():
    """Run commands against the REAL local DB (not /tmp) to capture numeric
    metrics the fresh-install suite cannot see. Returns a dict of
    metric_name -> float.

    Keep this pass short and read-only — this runs every day under cron.
    """
    metrics = {}

    # fix-scoreboard — monthly savings
    try:
        proc = subprocess.run(
            ["python3", str(REPO_DIR / "cli.py"), "fix-scoreboard"],
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=LOCAL_CMD_TIMEOUT,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r"API-equivalent monthly savings:\s*\$([\d,]+\.?\d*)", out)
        if m:
            metrics["fix_monthly_savings_usd"] = float(m.group(1).replace(",", ""))
        m = re.search(r"Tokens saved.*:\s*([\d,]+)", out)
        if m:
            metrics["fix_tokens_saved"] = int(m.group(1).replace(",", ""))
        m = re.search(r"Improving:\s*(\d+)", out)
        if m:
            metrics["fix_improving_count"] = int(m.group(1))
    except Exception:
        pass

    # work-timeline — CC vs browser ratio (today only)
    try:
        proc = subprocess.run(
            ["python3", str(REPO_DIR / "cli.py"), "work-timeline"],
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=LOCAL_CMD_TIMEOUT,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r"Claude Code CLI\s+(\d+)% of active time", out)
        if m:
            metrics["work_cc_pct"] = int(m.group(1))
        m = re.search(r"Browser claude\.ai\s+(\d+)% of active time", out)
        if m:
            metrics["work_browser_pct"] = int(m.group(1))
    except Exception:
        pass

    return metrics


def extract_report_metrics(results, local_metrics):
    """Build the machine-readable trend block embedded in each report."""
    wow = sum(1 for r in results if r["status"] == WOW)
    ok = sum(1 for r in results if r["status"] == OK)
    dod = sum(1 for r in results if r["status"] == DOD)

    kv = {
        "wow_count": wow,
        "ok_count": ok,
        "dod_count": dod,
    }

    # pull from scored results
    for r in results:
        if r["name"] == "resume-audit":
            m = re.search(r"\(([\d.]+)%\)", r["evidence"])
            if m:
                kv["resume_audit_flag_pct"] = float(m.group(1))
        elif r["name"] == "api/stats":
            m = re.search(r"\$([\d,]+\.?\d*)\s+across\s+([\d,]+)", r["evidence"])
            if m:
                kv["api_stats_cost_usd"] = float(m.group(1).replace(",", ""))
                kv["api_stats_total_turns"] = int(m.group(2).replace(",", ""))
        elif r["name"] == "api/health":
            m = re.search(r"v([\d.]+)", r["evidence"])
            if m:
                kv["api_health_version"] = m.group(1)

    # merge in local (real-DB) captures
    kv.update(local_metrics)
    return kv


def format_trend_block(kv):
    lines = ["<!-- trend-metrics:start -->"]
    for k in sorted(kv.keys()):
        v = kv[k]
        if isinstance(v, float):
            lines.append(f"{k}={v:.2f}")
        else:
            lines.append(f"{k}={v}")
    lines.append("<!-- trend-metrics:end -->")
    return "\n".join(lines)


def parse_trend_block(report_text):
    """Extract kv pairs from a report's trend-metrics block. Returns dict."""
    m = re.search(
        r"<!--\s*trend-metrics:start\s*-->\s*(.*?)\s*<!--\s*trend-metrics:end\s*-->",
        report_text,
        re.DOTALL,
    )
    if not m:
        return {}
    kv = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        try:
            kv[k] = float(v) if "." in v else int(v)
        except ValueError:
            kv[k] = v  # e.g. version string
    return kv


def load_trend_history(days_back=7):
    """Load all qa-reports/*.md from the last N days with a trend block.

    Returns list of (timestamp, kv) sorted by timestamp. Excludes latest.md
    since timestamped files already cover the same content.
    """
    cutoff = time.time() - days_back * 86400
    history = []
    for p in sorted(QA_DIR.glob("*.md")):
        if p.name == "latest.md":
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(\d{2})\.md$", p.name)
        if not m:
            continue
        try:
            dt = datetime.datetime.strptime(
                f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H"
            ).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        if dt.timestamp() < cutoff:
            continue
        try:
            kv = parse_trend_block(p.read_text())
        except OSError:
            continue
        if kv:
            history.append((dt, kv))
    return history


def render_trend_table():
    """Human-readable trend table across last 7 days of reports."""
    history = load_trend_history(7)
    if len(history) < 2:
        print()
        print(f"burnctl trend — need at least 2 snapshots, have {len(history)}")
        print(f"Reports dir: {QA_DIR}")
        print()
        print("Run `burnctl qa` daily (or let cron do it). After 2+ runs, the")
        print("trend table will show movement per metric with drift flags.")
        return

    # pick three anchor snapshots: oldest, middle, newest
    newest = history[-1]
    oldest = history[0]
    middle = history[len(history) // 2]

    metrics_order = [
        ("wow_count",              "WOW commands",              "count",   False),
        ("dod_count",              "DOD commands",              "count",   True),
        ("resume_audit_flag_pct",  "resume-audit noise",        "percent", True),
        ("api_stats_cost_usd",     "total cost (DB lifetime)",  "usd",     False),
        ("api_stats_total_turns",  "total turns logged",        "int",     False),
        ("fix_monthly_savings_usd","fixes monthly savings",     "usd",     False),
        ("fix_improving_count",    "fixes improving",           "count",   False),
        ("work_cc_pct",            "CC share of active time",   "percent", False),
        ("work_browser_pct",       "browser share",             "percent", False),
    ]

    print()
    print(f"burnctl trend — {len(history)} snapshot(s) over the last 7 days")
    print("=" * 74)
    print(f"{'METRIC':<28} {'OLDEST':>12} {'MID':>10} {'LATEST':>10}  TREND")
    print("-" * 74)

    def fmt(v, kind):
        if v is None:
            return "—"
        if kind == "usd":
            return f"${v:,.0f}"
        if kind == "percent":
            return f"{v:.1f}%"
        if kind == "int":
            return f"{v:,}"
        return str(v)

    def direction(a, b, lower_is_better):
        if a is None or b is None:
            return "       —"
        if a == 0:
            return "  (new)  "
        delta = b - a
        pct = (delta / a * 100) if a else 0
        drift_trigger = TREND_DRIFT_PCT
        if abs(pct) < drift_trigger / 2:
            return "[stable] "
        if (delta > 0 and not lower_is_better) or (delta < 0 and lower_is_better):
            return f"[OK] {pct:+.0f}%  "
        # wrong direction — flag drift if big enough
        if abs(pct) >= drift_trigger:
            return f"[DRIFT] {pct:+.0f}%"
        return f"[slip] {pct:+.0f}% "

    def get(kv, key):
        return kv.get(key)

    for key, label, kind, lower_is_better in metrics_order:
        oldv = get(oldest[1], key)
        midv = get(middle[1], key)
        newv = get(newest[1], key)
        arrow = direction(oldv, newv, lower_is_better)
        print(
            f"{label:<28} "
            f"{fmt(oldv, kind):>12} "
            f"{fmt(midv, kind):>10} "
            f"{fmt(newv, kind):>10}  "
            f"{arrow}"
        )

    print("-" * 74)
    print(f"oldest: {oldest[0].strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"latest: {newest[0].strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"snapshots used: {len(history)}")
    print()
    print(f"Drift threshold: {TREND_DRIFT_PCT}% move in the wrong direction.")
    print(f"Full reports: {QA_DIR}")


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


def format_report(results, regressions, prior_path, trend_block=""):
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

    if trend_block:
        lines.append(trend_block)
    return "\n".join(lines)


def main():
    # --trend renders historical view and exits; no new test run
    if "--trend" in sys.argv:
        render_trend_table()
        return

    QA_DIR.mkdir(parents=True, exist_ok=True)
    prior_path = QA_DIR / "latest.md"
    prior = load_prior_results(prior_path)

    print(f"burnctl daily_qa — running {len(TESTS) + 1} checks...")
    results = run_all_tests()
    local_metrics = capture_local_metrics()
    trend_kv = extract_report_metrics(results, local_metrics)
    trend_block = format_trend_block(trend_kv)
    regressions = detect_regressions(results, prior)
    report = format_report(results, regressions, prior_path, trend_block)

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
