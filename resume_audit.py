"""burnctl resume-audit — detect cache-bust signals from JSONL.

Reads ~/.claude/projects/*.jsonl directly (not the DB) so we can see
the per-turn TTL allocation that the DB doesn't preserve.

Cache-bust signals (cross-checked against community analyses):
  1. ephemeral_5m_input_tokens dominates ephemeral_1h_input_tokens
     → server gave 5-minute TTL → cache expires fast → re-cached on every pause
  2. cache_read_input_tokens near zero despite multi-turn input
     → cache miss → full context rebuild each turn

Sources:
  github.com/cnighswonger/claude-code-cache-fix (TTL-allocation analysis)
  github.com/ArkNill/claude-code-hidden-problem-analysis
  GitHub anthropics/claude-code issue #46829 (cache TTL regression)

Pure stdlib. No DB dependency.
"""

import json
import os
import glob
from collections import defaultdict
from datetime import datetime, timezone


# Sonnet input pricing — used as a CONSERVATIVE lower bound for the
# extra-cost estimate. Real cost depends on model used; we deliberately
# under-estimate to avoid alarmist numbers.
SONNET_INPUT_PER_TOKEN = 3.0 / 1_000_000


def _project_label(fpath):
    """Map JSONL file path → display-friendly project name.

    Claude Code stores sessions under ~/.claude/projects/<encoded-dir>/...
    where slashes in the original cwd are encoded as hyphens. We strip
    the predictable system prefixes for display only — substring match
    still works for filtering.
    """
    project_dir = os.path.basename(os.path.dirname(fpath))
    for prefix in ("-root-projects-", "-home-projects-",
                   "-home-Users-", "-Users-"):
        if project_dir.startswith(prefix):
            return project_dir[len(prefix):]
    return project_dir.lstrip("-") or "unknown"


