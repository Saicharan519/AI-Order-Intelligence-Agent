"""HTTP API (T-9.1; technical design 9 and 10.4).

Endpoints: POST /v1/ask, GET /v1/requests/{id}, GET /v1/sessions, GET /v1/sessions/{id},
POST /v1/sessions/{id}/scope/clear, GET /v1/catalog, GET /v1/health, GET /v1/budget.
Every endpoint except health needs the X-Access-Code header; with no ACCESS_CODE
configured the server refuses (fail closed). /v1/ask is rate limited per client IP and
globally (in-memory token buckets) and honours the LLM_ENABLED kill switch. Errors are
{"error": {"code", "message"}}, never stack traces or secrets.

Run locally:  uvicorn orderintel.api.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from collections.abc import Callable

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orderintel.agent.ask import PreviousTurn, ask, build_graph
from orderintel.agent.session import SessionStore
from orderintel.api.schemas import AskResponse
from orderintel.catalog import CatalogCache
from orderintel.config import Settings, get_settings
from orderintel.db.connect import connect_agent
from orderintel.llm.budget import LimitExceeded, PostgresLedger
from orderintel.llm.cache import ResponseCache
from orderintel.llm.client import LLMClient, LLMError, provider_config
from orderintel.redact import redact
from orderintel.trace.recorder import TraceRecorder

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
log = logging.getLogger("orderintel.api")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers


class TokenBucket:
    """capacity requests per minute, refilled continuously."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.tokens = self.capacity
        self.clock = clock
        self.updated = clock()

    def take(self) -> float:
        """Take one token; return 0 if allowed, else the seconds to wait."""
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate


class RateLimiter:
    def __init__(self, per_ip: int, total: int, clock: Callable[[], float] = time.monotonic):
        self.per_ip, self.clock = per_ip, clock
        self.total = TokenBucket(total, clock)
        self.ips: dict[str, TokenBucket] = {}
        self.lock = threading.Lock()

    def check(self, ip: str) -> None:
        with self.lock:
            bucket = self.ips.setdefault(ip, TokenBucket(self.per_ip, self.clock))
            wait = bucket.take() or self.total.take()
        if wait:
            raise ApiError(
                429,
                "rate_limited",
                "Too many requests; please wait and try again.",
                {"Retry-After": str(int(wait) + 1)},
            )


def _log(event: str, **fields) -> None:
    """Structured JSON log line, redacted."""
    log.info(redact(json.dumps({"event": event, **fields}, default=str)))


