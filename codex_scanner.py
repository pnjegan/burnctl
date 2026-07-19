"""codex_scanner.py — parses Codex CLI rollout JSONL into the same
`sessions` table burn_rate.py / scanner.py already read, via the existing
insert_session() call. No new table, no parallel pipeline.

Schema note: uses the SAME insert_session(conn, row) as scanner.py.
`account` is hardcoded "codex" so burn_rate.py's queries (which don't
filter by account today) naturally include Codex sessions once these rows
land — verify that's actually what you want before running at scale;
if you want Claude/Codex kept separate, filter by account downstream
instead of splitting the table.

Refuses to insert a session if its model has no real entry in
MODEL_PRICING — a silent cost_usd=0 for an unpriced model is precisely
the phantom-cost bug already found in TD-48. Better a skipped row you
know about than a wrong number you don't.
"""

import json
import os
import glob
from datetime import datetime, timezone

from config import MODEL_PRICING
from db import get_conn, insert_session


def normalize_codex_model(model_str):
    """Codex model strings pass through as-is (e.g. 'gpt-5.6-sol') —
    unlike normalize_model() in scanner.py, we do NOT bucket unknowns
    into a Claude default. An unrecognized Codex model should fail
    loudly (skip + warn), never silently mispriced as Sonnet.
    """
    return (model_str or "unknown").lower()


def compute_codex_cost(model, input_tokens, cached_tokens, output_tokens):
    """Returns (cost_usd, priced_ok). priced_ok=False means MODEL_PRICING
    has no real entry for this model — caller must skip the row, not
    write cost_usd=0 as if it were a real observed number.
    """
    if model not in MODEL_PRICING:
        return 0.0, False
    pricing = MODEL_PRICING[model]
    cost = 0.0
    cost += (input_tokens / 1_000_000) * pricing["input"]
    cost += (output_tokens / 1_000_000) * pricing["output"]
    if "cache_read" in pricing:
        cost += (cached_tokens / 1_000_000) * pricing["cache_read"]
    return round(cost, 8), True


def parse_codex_rollout(filepath):
    """Parse one rollout-*.jsonl file into a row dict for insert_session(),
    or None if the file has no usable token_count event (e.g. a session
    that errored before any turn completed).
    """
    session_id = None
    cwd = None
    model = None
    session_ts = None
    last_token_usage = None
    used_percent = None

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = rec.get("type")
            payload = rec.get("payload", {})

            if rtype == "session_meta":
                session_id = payload.get("session_id")
                cwd = payload.get("cwd")
                ts = payload.get("timestamp") or rec.get("timestamp")
                if ts:
                    try:
                        clean = ts.replace("Z", "+00:00")
                        session_ts = int(
                            datetime.fromisoformat(clean).timestamp()
                        )
                    except ValueError:
                        session_ts = None

            elif rtype == "turn_context":
                model = payload.get("model") or model

            elif rtype == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info", {})
                last_token_usage = info.get("total_token_usage")
                rl = payload.get("rate_limits") or {}
                primary = rl.get("primary") or {}
                used_percent = primary.get("used_percent")

    if not session_id or not last_token_usage:
        return None

    model_norm = normalize_codex_model(model)
    input_t = last_token_usage.get("input_tokens", 0)
    cached_t = last_token_usage.get("cached_input_tokens", 0)
    output_t = last_token_usage.get("output_tokens", 0)

    cost, priced_ok = compute_codex_cost(model_norm, input_t, cached_t, output_t)
    if not priced_ok:
        print(
            f"SKIP {filepath}: no MODEL_PRICING entry for '{model_norm}' — "
            f"add real pricing before this session's cost can be trusted. "
            f"used_percent from Codex's own rate_limits: {used_percent}"
        )
        return None

    return {
        "session_id": f"codex-{session_id}",
        "timestamp": session_ts or int(os.path.getmtime(filepath)),
        "project": cwd or "unknown",
        "account": "codex",
        "model": model_norm,
        "input_tokens": input_t,
        "output_tokens": output_t,
        "cache_read_tokens": cached_t,
        "cache_creation_tokens": 0,  # Codex doesn't distinguish cache-write; verify if this matters for your cost math
        "cost_usd": cost,
        "source_path": filepath,
    }


def scan_codex_sessions(sessions_root=None):
    """Walk ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl and insert rows
    via the existing insert_session() pipeline. Returns (inserted, skipped).
    """
    sessions_root = sessions_root or os.path.expanduser("~/.codex/sessions")
    pattern = os.path.join(sessions_root, "**", "rollout-*.jsonl")
    files = glob.glob(pattern, recursive=True)

    conn = get_conn()
    if conn is None:
        print(
            "No burnctl DB found (get_conn() returned None). "
            "Run `burnctl scan` first to create it, same as burn_rate.py "
            "requires — this adapter doesn't create the DB itself."
        )
        return 0, 0

    inserted, skipped = 0, 0
    for filepath in files:
        row = parse_codex_rollout(filepath)
        if row is None:
            skipped += 1
            continue
        insert_session(conn, row)
        inserted += 1
    conn.commit()
    return inserted, skipped


if __name__ == "__main__":
    ins, skip = scan_codex_sessions()
    print(f"Codex scan: {ins} inserted, {skip} skipped")
    if skip:
        print(
            "Skipped sessions are almost certainly unpriced-model rows — "
            "check MODEL_PRICING in config.py before re-running."
        )
