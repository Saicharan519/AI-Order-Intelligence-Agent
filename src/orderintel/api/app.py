"""HTTP API (T-9.1; technical design 9 and 10.4).

Accounts (invite-only): POST /v1/auth/login, /v1/auth/logout, /v1/auth/signup,
GET /v1/auth/me, GET /v1/auth/invites/{code}; admin: GET /v1/admin/users,
POST /v1/admin/users/{id}/disable|enable, GET|POST /v1/admin/invites,
POST /v1/admin/invites/{id}/revoke.
Questions and history: POST /v1/ask, GET /v1/requests/{id}, GET /v1/sessions,
GET /v1/sessions/{id}, POST /v1/sessions/{id}/scope/clear, GET /v1/catalog, GET /v1/budget,
and GET /v1/health (open).

Who is calling: a signed-in user (Authorization: Bearer <session token>; the web app keeps
the token in an httpOnly cookie on its own server) or the operator key (X-Access-Code, for
scripts, tests and the Streamlit fallback; with no ACCESS_CODE set it is refused, fail
closed). History, traces and per-user spend are scoped to the caller; one user never sees
another's conversations. /v1/ask is rate limited per user (or per client IP for the operator
key) and globally, applies each user's daily budget, and honours the LLM_ENABLED kill
switch. Errors are {"error": {"code", "message"}}, never stack traces or secrets.

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
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orderintel.agent.ask import PreviousTurn, ask, build_graph
from orderintel.agent.session import SessionStore
from orderintel.api.schemas import AskResponse
from orderintel.auth.crypto import normalise_email
from orderintel.auth.store import AccountError, AccountStore, User
from orderintel.auth.throttle import LoginThrottle
from orderintel.catalog import CatalogCache
from orderintel.config import Settings, get_settings
from orderintel.db.connect import connect_agent
from orderintel.llm.budget import LimitExceeded, PostgresLedger
from orderintel.llm.cache import ResponseCache
from orderintel.llm.client import LLMClient, LLMError, provider_config
from orderintel.redact import redact
from orderintel.trace.recorder import TraceRecorder

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
INVITE_PATTERN = r"^[A-Za-z0-9_-]{20,100}$"
UUID_PATTERN = r"^[0-9a-fA-F-]{36}$"
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


@dataclass(frozen=True)
class Identity:
    """Who is calling: a signed-in user, or the operator key (scripts, tests, fallback UI)."""

    kind: str  # user | operator
    user: User | None = None

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def is_admin(self) -> bool:
        return self.kind == "operator" or (self.user is not None and self.user.role == "admin")

    @property
    def limit_key(self) -> str | None:
        return f"user:{self.user.id}" if self.user else None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    invite: str = Field(pattern=INVITE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


ACCOUNT_ERROR_STATUS = {"email_taken": 409, "not_found": 404, "not_allowed": 403}


def create_app(
    settings: Settings | None = None,
    client: LLMClient | None = None,
    recorder: TraceRecorder | None = None,
    store: SessionStore | None = None,
    clock: Callable[[], float] = time.monotonic,
    trace_config: str = "api",
    accounts: AccountStore | None = None,
) -> FastAPI:
    s = settings or get_settings()
    store = store or SessionStore()
    recorder = recorder or TraceRecorder(s)
    accounts = accounts or AccountStore(s)
    ledger = PostgresLedger(s)
    state: dict = {"client": client, "graph": None}
    limiter = RateLimiter(s.rate_limit_per_ip_per_min, s.rate_limit_global_per_min, clock)
    throttle = LoginThrottle(clock)
    catalog = CatalogCache(s)
    app = FastAPI(title="Order Intelligence Agent", version="0.2.0", docs_url=None, redoc_url=None)

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

    def identify(request: Request) -> Identity:
        """A signed-in user (Authorization: Bearer <session token>) or the operator key."""
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            user = accounts.user_for_token(auth[7:].strip())
            if user is None:
                raise ApiError(401, "unauthorized", "Please sign in again.")
            return Identity("user", user)
        require_access(request.headers.get("x-access-code"))
        return Identity("operator")

    def require_admin(who: Identity) -> User:
        if who.user is None or who.user.role != "admin":
            raise ApiError(403, "forbidden", "Only an admin can do that.")
        return who.user

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError):
        return JSONResponse(
            {"error": {"code": e.code, "message": e.message}}, e.status, headers=e.headers
        )

    @app.exception_handler(AccountError)
    async def _account_error(request: Request, e: AccountError):
        return JSONResponse(
            {"error": {"code": e.code, "message": e.message}},
            ACCOUNT_ERROR_STATUS.get(e.code, 400),
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

    # ---------------- accounts ----------------
    @app.post("/v1/auth/login")
    def login(body: LoginRequest, request: Request):
        """Email and password -> a session token. The same answer for an unknown email and a
        wrong password; repeated failures are refused for a while."""
        email = normalise_email(body.email) or body.email.strip().lower()
        ip = client_ip(request)
        if throttle.blocked(email, ip):
            raise ApiError(
                429,
                "too_many_attempts",
                "Too many failed sign-in attempts. Please wait 15 minutes and try again.",
            )
        user = accounts.authenticate(email, body.password)
        if user is None:
            throttle.failed(email, ip)
            _log("login_failed")
            raise ApiError(401, "invalid_credentials", "Email or password is wrong.")
        throttle.succeeded(email)
        _log("login", user_id=user.id)
        return {"token": accounts.create_session(user), "user": user.public()}

    @app.post("/v1/auth/logout")
    def logout(request: Request):
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            accounts.end_session(auth[7:].strip())
        return {"ok": True}

    @app.get("/v1/auth/me")
    def me(request: Request):
        who = identify(request)
        if who.user is None:
            return {"id": None, "email": None, "name": "Operator", "role": "operator"}
        return who.user.public()

    @app.get("/v1/auth/invites/{code}")
    def invite_info(code: str, request: Request):
        """For the sign-up page: which email an invite is for, if it is still valid."""
        if not re.fullmatch(INVITE_PATTERN, code):
            raise ApiError(404, "invalid_invite", "This invite link is not valid.")
        ip = client_ip(request)
        if throttle.blocked("", ip):
            raise ApiError(429, "too_many_attempts", "Too many attempts. Please wait.")
        found = accounts.invite_for_code(code)
        if found is None:
            throttle.failed("", ip)
            raise ApiError(
                404, "invalid_invite", "This invite link is not valid: it may be used or expired."
            )
        return {"email": found["email"], "expires_at": found["expires_at"]}

    @app.post("/v1/auth/signup")
    def signup(body: SignupRequest):
        user = accounts.accept_invite(body.invite, body.name, body.password)
        _log("signup", user_id=user.id)
        return {"token": accounts.create_session(user), "user": user.public()}

    # ---------------- admin ----------------
    @app.get("/v1/admin/users")
    def admin_users(request: Request):
        require_admin(identify(request))
        return {"users": accounts.list_users(), "user_daily_cap_usd": s.user_daily_cap_usd}

    @app.post("/v1/admin/users/{user_id}/{action}")
    def admin_user_action(user_id: str, action: str, request: Request):
        admin = require_admin(identify(request))
        if action not in ("disable", "enable") or not re.fullmatch(UUID_PATTERN, user_id):
            raise ApiError(404, "not_found", "No such action.")
        user = accounts.set_disabled(user_id, action == "disable", admin)
        _log("user_" + action, user_id=user.id, by=admin.id)
        return {"id": user.id, "disabled": user.disabled}

    @app.get("/v1/admin/invites")
    def admin_invites(request: Request):
        require_admin(identify(request))
        return {"invites": accounts.list_invites()}

    @app.post("/v1/admin/invites")
    def admin_create_invite(body: InviteRequest, request: Request):
        """A one-time invite for an email. The code is in this response only."""
        admin = require_admin(identify(request))
        code, invite = accounts.create_invite(body.email, admin)
        _log("invite_created", invite_id=invite["id"], by=admin.id)
        return {"code": code, "invite": invite}

    @app.post("/v1/admin/invites/{invite_id}/revoke")
    def admin_revoke_invite(invite_id: str, request: Request):
        require_admin(identify(request))
        if not re.fullmatch(UUID_PATTERN, invite_id):
            raise ApiError(404, "not_found", "No such invite.")
        return {"revoked": accounts.revoke_invite(invite_id)}

    # ---------------- questions and history ----------------
    @app.post("/v1/ask", response_model=AskResponse)
    def ask_endpoint(body: AskRequest, request: Request):
        who = identify(request)
        limiter.check(who.limit_key or client_ip(request))
        if not s.llm_enabled:
            raise ApiError(503, "llm_disabled", "Questions are paused by the operator.")
        if who.user is not None and who.user.role == "user":
            if accounts.spend_today(who.user.id) >= s.user_daily_cap_usd:
                raise ApiError(
                    429,
                    "user_budget_exhausted",
                    "You have used today's question budget. It resets at midnight UTC.",
                )
        client, g = graph()
        # Read before this request's own row is written, so it is the previous turn.
        last = (
            recorder.last_turn(body.session_id, trace_config, who.user_id)
            if body.session_id
            else None
        )
        previous = PreviousTurn(*last) if last else None
        try:
            with recorder.request(body.question, body.session_id, trace_config, who.user_id) as t:
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
            user_id=who.user_id,
            route=r.route,
            status=r.status,
            latency_ms=r.usage.latency_ms,
            cost_usd=r.usage.cost_usd,
        )
        return r

    @app.get("/v1/requests/{request_id}")
    def get_request(request_id: str, request: Request):
        who = identify(request)
        found = recorder.get(request_id)
        # Someone else's request looks exactly like a missing one.
        if found is None or (not who.is_admin and found.get("user_id") != who.user_id):
            raise ApiError(404, "not_found", "No such request.")
        return found

    @app.get("/v1/sessions")
    def list_sessions(request: Request):
        """Your past conversations (newest first), read from the stored request traces."""
        who = identify(request)
        return {"sessions": recorder.sessions(trace_config, who.user_id)}

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, request: Request):
        """One of your conversations with its stored answers, to reopen it without any model
        call. `scope_active` says whether follow-ups still inherit its investigation scope
        (the scope is kept in memory for two hours and lost when the API restarts)."""
        who = identify(request)
        if not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise ApiError(422, "invalid_request", "Invalid session id.")
        turns = recorder.session(session_id, trace_config, who.user_id)
        if not turns:
            raise ApiError(404, "not_found", "No such conversation.")
        return {
            "session_id": session_id,
            "scope_active": store.get(session_id) is not None,
            "turns": turns,
        }

    @app.post("/v1/sessions/{session_id}/scope/clear")
    def clear_scope(session_id: str, request: Request):
        identify(request)
        if not re.fullmatch(SESSION_ID_PATTERN, session_id):
            raise ApiError(422, "invalid_request", "Invalid session id.")
        return {"session_id": session_id, "cleared": store.clear(session_id)}

    @app.get("/v1/catalog")
    def get_catalog(request: Request):
        """What the data contains and what can be asked: fixed read-only queries and the
        glossary, no model call (the "Explore the data" guide)."""
        identify(request)
        return catalog.get()

    @app.get("/v1/budget")
    def budget(request: Request):
        who = identify(request)
        total, today = ledger.totals()
        mine = None
        if who.user is not None and who.user.role == "user":
            mine = {
                "today_usd": round(accounts.spend_today(who.user.id), 6),
                "daily_cap_usd": s.user_daily_cap_usd,
            }
        return {
            "total_usd": round(total, 6),
            "today_usd": round(today, 6),
            "total_cap_usd": s.llm_total_cap_usd,
            "daily_cap_usd": s.llm_daily_cap_usd,
            "remaining_total_usd": round(max(s.llm_total_cap_usd - total, 0), 6),
            "remaining_today_usd": round(max(s.llm_daily_cap_usd - today, 0), 6),
            "llm_enabled": s.llm_enabled,
            "you": mine,
        }

    return app


def __getattr__(name: str):
    """`app` is created on first access, so importing this module needs no settings."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
