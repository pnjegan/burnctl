"""burnctl fix-rules — generate a CLAUDE.md rules section from YOUR waste.

Reads waste_events + compliance_events from the local DB and emits a
paste-ready CLAUDE.md section. Only patterns that appear in the DB get
rules — no generic advice, no hallucinated templates.

Sibling to fix_generator.py (agentic, per-event, LLM-backed). This
module is deterministic, aggregate, offline.

Entry point:
    generate_claude_md_rules(db_path=None) -> str

Monthly-saving estimate is (SUM(token_cost) / days_in_window) * 30.
When the data window is <7 days the output tags the number
"(thin data)" so operators don't over-trust it.
"""

import os
import sqlite3
from datetime import datetime


# ─── DB location (matches overhead_audit.load_db) ────────────────

def load_db(db_path=None):
    if db_path:
        return sqlite3.connect(db_path) if os.path.exists(db_path) else None
    candidates = [
        "data/usage.db",
        os.path.expanduser("~/projects/burnctl/data/usage.db"),
        os.path.expanduser("~/.burnctl/data/usage.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return sqlite3.connect(p)
    return None


# ─── Pattern → rule templates ────────────────────────────────────
# Key = waste_events.pattern_type (or compliance_events.pattern_id for
# compliance). Only patterns present in the DB emit a section.

WASTE_TEMPLATES = {
    "floundering": {
        "heading": "Stop retry loops",
        "lines": [
            "- If a bash command fails 3 times consecutively, STOP.",
            "  Report the error. Do not retry. Ask for guidance.",
            "- Never retry the same approach more than 3 times.",
        ],
    },
    "repeated_reads": {
        "heading": "Prevent repeated file reads",
        "lines": [
            "- Before reading any file, check if it was already read",
            "  this session. If yes, use the cached content.",
            "- Never read the same file twice in one session.",
            "- Use Read tool results from earlier in context —",
            '  do not re-read to "refresh".',
        ],
    },
    "deep_no_compact": {
        "heading": "Context compaction rules",
        "lines": [
            "- When context reaches 60%, run /compact immediately.",
            "- Never let context exceed 80% without compacting.",
            "- After compaction, confirm key facts are retained",
            "  before continuing.",
        ],
    },
    "cost_outlier": {
        "heading": "Session cost guardrails",
        "lines": [
            "- If a single session exceeds 3x your project's average cost,",
            "  stop and summarise progress. Start a fresh session.",
            "- Break tasks >2h estimated work into separate sessions.",
        ],
    },
    "oververbose_tool": {
        "heading": "Output terseness",
        "lines": [
            "- Keep all responses under 200 words unless explicitly asked",
            "  for detail.",
            "- Use bullet points for lists. No preamble. No summaries",
            "  of what you just did.",
            "- Code only: no explanation unless asked.",
        ],
    },
}

COMPLIANCE_TEMPLATES = {
    "four_tier_compaction": {
        "heading": "Four-tier compaction compliance",
        "lines": [
            "- Always follow the four-tier compaction hierarchy:",
            "  1. In-context summary first",
            "  2. /compact if >60% context",
            "  3. Handoff doc if switching tasks",
            "  4. Fresh session if context is polluted",
        ],
    },
}


# ─── Aggregates ──────────────────────────────────────────────────

def _waste_aggregates(conn):
    """Return {pattern_type: {"occurrences": n, "cost": $, "days": d}}."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pattern_type,
               COUNT(*),
               COALESCE(SUM(token_cost), 0),
               COALESCE(MIN(detected_at), 0),
               COALESCE(MAX(detected_at), 0)
        FROM waste_events
        GROUP BY pattern_type
        HAVING COUNT(*) > 0
    """)
    out = {}
    for pt, n, cost, mn, mx in cur.fetchall():
        days = max(1, (mx - mn) / 86400) if mx > mn else 1
        out[pt] = {
            "occurrences": int(n),
            "cost": float(cost or 0),
            "days": days,
        }
    return out


def _compliance_aggregates(conn):
    """Return {pattern_id: {"violations": n}} for status='violated'."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pattern_id, COUNT(*)
        FROM compliance_events
        WHERE status = 'violated'
        GROUP BY pattern_id
        HAVING COUNT(*) > 0
    """)
    return {pid: {"violations": int(n)} for pid, n in cur.fetchall()}


