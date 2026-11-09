#!/usr/bin/env python3
"""burnctl pre-session audit — the 7 checks, as one runnable command each.

Why this exists: the checks used to live in `burnctl-auditor.md` as compound
shell pipelines. A non-interactive session (which is how the nightly cron runs)
refuses them as multiple operations needing approval, so on 2026-11-09 five of
seven checks came back BLOCKED and the gate could not reach GO regardless of
repo state. The greps were never the problem; the delivery was.

Everything here is stdlib and runs as a single process, so one permission rule
covers all seven checks, and the grep logic now lives in version-controlled
code where it can be read and tested instead of in an agent prompt.

Usage:
    python3 tools/audit_checks.py              # all checks + verdict
    python3 tools/audit_checks.py --check 4     # one check
    python3 tools/audit_checks.py --json        # machine-readable

Exit codes:
    0  GO       — every check PASS, warnings allowed
    1  NO-GO    — at least one FAIL (a real finding)
    3  BLOCKED  — at least one check could not be executed
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS, WARN, FAIL, BLOCKED = "PASS", "WARN", "FAIL", "BLOCKED"

# ── Check 2: hardcoded maintainer paths ───────────────────────────────────────
PATH_PATTERNS = ("projects/burnctl", "/root/projects", "pnjegan", "174.138")
COMMENT_RE = re.compile(r"^\s*#")
# A bare string literal on its own line is a detection pattern, not a path in
# use. daily_qa.py holds "~/projects/burnctl" and "/root/projects/burnctl" in
# _DEFAULT_LEAK_PATTERNS -- those two lines ARE the leak detector, and three
# research cycles reported them as a shipping defect. A real hardcode sits
# inside an expression, e.g. os.path.expanduser("~/projects/burnctl/..."),
# which is a call and still gets flagged.
BARE_LITERAL_RE = re.compile(r'^\s*"[^"]*",?\s*$|^\s*\'[^\']*\',?\s*$')
# Each exemption needs a reason. The public repo URL is the same class as the
# LICENSE copyright line: shipped attribution, not a maintainer-path leak.
# Note the ORIGINAL shell check never saw these at all -- its `grep -v ".git"`
# had an unescaped, unanchored dot, so it matched "github" and silently dropped
# every line containing github.com/pnjegan. Four user-visible hits were
# invisible for the entire life of that check.
PATH_EXEMPT_SUBSTRINGS = {
    "github.com/pnjegan/burnctl":
        "the public repository URL -- shipped attribution, same class as the "
        "LICENSE copyright, not a maintainer-path leak",
}

# ── Check 3: branding ─────────────────────────────────────────────────────────
BRANDING_PATTERNS = ("Claudash", "claudash")
# Each exemption needs a reason. A bare entry here silently re-opens the check.
BRANDING_EXEMPT_SUBSTRINGS = {
    "(?:burnctl|claudash)-":
        "a read-side regex accepting backup filenames written before the "
        "rebrand; back-compat for upgraders, never emitted",
}
BRANDING_EXEMPT = {
    "daily_qa.py": "the branding detector itself -- flagging it asks the QA "
                   "script to stop detecting branding leaks",
    "server.py": "the sanitiser map that rewrites claudash -> burnctl on the "
                 "way out, plus a comment about the v3.x JSON surface",
}

# ── Check 4: schema drift ─────────────────────────────────────────────────────
# Column names are TABLE-SCOPED. Matching bare identifiers reported ~150
# legitimate lines as drift: token_cost is a real column on waste_events and
# fix_id is a real column on fix_measurements. Only SQL context counts.
DRIFT_RE = re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE)\s+browser_activity\b"
    r"|\bwaste_type\b"
    r"|\bbaseline_waste_events\b"
    r"|\bmeasured_waste_events\b"
    r"|(?:SELECT|SET|,)\s*start_time\s*(?:,|\s+FROM|=)"
)

# ── Check 5: npm hygiene ──────────────────────────────────────────────────────
FORBIDDEN_IN_TARBALL = ("tools/get-derived-keys.py", ".env", "data/usage.db",
                        "__pycache__", ".pyc", "CLAUDE.md", "deploy.sh")

HEALTH_URL = "http://localhost:8080/api/health"


def _root_py():
    out = []
    for name in sorted(os.listdir(REPO)):
        if name.endswith(".py") and os.path.isfile(os.path.join(REPO, name)):
            out.append(name)
    bindir = os.path.join(REPO, "bin")
    if os.path.isdir(bindir):
        for name in sorted(os.listdir(bindir)):
            p = os.path.join(bindir, name)
            if os.path.isfile(p):
                out.append(os.path.join("bin", name))
    return out


def _prose_lines(lines):
    """Line numbers (1-based) that are comment or docstring prose.

    A docstring line is prose, not code. `cli.py` explains its deliberate
    backup path in a docstring, and flagging the explanation as a leak is the
    same mistake as flagging a detector. Tracks unterminated triple quotes
    rather than guessing, so a string containing a `#` is not mistaken for a
    comment and vice versa.
    """
    prose, in_doc, delim = set(), False, None
    delims = (chr(34) * 3, chr(39) * 3)
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_doc:
            prose.add(n)
            if delim in line:
                in_doc, delim = False, None
            continue
        if COMMENT_RE.match(line):
            prose.add(n)
            continue
        for d in delims:
            if d in stripped:
                if stripped.count(d) == 1:      # opens a multi-line docstring
                    in_doc, delim = True, d
                    prose.add(n)
                break
    return prose


def _lines(rel):
    path = os.path.join(REPO, rel)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def check1_qa_gate():
    rel = os.path.join("qa-reports", "latest.md")
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        return BLOCKED, ["qa-reports/latest.md does not exist "
                         "(do not substitute an older report)"], {}
    age_h = (time.time() - os.path.getmtime(path)) / 3600.0
    text = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*WOW.*?(\d+)\s*OK.*?(\d+)\s*DOD", text, re.S)
    ev = [f"{rel} is {age_h:.1f}h old"]
    meta = {"age_hours": round(age_h, 1)}
    if not m:
        return BLOCKED, ev + ["could not parse the WOW/OK/DOD summary line"], meta
    wow, total, ok, dod = (int(g) for g in m.groups())
    meta.update(wow=wow, total=total, ok=ok, dod=dod)
    ev.append(f"{wow}/{total} WOW, {ok} OK, {dod} DOD")
    if dod > 0:
        return FAIL, ev + [f"{dod} DOD item(s) -- NO-GO per CLAUDE.md"], meta
    if age_h > 24:
        return WARN, ev + ["report is over 24h old"], meta
    if ok > 0:
        return WARN, ev + [f"{ok} OK item(s) -- review as thin-data states"], meta
    return PASS, ev, meta


def check2_hardcoded_paths():
    hits, exempt = [], []
    for rel in _root_py():
        lines = _lines(rel)
        prose = _prose_lines(lines)
        for n, line in enumerate(lines, 1):
            if not any(p in line for p in PATH_PATTERNS):
                continue
            why = next((r for sub, r in PATH_EXEMPT_SUBSTRINGS.items() if sub in line), None)
            if why:
                exempt.append(f"{rel}:{n} ({why})")
            elif n in prose:
                exempt.append(f"{rel}:{n} (comment or docstring prose)")
            elif BARE_LITERAL_RE.match(line):
                exempt.append(f"{rel}:{n} (bare literal in a detection list)")
            else:
                hits.append(f"{rel}:{n}: {line.strip()[:100]}")
    ev = [f"{len(hits)} hit(s); {len(exempt)} exempt"] + [f"  exempt: {e}" for e in exempt]
    if hits:
        return FAIL, ev + hits, {"hits": len(hits)}
    return PASS, ev, {"hits": 0}


def check3_branding():
    real, exempt = [], []
    targets = _root_py()
    tdir = os.path.join(REPO, "templates")
    if os.path.isdir(tdir):
        targets += [os.path.join("templates", f) for f in sorted(os.listdir(tdir))
                    if os.path.isfile(os.path.join(tdir, f)) and ".bak-" not in f]
    for rel in targets:
        lines = _lines(rel)
        prose = _prose_lines(lines)
        for n, line in enumerate(lines, 1):
            if not any(p in line for p in BRANDING_PATTERNS):
                continue
            base = os.path.basename(rel)
            why = next((r for sub, r in BRANDING_EXEMPT_SUBSTRINGS.items() if sub in line), None)
            if base in BRANDING_EXEMPT:
                exempt.append(f"{rel}:{n} ({BRANDING_EXEMPT[base]})")
            elif why:
                exempt.append(f"{rel}:{n} ({why})")
            elif n in prose:
                exempt.append(f"{rel}:{n} (comment or docstring prose)")
            else:
                real.append(f"{rel}:{n}: {line.strip()[:100]}")
    ev = [f"{len(real)} user-visible hit(s); {len(exempt)} exempt"] + \
         [f"  exempt: {e}" for e in exempt]
    if real:
        return FAIL, ev + real, {"real": len(real), "exempt": len(exempt)}
    return PASS, ev, {"real": 0, "exempt": len(exempt)}


def check4_schema_drift():
    doc = os.path.join(REPO, "docs", "schema.md")
    if not os.path.exists(doc):
        return BLOCKED, ["docs/schema.md missing -- nothing to resolve "
                         "(table, column) against"], {}
    hits = []
    for rel in _root_py():
        for n, line in enumerate(_lines(rel), 1):
            if DRIFT_RE.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:100]}")
    ev = ["resolved against docs/schema.md; SQL context only, never bare identifiers",
          f"{len(hits)} hit(s)"]
    if hits:
        return FAIL, ev + hits, {"hits": len(hits)}
    return PASS, ev, {"hits": 0}


def check5_npm_hygiene():
    try:
        r = subprocess.run(["npm", "pack", "--dry-run"], cwd=REPO,
                           capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return BLOCKED, ["npm is not installed"], {}
    except subprocess.TimeoutExpired:
        return BLOCKED, ["npm pack --dry-run timed out after 180s"], {}
    out = (r.stdout or "") + (r.stderr or "")
    if not out.strip():
        return BLOCKED, ["npm pack --dry-run produced no output"], {}
    listed = [ln for ln in out.splitlines() if ln.startswith("npm notice")]
    bad = [ln.strip() for ln in listed
           if any(f in ln for f in FORBIDDEN_IN_TARBALL)]
    nm = re.search(r"total files:\s*(\d+)", out)
    sz = re.search(r"package size:\s*([\d.]+\s*\w+)", out)
    meta = {"total_files": int(nm.group(1)) if nm else None,
            "package_size": sz.group(1) if sz else None}
    ev = [f"tarball: {meta['total_files']} files, {meta['package_size']}"]
    # npm pack writes a tgz even on --dry-run in some versions; clean up.
    for f in os.listdir(REPO):
        if f.startswith("burnctl-") and f.endswith(".tgz"):
            try:
                os.remove(os.path.join(REPO, f))
            except OSError:
                pass
    if bad:
        return FAIL, ev + ["forbidden file(s) in tarball:"] + bad, meta
    return PASS, ev + ["no forbidden files (.env, get-derived-keys.py, "
                       "data/*.db, __pycache__, *.pyc)"], meta


def check6_version_match():
    pkg = os.path.join(REPO, "package.json")
    if not os.path.exists(pkg):
        return BLOCKED, ["package.json missing"], {}
    try:
        disk = json.load(open(pkg))["version"]
    except Exception as exc:
        return BLOCKED, [f"package.json unreadable: {exc}"], {}
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=8) as resp:
            live = json.loads(resp.read().decode())["version"]
    except Exception as exc:
        return BLOCKED, [f"package.json={disk}",
                         f"{HEALTH_URL} unreachable: {exc}"], {"disk": disk}
    meta = {"disk": disk, "live": live}
    ev = [f"package.json={disk}  /api/health={live}"]
    if disk != live:
        return WARN, ev + ["mismatch -- pm2 may be serving stale code; "
                           "run bash deploy.sh"], meta
    return PASS, ev, meta


def check7_backlog():
    rel = os.path.join("qa-reports", "findings-backlog.md")
    path = os.path.join(REPO, rel)
    if not os.path.exists(path):
        return PASS, ["no backlog file (optional) -- 0 items"], {"items": 0}
    items = []
    for n, line in enumerate(_lines(rel), 1):
        m = re.match(r"^## (\d+)\.\s*(.+?)\s*$", line)
        if m:
            items.append(f"{rel}:{n}: {m.group(2)[:90]}")
    return PASS, [f"{len(items)} open item(s)"] + items, {"items": len(items)}


CHECKS = {
    1: ("QA gate", check1_qa_gate),
    2: ("Hardcoded paths", check2_hardcoded_paths),
    3: ("Branding leaks", check3_branding),
    4: ("Schema drift", check4_schema_drift),
    5: ("npm hygiene", check5_npm_hygiene),
    6: ("Version match", check6_version_match),
    7: ("Backlog", check7_backlog),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", type=int, choices=sorted(CHECKS),
                    help="run a single check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    ids = [args.check] if args.check else sorted(CHECKS)
    results = {}
    for cid in ids:
        name, fn = CHECKS[cid]
        try:
            status, evidence, meta = fn()
        except Exception as exc:                      # never crash the gate
            status, evidence, meta = BLOCKED, [f"check raised {type(exc).__name__}: {exc}"], {}
        results[cid] = {"name": name, "status": status,
                        "evidence": evidence, "meta": meta}

    statuses = [r["status"] for r in results.values()]
    if BLOCKED in statuses:
        verdict, code = "NO-GO (a check could not be executed)", 3
    elif FAIL in statuses:
        verdict, code = "NO-GO", 1
    else:
        verdict, code = "GO", 0

    if args.json:
        print(json.dumps({"verdict": verdict, "exit_code": code,
                          "checks": results}, indent=2))
        return code

    print(f"burnctl pre-session audit — {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 66)
    for cid in ids:
        r = results[cid]
        print(f"\nCheck {cid} {r['name']}: {r['status']}")
        for line in r["evidence"]:
            print(f"    {line}")
    if not args.check:
        print("\n" + "=" * 66)
        print(f"VERDICT: {verdict}")
        blockers = [f"Check {c} {r['name']}" for c, r in results.items()
                    if r["status"] in (FAIL, BLOCKED)]
        warnings = [f"Check {c} {r['name']}" for c, r in results.items()
                    if r["status"] == WARN]
        print(f"BLOCKERS: {', '.join(blockers) if blockers else 'none'}")
        print(f"WARNINGS: {', '.join(warnings) if warnings else 'none'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
