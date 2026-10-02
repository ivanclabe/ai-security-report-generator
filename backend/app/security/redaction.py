"""Strips secrets from anything that is about to be logged, audited or shown.

Applied to every audit/observability context before it is written: a key whose
name looks like a credential is replaced, long strings are truncated, and
deep or huge structures are cut -- so a careless `context={...}` at a call site
cannot put a password, token or a whole payload into Supabase.
"""
import re
from typing import Any

REDACTED = "[oculto]"
_SENSITIVE_KEY = re.compile(
    r"pass(word)?|pwd|secret|token|authorization|cookie|api[_-]?key|credential|ciphertext|session", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b")
_URL_USERINFO = re.compile(r"(?i)\b(https?://)[^/\s:@]+:[^/\s@]+@")
_MAX_STRING = 500
_MAX_ITEMS = 50
_MAX_DEPTH = 4


def redact_text(value: str, limit: int = _MAX_STRING) -> str:
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    text = _JWT.sub(REDACTED, text)
    text = _URL_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def redact(value: Any, _depth: int = 0) -> Any:
    if _depth > _MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        out = {}
        for i, (key, item) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["…"] = f"{len(value) - _MAX_ITEMS} más"
                break
            key = str(key)
            # a flag such as {"password_changed": true} says nothing secret -- keep it
            sensitive = _SENSITIVE_KEY.search(key) and not isinstance(item, bool) and item is not None
            out[key] = REDACTED if sensitive else redact(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = [redact(item, _depth + 1) for item in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            items.append(f"… {len(value) - _MAX_ITEMS} más")
        return items
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))
