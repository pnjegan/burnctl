"""burnctl pricing — the single source of truth for token rates.

WHY THIS FILE EXISTS. Until 2026-11-11 there were two price tables measuring the
same corpus (`~/.claude/projects/**/*.jsonl`) and they disagreed:

  1. `config.py:MODEL_PRICING` — three family keys, no source, no date.
  2. narthex-agent-eval `scripts/agent-eval/prices.mjs` — version keys, with a
     cited source and a date, plus one multiplier verified against a real bill.

A rate table without a date is not a fact, it is a memory. This file carries
both: every rate below is traceable to SOURCE, and SOURCE names when it was read.
Re-read it from the Pricing row of the bundled `claude-api` skill, or from
platform.claude.com, before trusting any figure derived from it.

NOTHING IN THIS FILE IS WIRED INTO THE SCANNER YET. See LEGACY_FAMILY_PRICING for
what burnctl actually charges today and by how much it is wrong. Repricing is a
data decision, not a patch: `cost_usd` is computed at scan time
(`scanner.py:98` -> `scanner.py:205`) and persisted, so correcting the rates
changes new rows only and leaves a visible discontinuity in the series.
"""

SOURCE = (
    "Anthropic first-party API list rates, per million tokens. Read 2026-11-11 "
    "from the Claude Code bundled `claude-api` skill, 'Current Models' table, "
    "which states its own cache date as 2026-10-06. Cache multipliers from the "
    "same skill: cache read ~0.10x input, cache write (5-minute) ~1.25x input. "
    "The 1-hour cache-write factor of 2.00x and its live-bill verification "
    "(19,848 1h-cache tokens on haiku = $0.039696 of a $0.04004 bill, "
    "2026-09-27) come from narthex-agent-eval scripts/agent-eval/prices.mjs, "
    "which is the better-sourced of the two tables this file reconciles."
)

SOURCE_DATE = "2026-11-11"
UPSTREAM_CACHE_DATE = "2026-10-06"

# Per million tokens, USD. Keys are exact model IDs — never date-suffixed.
PRICES = {
    "claude-fable-5-1":  {"input": 10.00, "output": 50.00},
    "claude-mythos-5-1": {"input": 10.00, "output": 50.00},
    "claude-fable-5":    {"input": 10.00, "output": 50.00},
    "claude-opus-5-5":   {"input": 4.00,  "output": 20.00},
    "claude-opus-5":     {"input": 5.00,  "output": 25.00},
    "claude-opus-4-8":   {"input": 5.00,  "output": 25.00},
    "claude-opus-4-7":   {"input": 5.00,  "output": 25.00},
    "claude-opus-4-6":   {"input": 5.00,  "output": 25.00},
    "claude-sonnet-5-5": {"input": 2.00,  "output": 10.00},
    "claude-sonnet-5":   {"input": 2.00,  "output": 10.00},
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-haiku-5-5":  {"input": 0.10,  "output": 0.50},
    "claude-haiku-4-5":  {"input": 1.00,  "output": 5.00},
}

# Cache-read rates that are published per model rather than as a multiple of
# input. These WIN over CACHE_MULT, and they are the reason a flat multiplier is
# not good enough: 0.10x of Opus 5.5's $4.00 input would be $0.40, but the
# published cache-read rate is $0.20 — a flat 0.10x overstates it by 2x.
# narthex's prices.mjs applies the flat factor and inherits exactly that error.
CACHE_READ = {
    "claude-opus-5-5":   0.20,
    "claude-sonnet-5-5": 0.20,
    "claude-fable-5-1":  0.25,
}

# Fallback multipliers, applied to a model's INPUT rate when CACHE_READ has no
# entry for it. cache_1h is the factor narthex verified against a live bill.
CACHE_MULT = {"cache_read": 0.10, "cache_5m": 1.25, "cache_1h": 2.00}

# Haiku 5.5 is priced in two bands by prompt size. Rates above are the <=100K
# band; beyond it the rates are these. Nothing in burnctl bands by prompt size
# yet, so this is recorded, not applied.
PROMPT_BAND_OVERRIDES = {
    "claude-haiku-5-5": {
        "over_tokens": 100_000,
        "input": 0.50,
        "output": 2.50,
    },
}

