"""Redaction helpers for safe logging. Tokens/emails must never hit logs raw.

Used by every v5.0 code path that logs near a credential or PII. Pure
stdlib, no deps. See standing rule: secureLog for anything touching
tokens or emails.
"""


def redact_token(s):
    """Mask all but first 4 + last 4 chars. Tokens <=8 chars are fully
    masked (revealing 8 of <=8 chars would leak the whole secret).
    None/empty -> "" (never crash)."""
    if not s:
        return ""
    s = str(s)
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}{'*' * (len(s) - 8)}{s[-4:]}"


def redact_email(s):
    """Mask the local part, keep the domain (e.g. a***e@example.com).
    Local parts <=2 chars are fully masked. No '@' -> fully masked
    (can't trust it's safe to reveal). None/empty -> "" (never crash)."""
    if not s:
        return ""
    s = str(s)
    if "@" not in s:
        return "*" * len(s)
    local, _, domain = s.partition("@")
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{masked}@{domain}"


def redact_dict(d, keys):
    """Return a shallow copy of d with each key in `keys` redacted.
    Values containing '@' are treated as emails, otherwise as tokens.
    Useful for logging a request body without leaking secrets. Non-dict
    input is returned unchanged; missing/None keys are skipped."""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    for k in keys:
        if k not in out or out[k] is None:
            continue
        val = str(out[k])
        out[k] = redact_email(val) if "@" in val else redact_token(val)
    return out