def _record_timestamp(d):
    """Best-effort extraction of a unix-second timestamp from a JSONL record."""
    for ts_field in ("timestamp", "created_at"):
        raw = d.get(ts_field)
        if isinstance(raw, (int, float)) and raw > 1e9:
            return raw / 1000 if raw > 1e12 else raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(
                    raw.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                continue
    return None


def scan_jsonl_for_cache_health(days=30):
    """Walk ~/.claude/projects/ JSONL files, aggregate per-session totals."""
    cutoff_ts = datetime.now(timezone.utc).timestamp() - (days * 86400)
    base = os.path.expanduser("~/.claude/projects/")
    files = glob.glob(f"{base}/**/*.jsonl", recursive=True)

    sessions = defaultdict(lambda: {
        "project": "unknown",
        "total_input": 0,
        "total_output": 0,
        "cache_read": 0,
        "cache_5m": 0,
        "cache_1h": 0,
        "turns": 0,
        "first_ts": None,
    })

    for fpath in files:
        project = _project_label(fpath)
        session_id = os.path.basename(fpath).replace(".jsonl", "")
        try:
            with open(fpath, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = _record_timestamp(d)
                    if ts is not None and ts < cutoff_ts:
                        continue

                    msg = d.get("message", {}) if isinstance(d, dict) else {}
                    usage = (msg.get("usage")
                             if isinstance(msg, dict) else None) or d.get("usage")
                    if not isinstance(usage, dict):
                        continue

                    s = sessions[session_id]
                    s["project"] = project
                    if ts is not None and (s["first_ts"] is None or ts < s["first_ts"]):
                        s["first_ts"] = ts

                    s["total_input"] += int(usage.get("input_tokens") or 0)
                    s["total_output"] += int(usage.get("output_tokens") or 0)
                    s["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                    s["turns"] += 1

                    cc = usage.get("cache_creation")
                    if isinstance(cc, dict):
                        s["cache_5m"] += int(cc.get("ephemeral_5m_input_tokens") or 0)
                        s["cache_1h"] += int(cc.get("ephemeral_1h_input_tokens") or 0)
        except (IOError, OSError):
            continue

    return dict(sessions)


def analyze_cache_health(sessions):
    """Classify sessions by cache-bust signal severity."""
    busted = []
    healthy = []

    for sid, s in sessions.items():
        # Total input processed across all pathways (uncached + cache-read + new-cache)
        total_processed = (
            s["total_input"] + s["cache_read"] + s["cache_5m"] + s["cache_1h"]
        )

        if total_processed < 1000 or s["turns"] < 2:
            continue  # too small to draw a conclusion

        total_cache_creation = s["cache_5m"] + s["cache_1h"]
        # Fraction of all input bytes that arrived via cache_read (true hit rate)
        cache_read_ratio = s["cache_read"] / max(total_processed, 1)
        ttl_5m_ratio = (
            s["cache_5m"] / max(total_cache_creation, 1)
            if total_cache_creation > 0 else 0.0
        )

        signals = []
        severity = "ok"

        # 5m TTL dominance alone is not actionable — a session with 90%+
        # cache hit rate is healthy even if the TTL is short. Only flag
        # when the short TTL is actually hurting us (hit rate < 50%).
        if (
            total_cache_creation > 5000
            and ttl_5m_ratio > 0.85
            and cache_read_ratio < 0.50
        ):
            signals.append(
                f"Cache TTL: {ttl_5m_ratio*100:.0f}% on 5-minute TTL with "
                f"{cache_read_ratio*100:.1f}% hit rate "
                f"(expires fast AND misses — rebuilding context on pause)"
            )
            severity = "high"

        if cache_read_ratio < 0.05 and total_processed > 10000:
            signals.append(
                f"Cache hit rate: {cache_read_ratio*100:.1f}% "
                f"(<5% = likely full context rebuild each turn)"
            )
            severity = "high" if severity == "ok" else severity

        # Conservative extra-cost estimate (treats uncached input at half-rate
        # vs full Sonnet input pricing). Skipped for healthy cache hit ratios.
        extra_cost_estimate = 0.0
        if cache_read_ratio < 0.3:
            extra_cost_estimate = (
                total_processed * SONNET_INPUT_PER_TOKEN
                * (1 - cache_read_ratio) * 0.5
            )

        entry = {
            "session_id": sid[:16],
            "project": s["project"],
            "first_seen": (
                datetime.fromtimestamp(s["first_ts"]).strftime("%Y-%m-%d %H:%M")
                if s["first_ts"] else "unknown"
            ),
            "total_processed": total_processed,
            "cache_read": s["cache_read"],
            "cache_read_pct": round(cache_read_ratio * 100, 1),
            "cache_5m": s["cache_5m"],
            "cache_1h": s["cache_1h"],
            "ttl_5m_pct": round(ttl_5m_ratio * 100, 1),
            "turns": s["turns"],
            "extra_cost_estimate": round(extra_cost_estimate, 4),
            "signals": signals,
            "severity": severity,
        }

        if signals:
            busted.append(entry)
        else:
            healthy.append(entry)

    busted.sort(key=lambda x: x["extra_cost_estimate"], reverse=True)
    return busted, healthy


def run_resume_audit(days=30):
    print(f"\nburnctl resume-audit  (last {days} days)")
    print("=" * 58)
    print("Scanning JSONL files for cache-bust signals...")
    print("Signals: 5-minute TTL domination, low cache hit rate")
    print()

    sessions = scan_jsonl_for_cache_health(days)
    if not sessions:
        print("No sessions found in ~/.claude/projects/ for the lookback window.")
        return

    busted, healthy = analyze_cache_health(sessions)
    total = len(busted) + len(healthy)

    if not busted:
        print(f"✓ No cache-bust signals across {total} sessions analyzed.")
        print("  Cache appears to be working normally.")
        return

    total_extra = sum(s["extra_cost_estimate"] for s in busted)
    print(f"⚠️  {len(busted)} session(s) with cache-bust signals "
          f"(of {total} analyzed)\n")

    for s in busted[:10]:
        sev_icon = "🔴" if s["severity"] == "high" else "🟡"
        print(f"  {sev_icon} [{s['first_seen']}] {s['project']}")
        print(f"     Input processed: {s['total_processed']:,} tokens | "
              f"Cache hit: {s['cache_read_pct']}% | "
              f"5m TTL: {s['ttl_5m_pct']}%")
        for sig in s["signals"]:
            print(f"     → {sig}")
        if s["extra_cost_estimate"] > 0:
            print(f"     Est. extra cost (conservative): ${s['extra_cost_estimate']:.4f}")
        print()

    if len(busted) > 10:
        print(f"  ... and {len(busted) - 10} more sessions\n")

    print("=" * 58)
    if total_extra > 0:
        print(f"Est. extra cost from cache inefficiency: ${total_extra:.4f}")
        print("(conservative — assumes Sonnet input pricing)")
    print()
    print("Fixes:")
    print("  1. Update Claude Code:  npm update -g @anthropic-ai/claude-code")
    print("  2. Install cache-fix interceptor:")
    print("       github.com/cnighswonger/claude-code-cache-fix")
    print("  3. Run `burnctl version-check` to confirm your CC version")
    print("  4. Use /clear instead of --resume to start fresh sessions")
    print()


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_resume_audit(days)
