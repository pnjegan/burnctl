#!/usr/bin/env python3
"""check_invariants.py — mechanical enforcement of INVARIANTS.md.

Two modes:
  --report        Human-readable pass/fail report, exit 0 always (for manual runs)
  (no args)       Claude Code Stop-hook mode: reads hook JSON on stdin, checks
                  stop_hook_active to avoid infinite loops, prints hook-format
                  JSON on stdout, exit 0 always (Stop hooks communicate via the
                  JSON body, not exit code -- see Claude Code hooks docs)

Checks implemented (see INVARIANTS.md for the human-readable rule):
  I1 — fix-rules savings must not exceed stats spend
  I2 — no session's summed waste may exceed its real cost
  I3 — the burnctl pm2 process must be newer than the last .py edit
  I5 — sessions row count vs distinct-request-id count sanity check

I4 (time-windowed queries) is structural, not mechanically checkable here --
that's the verifier subagent's job (see .claude/agents/verifier.md).
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.abspath(__file__ + "/../.."))
DB_PATH = os.path.join(REPO_ROOT, "data", "usage.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def check_i1_savings_vs_spend():
    """fix-rules total savings must not exceed stats 30d spend."""
    try:
        sys.path.insert(0, REPO_ROOT)
        from fix_rules import generate_claude_md_rules  # noqa: E402
        import re

        output = generate_claude_md_rules()
        m = re.search(r"estimated \$([\d,]+)/mo savings", output)
        savings = float(m.group(1).replace(",", "")) if m else 0.0

        conn = _conn()
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM sessions "
            "WHERE timestamp >= strftime('%s','now') - 30*86400"
        ).fetchone()
        spend = row["c"] or 0.0
        conn.close()

        ratio = (savings / spend) if spend > 0 else 0.0
        ok = ratio <= 1.0
        return {
            "id": "I1",
            "ok": ok,
            "detail": f"savings=${savings:,.0f}/mo spend=${spend:,.2f}/30d ratio={ratio:.2f}",
            "severity": "fail" if not ok else ("warn" if ratio > 0.6 else "ok"),
        }
    except Exception as e:
        return {"id": "I1", "ok": False, "detail": f"check errored: {e}", "severity": "error"}


def check_i2_per_session_waste_cap():
    """No session's summed waste may exceed its real cost (1.01x tolerance)."""
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT w.session_id, SUM(w.token_cost) AS waste, "
            "       (SELECT COALESCE(SUM(s.cost_usd),0) FROM sessions s "
            "         WHERE s.session_id = w.session_id) AS cost "
            "FROM waste_events w GROUP BY w.session_id "
            "HAVING waste > cost * 1.01"
        ).fetchall()
        conn.close()
        ok = len(rows) == 0
        detail = f"{len(rows)} session(s) exceed cost cap"
        if rows:
            worst = rows[0]
            detail += f"; worst: {worst['session_id']} waste=${worst['waste']:.2f} cost=${worst['cost']:.2f}"
        return {"id": "I2", "ok": ok, "detail": detail, "severity": "fail" if not ok else "ok"}
    except Exception as e:
        return {"id": "I2", "ok": False, "detail": f"check errored: {e}", "severity": "error"}