def create_app(
    settings: Settings | None = None,
    client: LLMClient | None = None,
    recorder: TraceRecorder | None = None,
    store: SessionStore | None = None,
    clock: Callable[[], float] = time.monotonic,
    trace_config: str = "api",
) -> FastAPI:
    s = settings or get_settings()
    store = store or SessionStore()
    recorder = recorder or TraceRecorder(s)
    ledger = PostgresLedger(s)
    state: dict = {"client": client, "graph": None}
    limiter = RateLimiter(s.rate_limit_per_ip_per_min, s.rate_limit_global_per_min, clock)
    catalog = CatalogCache(s)
    app = FastAPI(title="Order Intelligence Agent", version="0.1.0", docs_url=None, redoc_url=None)

    def graph():
        if state["graph"] is None:
            if state["client"] is None:
                state["client"] = LLMClient(
                    provider_config(s.llm_provider, s), ledger, ResponseCache(s.llm_cache_dir)
                )
            state["graph"] = build_graph(state["client"], store)
        return state["client"], state["graph"]

    def require_access(code: str | None) -> None:
        expected = s.access_code.get_secret_value() if s.access_code else ""
        if not expected:
            raise ApiError(503, "access_not_configured", "The server has no access code set.")
        if not code or not hmac.compare_digest(code.encode(), expected.encode()):
            raise ApiError(401, "unauthorized", "A valid access code is required.")

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError):
        return JSONResponse(
            {"error": {"code": e.code, "message": e.message}}, e.status, headers=e.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, e: RequestValidationError):
        fields = sorted({".".join(str(x) for x in err["loc"][1:]) for err in e.errors()})
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": f"Invalid field(s): {', '.join(fields)}",
                }
            },
            422,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, e: Exception):
        _log("unexpected_error", path=request.url.path, error=type(e).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Something went wrong."}}, 500
        )

    @app.get("/v1/health")
    def health():
        try:
            with connect_agent(s) as conn:
                conn.execute("SELECT 1")
            db = "ok"
        except Exception:  # noqa: BLE001  health reports, never raises
            db = "unavailable"
        return {"status": "ok", "database": db, "llm_enabled": s.llm_enabled}

    @app.post("/v1/ask", response_model=AskResponse)
    def ask_endpoint(
        body: AskRequest, request: Request, x_access_code: str | None = Header(default=None)
    ):
        require_access(x_access_code)
        limiter.check(request.client.host if request.client else "unknown")
        if not s.llm_enabled:
            raise ApiError(503, "llm_disabled", "Questions are paused by the operator.")
        client, g = graph()
        # Read before this request's own row is written, so it is the previous turn.
        last = recorder.last_turn(body.session_id, trace_config) if body.session_id else None
        previous = PreviousTurn(*last) if last else None
        try:
            with recorder.request(body.question, body.session_id, trace_config) as t:
                r = ask(
                    client,
                    body.question,
                    config_name=trace_config,
                    graph=g,
                    session_id=body.session_id,
                    store=store,
                    request_id=t.id,
                    previous=previous,
                )
                recorder.finish(t, r)
        except LimitExceeded as e:
            _log("budget_blocked", code=e.code)
            raise ApiError(
                503, "budget_exhausted", "The spending limit is reached; no model call was made."
            ) from None
        except LLMError as e:
            _log("provider_error", code=e.code)
            raise ApiError(502, "provider_error", "The language model is unavailable.") from None
        _log(
            "ask",
            request_id=r.request_id,
            route=r.route,
            status=r.status,
            latency_ms=r.usage.latency_ms,
            cost_usd=r.usage.cost_usd,
        )
        return r

    @app.get("/v1/requests/{request_id}")
    def get_request(request_id: str, x_access_code: str | None = Header(default=None)):
        require_access(x_access_code)
        found = recorder.get(request_id)
        if found is None:
            raise ApiError(404, "not_found", "No such request.")
        return found

    @app.get("/v1/sessions")
    def list_sessions(x_access_code: str | None = Header(default=None)):
        """Past conversations (newest first), read from the stored request traces."""
        require_access(x_access_code)
        return {"sessions": recorder.sessions(trace_config)}

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, x_access_code: str | None = Header(default=None)):
        """One conversation's questions and stored answers, to reopen it without any model
        call. `scope_active` says whether follow-ups still inherit its investigation scope
        (the scope is kept in memory for two hours and lost when the API restarts)."""
        require_access(x_access_code)
        if not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise ApiError(422, "invalid_request", "Invalid session id.")
        turns = recorder.session(session_id, trace_config)
        if not turns:
            raise ApiError(404, "not_found", "No such conversation.")
        return {
            "session_id": session_id,
            "scope_active": store.get(session_id) is not None,
            "turns": turns,
        }

    @app.post("/v1/sessions/{session_id}/scope/clear")
    def clear_scope(session_id: str, x_access_code: str | None = Header(default=None)):
        require_access(x_access_code)
        if not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise ApiError(422, "invalid_request", "Invalid session id.")
        return {"session_id": session_id, "cleared": store.clear(session_id)}

    @app.get("/v1/catalog")
    def get_catalog(x_access_code: str | None = Header(default=None)):
        """What the data contains and what can be asked: fixed read-only queries and the
        glossary, no model call (the "Explore the data" guide)."""
        require_access(x_access_code)
        return catalog.get()

    @app.get("/v1/budget")
    def budget(x_access_code: str | None = Header(default=None)):
        require_access(x_access_code)
        total, today = ledger.totals()
        return {
            "total_usd": round(total, 6),
            "today_usd": round(today, 6),
            "total_cap_usd": s.llm_total_cap_usd,
            "daily_cap_usd": s.llm_daily_cap_usd,
            "remaining_total_usd": round(max(s.llm_total_cap_usd - total, 0), 6),
            "remaining_today_usd": round(max(s.llm_daily_cap_usd - today, 0), 6),
            "llm_enabled": s.llm_enabled,
        }

    return app


def __getattr__(name: str):
    """`app` is created on first access, so importing this module needs no settings."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
