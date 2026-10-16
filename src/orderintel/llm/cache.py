"""Response cache (technical design 10.3): unchanged re-runs cost nothing.

Key = SHA-256 of (model, messages, request parameters, prompt version). Stored as JSON in
the git-ignored eval/cache/llm/ directory. Cached responses are not re-billed and are not
written to the spend ledger.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cache_key(model: str, messages: list[dict], params: dict, prompt_version: str) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "params": params, "prompt": prompt_version},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, value: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