def _monthly_estimate(cost, days):
    """(cost over window) / days * 30. Clamp small windows."""
    if cost <= 0 or days <= 0:
        return 0.0
    return (cost / days) * 30.0


# ─── Renderer ────────────────────────────────────────────────────

def _fmt_usd(n):
    if n >= 1000:
        return f"${n:,.0f}"
    if n >= 10:
        return f"${n:,.0f}"
    return f"${n:.2f}"


def generate_claude_md_rules(db_path=None):
    conn = load_db(db_path)
    if not conn:
        return (
            "burnctl fix-rules — no database found.\n"
            "Run `burnctl scan` first, then re-run this command.\n"
        )

    waste = _waste_aggregates(conn)
    compliance = _compliance_aggregates(conn)
    conn.close()

    if not waste and not compliance:
        return (
            "burnctl fix-rules — no waste_events or compliance violations in DB.\n"
            "Either your usage is already clean, or scan hasn't run yet.\n"
        )

    today = datetime.utcnow().strftime("%Y-%m-%d")
    bar = "=" * 61

    lines = []
    lines.append(bar)
    lines.append(f"burnctl fix-rules — {today}")
    lines.append("Generated from YOUR real waste data (not generic advice)")
    lines.append(bar)
    lines.append("")

    # Compute sections in descending cost order (waste), then compliance.
    waste_rows = []
    total_monthly = 0.0
    for pt, stats in waste.items():
        if pt not in WASTE_TEMPLATES:
            continue  # skip unknown pattern_types — never fabricate a rule
        monthly = _monthly_estimate(stats["cost"], stats["days"])
        total_monthly += monthly
        waste_rows.append((pt, stats, monthly))
    waste_rows.sort(key=lambda r: r[2], reverse=True)

    # Truth-first: only show a headline total if every pattern has ≥7 days
    # of data backing it. Otherwise the extrapolation isn't defensible.
    any_thin = any(stats["days"] < 7 for _, stats, _ in waste_rows)

    lines.append("Paste this section into your CLAUDE.md:")
    lines.append("")
    lines.append("## Token Efficiency Rules (auto-generated by burnctl)")
    if any_thin or not waste_rows:
        lines.append(
            "## Based on your top waste patterns "
            "(headline estimate unavailable — <7 days of data)"
        )
    else:
        lines.append(
            f"## Based on your top waste patterns — estimated "
            f"{_fmt_usd(total_monthly)}/mo savings"
        )
    lines.append("")

    thin_data_flag = False
    for pt, stats, monthly in waste_rows:
        tmpl = WASTE_TEMPLATES[pt]
        thin = stats["days"] < 7
        if thin:
            thin_data_flag = True
        tag = " (thin data)" if thin else ""
        lines.append(
            f"### {tmpl['heading']} ({pt} — {stats['occurrences']} events, "
            f"{_fmt_usd(monthly)}/mo{tag})"
        )
        lines.extend(tmpl["lines"])
        lines.append("")

    for pid, stats in compliance.items():
        if pid not in COMPLIANCE_TEMPLATES:
            continue  # never fabricate compliance rules
        tmpl = COMPLIANCE_TEMPLATES[pid]
        lines.append(
            f"### {tmpl['heading']} ({pid} — {stats['violations']} violations)"
        )
        lines.extend(tmpl["lines"])
        lines.append("")

    lines.append(bar)
    lines.append("These rules target YOUR specific waste patterns.")
    if thin_data_flag:
        lines.append(
            "Note: some estimates are from <7 days of data — treat as"
        )
        lines.append("directional, not precise. Re-run after more scans.")
    lines.append("Run `burnctl measure` after 7 days to verify savings.")
    lines.append(bar)
    lines.append("")

    return "\n".join(lines)


# ─── CLI shim ────────────────────────────────────────────────────

def main():
    print(generate_claude_md_rules())


if __name__ == "__main__":
    main()