def check_i3_live_process_freshness():
    """pm2-managed burnctl process must be newer than the last .py edit."""
    try:
        result = subprocess.run(
            ["pm2", "jlist"], capture_output=True, text=True, timeout=10
        )
        procs = json.loads(result.stdout) if result.stdout else []
        burnctl_proc = next((p for p in procs if p.get("name") == "burnctl"), None)
        if burnctl_proc is None:
            return {"id": "I3", "ok": True, "detail": "no burnctl pm2 process found (not running under pm2 -- skip)", "severity": "ok"}

        started_at_ms = burnctl_proc.get("pm2_env", {}).get("pm_uptime", 0)
        started_at = started_at_ms / 1000.0

        newest_py_mtime = 0.0
        newest_py_file = None
        # INVARIANTS.md scopes I3 to "any .py file it imports" -- the running
        # daemon's own modules. This walk used to cover every .py in the repo,
        # so editing a test or a dev tool blocked the stop hook with a stale-
        # server verdict about code the server never loads. Verified
        # 2026-11-09: server.py, cli.py, scanner.py and db.py import nothing
        # from tests/ or tools/, and the daemon's modules are the root-level
        # .py files, which are still walked.
        #
        # If the daemon ever does import from tools/, remove it from this list
        # or I3 will miss a genuinely stale import. The origin incident
        # (2026-07-17, nine days of stale code silently rewriting data every
        # five minutes) is the reason this check must not be loosened further.
        SKIP_DIRS = (".git", "node_modules", "backups", "__pycache__",
                     "tests", "tools", "ARCHIVE", "venv", ".venv")
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(p)
                        if mtime > newest_py_mtime:
                            newest_py_mtime = mtime
                            newest_py_file = p
                    except OSError:
                        continue

        ok = started_at >= newest_py_mtime
        detail = (
            f"process started {time.ctime(started_at)}, "
            f"newest .py edit {time.ctime(newest_py_mtime)} ({newest_py_file})"
        )
        return {"id": "I3", "ok": ok, "detail": detail, "severity": "fail" if not ok else "ok"}
    except FileNotFoundError:
        return {"id": "I3", "ok": True, "detail": "pm2 not installed -- skip", "severity": "ok"}
    except Exception as e:
        return {"id": "I3", "ok": False, "detail": f"check errored: {e}", "severity": "error"}


def check_i5_dedup_sanity():
    """sessions row count vs distinct request_id count -- flag re-emergence of duplicate ingestion."""
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "       COUNT(DISTINCT CASE WHEN request_id IS NOT NULL AND request_id != '' "
            "                            THEN session_id || ':' || request_id END) AS distinct_req, "
            "       SUM(CASE WHEN request_id IS NULL OR request_id = '' THEN 1 ELSE 0 END) AS legacy_null "
            "FROM sessions WHERE timestamp >= strftime('%s','now') - 30*86400"
        ).fetchone()
        conn.close()
        total, distinct_req, legacy_null = row["total"], row["distinct_req"], row["legacy_null"]
        non_legacy = total - legacy_null
        dup_rate = ((non_legacy - distinct_req) / non_legacy) if non_legacy > 0 else 0.0
        ok = dup_rate < 0.02
        detail = f"30d rows={total} legacy_null={legacy_null} dup_rate={dup_rate:.1%}"
        return {"id": "I5", "ok": ok, "detail": detail, "severity": "fail" if not ok else "ok"}
    except Exception as e:
        return {"id": "I5", "ok": False, "detail": f"check errored: {e}", "severity": "error"}


def run_all_checks():
    return [
        check_i1_savings_vs_spend(),
        check_i2_per_session_waste_cap(),
        check_i3_live_process_freshness(),
        check_i5_dedup_sanity(),
    ]


def report_mode():
    results = run_all_checks()
    print("=== INVARIANTS.md mechanical check report ===\n")
    any_fail = False
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            any_fail = True
        print(f"[{mark}] {r['id']}: {r['detail']}")
    print("")
    print("ALL PASS" if not any_fail else "FAILURES PRESENT -- see above")
    return 0


def hook_mode():
    try:
        stdin_data = json.load(sys.stdin)
    except Exception:
        stdin_data = {}

    if stdin_data.get("stop_hook_active"):
        # Already looping on this hook -- don't block again for the same reason.
        print(json.dumps({}))
        return 0

    results = run_all_checks()
    failures = [r for r in results if not r["ok"]]

    if not failures:
        print(json.dumps({}))
        return 0

    reason_lines = ["INVARIANTS.md check failed -- fix before marking this task done:"]
    for r in failures:
        reason_lines.append(f"  {r['id']}: {r['detail']}")
    reason_lines.append("Re-run tools/hooks/check_invariants.py --report to verify after fixing.")

    print(json.dumps({
        "decision": "block",
        "reason": "\n".join(reason_lines),
    }))
    return 0


if __name__ == "__main__":
    if "--report" in sys.argv:
        sys.exit(report_mode())
    else:
        sys.exit(hook_mode())
