"""Spend ledger and budget/quota guard (FR-15, FR-16; technical design 10.3).

Every real LLM call is recorded in trace.requests (written by oi_trace), so the budget is
enforced globally: evaluation runs, calibration, and the product share one ledger. The
guard runs BEFORE each call with a worst-case cost (peak price, no cache, full
max_tokens); a breach raises and no request is sent.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from orderintel.llm.pricing import Usage
from orderintel.redact import redact

# The user request being served, if any: LLM calls made while it is set are linked to it
# (trace.requests.parent_id). Set by orderintel.trace.recorder.
CURRENT_REQUEST: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_request", default=None
)


class LimitExceeded(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code  # budget_total | budget_daily | quota_rpm | quota_rpd
        self.message = message


@dataclass
class LedgerEntry:
    config_name: str
    model: str
    status: str  # ok | error
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_ms: int = 0
    question: str | None = None
    error: str | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


class Ledger(Protocol):
    def totals(self) -> tuple[float, float]: ...  # (total_usd, today_usd UTC)
    def count_requests(self, model: str, since: dt.datetime) -> int: ...
    def record(self, entry: LedgerEntry) -> None: ...


class MemoryLedger:
    """In-process ledger for tests."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def totals(self) -> tuple[float, float]:
        today = dt.datetime.now(dt.UTC).date()
        total = sum(e.cost_usd for e in self.entries)
        return total, sum(e.cost_usd for e in self.entries if e.created_at.date() == today)

    def count_requests(self, model: str, since: dt.datetime) -> int:
        return sum(1 for e in self.entries if e.model == model and e.created_at >= since)

    def record(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)


class PostgresLedger:
    """Ledger in trace.requests, via the oi_trace role."""

    def __init__(self, settings=None) -> None:
        from orderintel.db.connect import connect_trace

        self._connect = lambda: connect_trace(settings)

    def totals(self) -> tuple[float, float]:
        with self._connect() as conn:
            total, today, _ = conn.execute(
                "SELECT total_usd, today_usd, requests FROM trace.spend"
            ).fetchone()
        return float(total), float(today)

    def count_requests(self, model: str, since: dt.datetime) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT count(*) FROM trace.requests WHERE model = %s AND created_at >= %s",
                (model, since),
            ).fetchone()[0]

    def record(self, entry: LedgerEntry) -> None:
        u = entry.usage
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace.requests (id, created_at, config_name, model, question, status,
                    latency_ms, tokens_in, tokens_cache_hit, tokens_out, cost_usd, response, error,
                    kind, parent_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'llm_call', %s)
                """,
                (
                    uuid.uuid4(),
                    entry.created_at,
                    entry.config_name,
                    entry.model,
                    redact(entry.question),
                    entry.status,
                    entry.latency_ms,
                    u.prompt_tokens,
                    u.cache_hit_tokens,
                    u.completion_tokens,
                    entry.cost_usd,
                    json.dumps(
                        {
                            "reasoning_tokens": u.reasoning_tokens,
                            "cache_miss_tokens": u.cache_miss_tokens,
                        }
                    ),
                    redact(entry.error),
                    CURRENT_REQUEST.get(),
                ),
            )


@dataclass(frozen=True)
class Limits:
    total_cap_usd: float | None = None
    daily_cap_usd: float | None = None
    max_rpm: int | None = None
    max_rpd: int | None = None


def check_limits(ledger: Ledger, model: str, worst_case_usd: float, limits: Limits) -> None:
    if limits.total_cap_usd is not None or limits.daily_cap_usd is not None:
        total, today = ledger.totals()
        if limits.total_cap_usd is not None and total + worst_case_usd > limits.total_cap_usd:
            raise LimitExceeded(
                "budget_total",
                f"spent ${total:.4f}; this call could cost up to ${worst_case_usd:.4f}, "
                f"which would exceed the total cap ${limits.total_cap_usd:.2f}",
            )
        if limits.daily_cap_usd is not None and today + worst_case_usd > limits.daily_cap_usd:
            raise LimitExceeded(
                "budget_daily",
                f"spent ${today:.4f} today (UTC); the daily cap is ${limits.daily_cap_usd:.2f}",
            )
    now = dt.datetime.now(dt.UTC)
    if limits.max_rpm is not None:
        n = ledger.count_requests(model, now - dt.timedelta(minutes=1))
        if n + 1 > limits.max_rpm:
            raise LimitExceeded(
                "quota_rpm", f"{n} requests in the last minute; cap {limits.max_rpm}"
            )
    if limits.max_rpd is not None:
        n = ledger.count_requests(model, now - dt.timedelta(days=1))
        if n + 1 > limits.max_rpd:
            raise LimitExceeded("quota_rpd", f"{n} requests in the last 24 h; cap {limits.max_rpd}")
