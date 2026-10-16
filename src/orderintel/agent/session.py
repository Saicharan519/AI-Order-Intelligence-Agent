"""Session scope for follow-up questions (FR-12; technical design 2.5).

An investigation sets {period, state, population, source_request_id}; later questions in
the same session inherit it until it expires (2 hours) or is cleared. Single-user,
in-memory, not persisted across restarts. A deterministic scope-presence check verifies
that follow-up SQL mentions each inherited filter value (a heuristic, reported as a warning).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass

TTL_SECONDS = 2 * 60 * 60


@dataclass(frozen=True)
class SessionScope:
    period: str  # YYYY-MM
    state: str | None
    population: str  # delivered orders | reviewed orders
    source_request_id: str
    created: float

    @property
    def month_start(self) -> dt.date:
        return dt.date.fromisoformat(self.period + "-01")

    def describe(self) -> str:
        parts = [f"period {self.period} (orders purchased in that month)"]
        if self.state:
            parts.append(f"customer state {self.state}")
        parts.append(f"population: {self.population}")
        return "; ".join(parts)

    def context_for_sql(self) -> str:
        return (
            "Active scope from the previous investigation (apply it unless the question "
            "clearly asks for something else): " + self.describe() + "."
        )


class SessionStore:
    def __init__(self, ttl: int = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._data: dict[str, SessionScope] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str | None) -> SessionScope | None:
        if not session_id:
            return None
        with self._lock:
            s = self._data.get(session_id)
            if s and time.time() - s.created > self._ttl:
                del self._data[session_id]
                return None
            return s

    def set(self, session_id: str | None, scope: SessionScope) -> None:
        if session_id:
            with self._lock:
                self._data[session_id] = scope

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._data.pop(session_id, None) is not None


STORE = SessionStore()


def scope_presence_warnings(sql: str, scope: SessionScope) -> list[str]:
    """Heuristic: the follow-up SQL should mention the inherited month and state."""
    missing = []
    if scope.period not in sql and scope.month_start.isoformat() not in sql:
        missing.append(f"period {scope.period}")
    if scope.state and f"'{scope.state}'" not in sql:
        missing.append(f"state {scope.state}")
    if not missing:
        return []
    return [
        "This follow-up may not apply the inherited scope ("
        + ", ".join(missing)
        + "); check the SQL in the evidence panel."
    ]