# ─── What burnctl actually charges today ──────────────────────────────────
#
# `config.py:MODEL_PRICING`, verbatim. `scanner.py:75 normalize_model()` maps
# every model string onto one of these three keys and discards the version, so
# an Opus 5.5 session ($4/$20) and an Opus 5 session ($5/$25) are both billed at
# the single "claude-opus" rate below. Unrecognised models — Fable included, at a
# real $10/$50 — fall through to "claude-sonnet".
#
# These look like Claude 3-era rates. They are kept here, unchanged, so the drift
# is measurable instead of merely asserted. Do not "fix" this dict: it documents
# the live behaviour. Correct rates live in PRICES above.
LEGACY_FAMILY_PRICING = {
    "claude-opus":   {"input": 15.00, "output": 75.00, "cache_read": 1.50,  "cache_write": 18.75},
    "claude-sonnet": {"input": 3.00,  "output": 15.00, "cache_read": 0.30,  "cache_write": 3.75},
    "claude-haiku":  {"input": 0.25,  "output": 1.25,  "cache_read": 0.025, "cache_write": 0.30},
}

# Which current model each legacy family key is most likely standing in for, so
# the drift factor below compares like with like. Chosen as the newest model in
# that family, since that is what recent sessions actually ran.
LEGACY_FAMILY_ASSUMED_AS = {
    "claude-opus":   "claude-opus-5-5",
    "claude-sonnet": "claude-sonnet-5-5",
    "claude-haiku":  "claude-haiku-5-5",
}


def normalise_model(model):
    """Exact model ID for a raw model string, or None if it is not priced.

    Strips the `[1m]` cost-state suffix and a trailing `-YYYYMMDD` snapshot
    date, matching narthex's normaliseModel so the two agree on keys. Returns
    None rather than guessing — an unpriced model must never silently cost 0,
    and must never silently be charged as something else.
    """
    m = str(model or "")
    if m.endswith("[1m]"):
        m = m[:-4]
    parts = m.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        m = parts[0]
    return m if m in PRICES else None


def cache_read_rate(model_id):
    """Published cache-read rate for an exact model ID, in USD per million."""
    if model_id in CACHE_READ:
        return CACHE_READ[model_id]
    return PRICES[model_id]["input"] * CACHE_MULT["cache_read"]


def cache_write_rate(model_id, ttl="5m"):
    """Cache-write rate for an exact model ID, in USD per million."""
    key = "cache_1h" if ttl == "1h" else "cache_5m"
    return PRICES[model_id]["input"] * CACHE_MULT[key]


def cost_of(model, tokens):
    """Cost in USD for one message, or None if the model is not priced.

    `tokens` keys: input, output, cache_read, cache_5m, cache_1h — all optional.
    Returns None for an unknown model so the caller must decide what to do;
    a silent 0.0 is how an unpriced model disappears from a cost report.
    """
    model_id = normalise_model(model)
    if model_id is None:
        return None
    p = PRICES[model_id]
    per = 1_000_000.0
    total = 0.0
    total += tokens.get("input", 0) / per * p["input"]
    total += tokens.get("output", 0) / per * p["output"]
    total += tokens.get("cache_read", 0) / per * cache_read_rate(model_id)
    total += tokens.get("cache_5m", 0) / per * cache_write_rate(model_id, "5m")
    total += tokens.get("cache_1h", 0) / per * cache_write_rate(model_id, "1h")
    return total


def legacy_drift():
    """How wrong the live family rates are, per family.

    Returns {family: {field: factor}} where factor > 1 means burnctl currently
    charges MORE than the published rate for the model it is standing in for.
    """
    out = {}
    for family, legacy in LEGACY_FAMILY_PRICING.items():
        model_id = LEGACY_FAMILY_ASSUMED_AS[family]
        current = {
            "input": PRICES[model_id]["input"],
            "output": PRICES[model_id]["output"],
            "cache_read": cache_read_rate(model_id),
            "cache_write": cache_write_rate(model_id, "5m"),
        }
        out[family] = {
            "assumed_as": model_id,
            "factors": {
                field: (legacy[field] / current[field] if current[field] else None)
                for field in ("input", "output", "cache_read", "cache_write")
            },
        }
    return out


if __name__ == "__main__":
    print("burnctl pricing — source dated %s (upstream table cached %s)"
          % (SOURCE_DATE, UPSTREAM_CACHE_DATE))
    print()
    print("Drift of the live family rates vs the published rates:")
    for family, info in sorted(legacy_drift().items()):
        print("  %-14s standing in for %s" % (family, info["assumed_as"]))
        for field, factor in info["factors"].items():
            if factor is None:
                print("      %-12s n/a" % field)
            else:
                print("      %-12s %.2fx" % (field, factor))
