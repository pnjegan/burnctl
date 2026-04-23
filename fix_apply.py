"""burnctl fix apply <n> — write a generated fix to the actual CLAUDE.md.

Closes the manual copy-paste step in the loop:
  burnctl audit          → list waste patterns + fix recommendations
  burnctl fix apply <n>  → writes fix to CLAUDE.md, marks measuring
  [work normally for 2-3 sessions]
  burnctl measure <n>    → check the impact
  burnctl fix-scoreboard → see the full ROI

Schema notes (real DB on this scanner version):
  - fixes.applied_at column does NOT exist by default — we lazy-add it on
    first run with ALTER TABLE (idempotent).
  - "Already applied" = applied_to_path IS NOT NULL OR applied_at IS NOT NULL
  - fix_type values seen in production: 'claude_md_rule' (also accept 'claude_md'
    if a future generator emits it). We match `LIKE 'claude_md%'`.
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def load_db():
    """3-tier resolution matching burn_rate.resolve_db_path():
       cwd/data/usage.db → ~/.burnctl/data/usage.db → script_dir/data/usage.db.
    """
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/.burnctl/data/usage.db"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


def _ensure_applied_at_column(conn):
    """Lazy ALTER. Idempotent — silently no-op if the column already exists."""
    try:
        conn.execute("ALTER TABLE fixes ADD COLUMN applied_at INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def _find_claude_md():
    """Locate target CLAUDE.md. cwd-relative wins; ~/.claude is fallback.
    Returns (Path, scope_label) or (None, None) if neither exists."""
    candidates = [
        (Path.cwd() / "CLAUDE.md", "project (cwd)"),
        (Path.cwd() / "claude.md", "project (cwd)"),
        (Path.home() / ".claude" / "CLAUDE.md", "global (~/.claude)"),
        (Path.home() / ".claude" / "claude.md", "global (~/.claude)"),
    ]
    for path, scope in candidates:
        if path.exists():
            return path, scope
    return None, None


def _is_already_applied(row):
    """row schema: (applied_at, applied_to_path, status)"""
    applied_at, applied_to_path, status = row
    return bool(applied_at) or bool(applied_to_path) or status == "measuring"


def _finalize_apply(conn, fix_id, target_path):
    """Atomically finalize a fix apply: capture baseline, write
    status/applied_at/applied_to_path/baseline_json in a single UPDATE.
    Shared by CLI (apply_fix here) and HTTP (/api/fixes/:id/apply).

    Raises on capture or write failure — caller is responsible for any
    file-side rollback (e.g. restoring the CLAUDE.md backup)."""
    import json
    from fix_tracker import capture_baseline

    # capture_baseline uses row["col"] dict-style access; ensure Row factory
    # regardless of how the caller opened the connection (CLI load_db does
    # not set this; server.get_conn already does).
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT project FROM fixes WHERE id = ?", (fix_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"fix {fix_id} not found")
    project = row[0]

    baseline = capture_baseline(conn, project)
    now_ts = int(datetime.now(timezone.utc).timestamp())

    conn.execute(
        "UPDATE fixes SET status='measuring', applied_at=?, "
        "applied_to_path=?, baseline_json=? WHERE id=?",
        (now_ts, str(target_path), json.dumps(baseline), fix_id),
    )
    conn.commit()


def apply_fix(fix_id):
    print(f"\nburnctl fix apply {fix_id}")
    print("=" * 50)

    conn = load_db()
    if not conn:
        print("No burnctl database found.")
        print("Run `burnctl scan` from your project directory first.")
        return False

    _ensure_applied_at_column(conn)

    cur = conn.cursor()
    cur.execute("""
        SELECT id, project, waste_pattern, title,
               fix_type, fix_detail, status,
               applied_at, applied_to_path
        FROM fixes WHERE id = ?
    """, (fix_id,))
    row = cur.fetchone()
    if not row:
        print(f"Fix #{fix_id} not found.")
        print("Run `burnctl audit` to see what waste patterns exist,")
        print("then `burnctl fixes` to see fix IDs.")
        conn.close()
        return False

    (fid, project, pattern, title, fix_type, fix_detail,
     status, applied_at, applied_to_path) = row

    print(f"\nFix #{fid}: {title}")
    print(f"Project:  {project or 'all projects'}")
    print(f"Pattern:  {pattern}")
    print(f"Type:     {fix_type}")

    if _is_already_applied((applied_at, applied_to_path, status)):
        print()
        print("⚠️  This fix is already in the applied / measuring state:")
        if applied_to_path:
            print(f"   Path:       {applied_to_path}")
        if applied_at:
            ts = datetime.fromtimestamp(applied_at).strftime("%Y-%m-%d %H:%M")
            print(f"   Applied at: {ts}")
        print(f"   Status:     {status}")
        print()
        print(f"Run `burnctl measure {fid}` to check progress.")
        conn.close()
        return False

    # fix_type accept claude_md and claude_md_rule (and any future variant)
    if not fix_type or not fix_type.lower().startswith("claude_md"):
        print()
        print(f"This fix type ({fix_type!r}) is not a CLAUDE.md edit.")
        print("Apply manually:")
        print("-" * 50)
        print(fix_detail or "(no fix detail)")
        print("-" * 50)
        conn.close()
        return False

    if not fix_detail or not fix_detail.strip():
        print("Fix detail is empty. Nothing to apply.")
        conn.close()
        return False

    target_path, scope = _find_claude_md()
    if target_path is None:
        print()
        print("❌ No CLAUDE.md found in cwd or ~/.claude/")
        print("Create one first:")
        print(f"   touch {Path.cwd() / 'CLAUDE.md'}")
        print(f"   # or")
        print(f"   touch {Path.home() / '.claude' / 'CLAUDE.md'}")
        conn.close()
        return False

    print(f"\nTarget:   {target_path}  ({scope})")

    # Idempotent: skip if the rule's first 60 chars already appear
    existing = target_path.read_text() if target_path.exists() else ""
    fingerprint = fix_detail.strip()[:60]
    if fingerprint and fingerprint in existing:
        print()
        print("⚠️  This fix's content already appears to be in the file.")
        print(f"   (fingerprint match on: {fingerprint!r})")
        print("   Marking applied in the DB anyway.")
        idempotent = True
    else:
        idempotent = False
        print(f"\nWill append to {target_path}:")
        print("-" * 50)
        print(fix_detail.strip())
        print("-" * 50)

    print(f"\nApply this fix? [y/N] ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer != "y":
        print("Cancelled.")
        conn.close()
        return False

    try:
        if not idempotent:
            sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
            stamp = datetime.now().strftime("%Y-%m-%d")
            header = f"<!-- burnctl fix #{fid} applied {stamp} -->\n"
            target_path.write_text(
                existing + sep + header + fix_detail.strip() + "\n"
            )
            print(f"\n✅ Appended to {target_path}")
    except PermissionError:
        print(f"\n❌ Permission denied writing to {target_path}")
        conn.close()
        return False
    except OSError as e:
        print(f"\n❌ Error writing file: {e}")
        conn.close()
        return False

    # Update DB — unified apply finalization: captures baseline +
    # atomically writes status/applied_at/applied_to_path/baseline_json.
    # Same helper is called by the HTTP apply handler (server.py).
    _finalize_apply(conn, fid, target_path)
    conn.close()

    print()
    print(f"✅ Fix #{fid} applied to {target_path}")
    print()
    print("Next steps (manual):")
    print(f"  Work normally for 2-3 sessions")
    print(f"  Then run: burnctl measure {fid}")
    print(f"  Then run: burnctl fix-scoreboard")
    print()
    print("Auto-measure hook: coming in a future version.")
    print()
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: burnctl fix apply <fix_id>")
        sys.exit(1)
    try:
        fix_id = int(sys.argv[1])
    except ValueError:
        print(f"Invalid fix id: {sys.argv[1]}")
        sys.exit(1)
    apply_fix(fix_id)
