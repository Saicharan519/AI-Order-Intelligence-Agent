"""Secret redaction for traces and logs (technical design 10.1; NFR-06).

Every configured secret value is replaced by [REDACTED:<setting name>] before text is
written to a trace or a log. Values are compared in memory only and never printed.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import SecretStr

from orderintel.config import Settings, get_settings

MIN_SECRET_LENGTH = 8  # shorter values would redact ordinary words


def secret_values(settings: Settings | None = None) -> dict[str, str]:
    """Setting name -> value of every configured secret of at least MIN_SECRET_LENGTH."""
    s = settings or get_settings()
    out = {}
    for name in type(s).model_fields:
        v = getattr(s, name)
        if isinstance(v, SecretStr) and len(v.get_secret_value()) >= MIN_SECRET_LENGTH:
            out[name] = v.get_secret_value()
    return out


def redact(text: str | None, settings: Settings | None = None) -> str | None:
    if text is None:
        return None
    for name, value in secret_values(settings).items():
        if value in text:
            text = text.replace(value, f"[REDACTED:{name}]")
    return text


def redact_json(obj: Any, settings: Settings | None = None) -> str:
    """JSON-encode obj, then redact (catches secrets anywhere in a nested structure)."""
    return redact(json.dumps(obj, ensure_ascii=False, default=str), settings) or "null"
