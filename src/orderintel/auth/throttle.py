"""Sign-in throttling: after too many failed attempts for one email (or from one client),
further attempts are refused for a while, even with the right password, so passwords cannot
be guessed quickly. In memory, like the API's rate limits; resets when the API restarts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_CLIENT = 20
WINDOW_S = 15 * 60


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = self._clock()
        kept = [t for t in self._fails.get(key, []) if now - t < WINDOW_S]
        self._fails[key] = kept
        return kept

    def blocked(self, email: str, client: str) -> bool:
        with self._lock:
            return (
                len(self._recent(f"e:{email}")) >= MAX_FAILURES_PER_EMAIL
                or len(self._recent(f"c:{client}")) >= MAX_FAILURES_PER_CLIENT
            )

    def failed(self, email: str, client: str) -> None:
        with self._lock:
            now = self._clock()
            for key in (f"e:{email}", f"c:{client}"):
                self._recent(key).append(now)

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._fails.pop(f"e:{email}", None)
