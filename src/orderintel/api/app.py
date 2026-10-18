"""HTTP API (T-9.1; technical design 9 and 10.4).

Accounts (invite-only): POST /v1/auth/login, /v1/auth/logout, /v1/auth/signup,
GET /v1/auth/me, GET /v1/auth/invites/{code}, POST /v1/auth/login/verify, /login/resend,
/v1/auth/password/forgot, /password/resend, /password/reset (emailed 6-digit codes);
your account: POST /v1/account/profile, /v1/account/email/confirm, /email/resend,
POST /v1/account/password; admin: GET /v1/admin/users,
POST /v1/admin/users/{id}/disable|enable|delete, GET|POST /v1/admin/invites,
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

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orderintel.agent.ask import PreviousTurn, ask, build_graph
from orderintel.agent.session import SessionStore
from orderintel.api.schemas import AskResponse
from orderintel.auth.codes import CodeStore
from orderintel.auth.crypto import new_token, normalise_email, password_problem
from orderintel.auth.mail import (
    Mail,
    Mailer,
    MailError,
    email_change_mail,
    invite_mail,
    login_code_mail,
    mailer_for,
    reset_code_mail,
)
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
    device: str = Field(default="", max_length=100)  # a trusted-device token, if any


class CodeRequest(BaseModel):
    challenge: str = Field(pattern=INVITE_PATTERN)
    code: str = Field(min_length=1, max_length=12)
    trust_device: bool = False


class ChallengeRequest(BaseModel):
    challenge: str = Field(pattern=INVITE_PATTERN)


class ForgotRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetRequest(BaseModel):
    challenge: str = Field(pattern=INVITE_PATTERN)
    code: str = Field(min_length=1, max_length=12)
    new_password: str = Field(min_length=1, max_length=200)


class EmailCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)


class SignupRequest(BaseModel):
    invite: str = Field(pattern=INVITE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    send: bool = True  # email the link to that address


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    current_password: str = Field(default="", max_length=200)  # needed to change the email


class PasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


ACCOUNT_ERROR_STATUS = {
    "email_taken": 409,
    "not_found": 404,
    "not_allowed": 403,
    "too_many_codes": 429,
    "resend_wait": 429,
}


def mask_email(email: str) -> str:
    """k.saicharan@gmail.com -> k***@gmail.com: enough to recognise, not to read."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def create_app(
    settings: Settings | None = None,
    client: LLMClient | None = None,
    recorder: TraceRecorder | None = None,
    store: SessionStore | None = None,
    clock: Callable[[], float] = time.monotonic,
    trace_config: str = "api",
    accounts: AccountStore | None = None,
    mailer: Mailer | None = None,
) -> FastAPI:
    s = settings or get_settings()
    store = store or SessionStore()
    recorder = recorder or TraceRecorder(s)
    accounts = accounts or AccountStore(s)
    mailer = mailer or mailer_for(s)
    codes = CodeStore(s)
    ledger = PostgresLedger(s)
    state: dict = {"client": client, "graph": None}
    limiter = RateLimiter(s.rate_limit_per_ip_per_min, s.rate_limit_global_per_min, clock)
    throttle = LoginThrottle(clock)
    # Per client: wrong codes and invite lookups (failures), and emails asked for (sends).
    # Keyed by client only, so one client's mistakes never block anyone else.
    code_throttle = LoginThrottle(clock)
    send_throttle = LoginThrottle(clock)
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
    def session_token(request: Request) -> str:
        auth = request.headers.get("authorization") or ""
        return auth[7:].strip() if auth.lower().startswith("bearer ") else ""

    def send(mail: Mail) -> None:
        """Send now; a failure is an error the user sees (the code or link did not go out)."""
        try:
            mailer.send(mail)
        except MailError as e:
            _log("mail_failed", mode=mailer.mode, error=str(e))
            raise ApiError(
                502, "mail_failed", "The email could not be sent. Please try again later."
            ) from None

    def send_quietly(mail: Mail) -> None:
        """For password reset: sent after the answer, so the answer and its timing are the
        same whether or not the email has an account."""
        try:
            mailer.send(mail)
        except MailError as e:
            _log("mail_failed", mode=mailer.mode, error=str(e))

    def limit_sends(request: Request) -> None:
        ip = client_ip(request)
        if send_throttle.client_blocked(ip, 10):
            raise ApiError(429, "too_many_codes", "Too many emails were asked for. Please wait.")
        send_throttle.client_counted(ip)

    def check_code_throttle(request: Request) -> str:
        ip = client_ip(request)
        if code_throttle.client_blocked(ip):
            raise ApiError(429, "too_many_attempts", "Too many wrong codes. Please wait.")
        return ip

    def console_hint() -> dict:
        return {"mail_mode": "console"} if mailer.mode == "console" else {}

    @app.post("/v1/auth/login")
    def login(body: LoginRequest, request: Request):
        """Email and password. Then either a session token (codes off, or a trusted device)
        or an emailed 6-digit code and a challenge for /v1/auth/login/verify. The same
        answer for an unknown email and a wrong password; repeated failures are refused."""
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
        if not s.login_code_required or codes.is_trusted(user.id, body.device):
            _log("login", user_id=user.id)
            return {"token": accounts.create_session(user), "user": user.public()}
        limit_sends(request)
        challenge = new_token()
        code = codes.start(user.id, "login", challenge)
        send(login_code_mail(user.email, user.name, code))
        _log("login_code_sent", user_id=user.id)
        return {
            "code_required": True,
            "challenge": challenge,
            "email_hint": mask_email(user.email),
            **console_hint(),
        }

    @app.post("/v1/auth/login/verify")
    def login_verify(body: CodeRequest, request: Request):
        """The emailed code -> a session token (and a trusted-device token if asked)."""
        ip = check_code_throttle(request)
        try:
            found = codes.verify(body.challenge, "login", body.code)
        except AccountError:
            code_throttle.client_counted(ip)
            raise
        user = accounts.get_user(found.user_id)
        if user is None or user.disabled:
            raise ApiError(401, "invalid_credentials", "Email or password is wrong.")
        out = {"token": accounts.create_session(user), "user": user.public()}
        if body.trust_device:
            out["device_token"] = codes.trust_device(user.id)
        _log("login", user_id=user.id, trusted_device=body.trust_device)
        return out

    @app.post("/v1/auth/login/resend")
    def login_resend(body: ChallengeRequest, request: Request):
        limit_sends(request)
        user_id, code, _ = codes.resend(body.challenge, "login")
        user = accounts.get_user(user_id)
        if user is None or user.disabled:
            raise ApiError(400, "code_expired", "This code has expired. Please start again.")
        send(login_code_mail(user.email, user.name, code))
        return {"ok": True}

    @app.post("/v1/auth/password/forgot")
    def password_forgot(body: ForgotRequest, request: Request, tasks: BackgroundTasks):
        """Always the same answer (a challenge), so it cannot reveal who has an account.
        If the email has an active account, a reset code is emailed after the answer."""
        limit_sends(request)
        challenge = new_token()
        user = accounts.user_by_email(body.email)
        if user is not None and not user.disabled:
            try:
                code = codes.start(user.id, "reset", challenge)
                tasks.add_task(send_quietly, reset_code_mail(user.email, user.name, code))
                _log("reset_code_sent", user_id=user.id)
            except AccountError:  # too many codes this hour: same answer, no email
                _log("reset_code_refused", user_id=user.id)
        return {"challenge": challenge, **console_hint()}

    @app.post("/v1/auth/password/resend")
    def password_resend(body: ChallengeRequest, request: Request, tasks: BackgroundTasks):
        """Same answer whatever happens, for the same reason as /forgot."""
        limit_sends(request)
        try:
            user_id, code, _ = codes.resend(body.challenge, "reset")
            user = accounts.get_user(user_id)
            if user is not None and not user.disabled:
                tasks.add_task(send_quietly, reset_code_mail(user.email, user.name, code))
        except AccountError:
            pass
        return {"ok": True}

    @app.post("/v1/auth/password/reset")
    def password_reset(body: ResetRequest, request: Request):
        """The emailed code and a new password. Every session and trusted device ends."""
        if problem := password_problem(body.new_password):
            raise AccountError("weak_password", problem)
        ip = check_code_throttle(request)
        try:
            found = codes.verify(body.challenge, "reset", body.code)
        except AccountError:
            code_throttle.client_counted(ip)
            raise
        user = accounts.get_user(found.user_id)
        if user is None or user.disabled:
            raise ApiError(400, "wrong_code", "That code is wrong or has expired.")
        accounts.set_password(user.email, body.new_password)
        codes.forget_devices(user.id)
        throttle.succeeded(user.email)
        _log("password_reset", user_id=user.id)
        return {"ok": True}

    @app.post("/v1/auth/logout")
    def logout(request: Request):
        if token := session_token(request):
            accounts.end_session(token)
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
        ip = check_code_throttle(request)
        found = accounts.invite_for_code(code)
        if found is None:
            code_throttle.client_counted(ip)
            raise ApiError(
                404, "invalid_invite", "This invite link is not valid: it may be used or expired."
            )
        return {"email": found["email"], "expires_at": found["expires_at"]}

    @app.post("/v1/auth/signup")
    def signup(body: SignupRequest):
        user = accounts.accept_invite(body.invite, body.name, body.password)
        _log("signup", user_id=user.id)
        return {"token": accounts.create_session(user), "user": user.public()}

    # ---------------- your account ----------------
    def signed_in(request: Request) -> User:
        who = identify(request)
        if who.user is None:
            raise ApiError(403, "forbidden", "Only a signed-in user has an account to change.")
        return who.user

    def confirm_password(user: User, password: str, request: Request) -> None:
        """The current password again, with the same lockout as sign-in for wrong guesses."""
        ip = client_ip(request)
        if throttle.blocked(user.email, ip):
            raise ApiError(
                429, "too_many_attempts", "Too many wrong passwords. Please wait 15 minutes."
            )
        if not accounts.check_password(user, password):
            throttle.failed(user.email, ip)
            raise ApiError(400, "wrong_password", "Your current password is wrong.")
        throttle.succeeded(user.email)

    @app.post("/v1/account/profile")
    def account_profile(body: ProfileRequest, request: Request):
        """Change your name at once. A new email needs your current password and is used
        only after you enter the code sent to it (/v1/account/email/confirm)."""
        user = signed_in(request)
        new_email = normalise_email(body.email)
        if new_email is None:
            raise AccountError("invalid_email", "Enter a valid email address.")
        updated = accounts.update_profile(user, body.name, user.email)
        if new_email == user.email:
            _log("profile_updated", user_id=user.id)
            return updated.public()
        confirm_password(user, body.current_password, request)
        if accounts.user_by_email(new_email) is not None:
            raise AccountError("email_taken", "An account with this email already exists.")
        limit_sends(request)
        code = codes.start(user.id, "email_change", session_token(request), new_email=new_email)
        send(email_change_mail(new_email, updated.name, code))
        _log("email_change_code_sent", user_id=user.id)
        return {**updated.public(), "pending_email": new_email, **console_hint()}

    @app.post("/v1/account/email/confirm")
    def account_email_confirm(body: EmailCodeRequest, request: Request):
        user = signed_in(request)
        found = codes.verify(session_token(request), "email_change", body.code)
        if found.user_id != user.id or not found.new_email:
            raise ApiError(400, "wrong_code", "That code is wrong or has expired.")
        updated = accounts.update_profile(user, user.name, found.new_email)
        _log("email_changed", user_id=user.id)
        return updated.public()

    @app.post("/v1/account/email/resend")
    def account_email_resend(request: Request):
        user = signed_in(request)
        limit_sends(request)
        _, code, new_email = codes.resend(session_token(request), "email_change")
        if new_email:
            send(email_change_mail(new_email, user.name, code))
        return {"ok": True}

    @app.post("/v1/account/password")
    def account_password(body: PasswordRequest, request: Request):
        """Change your password; your other devices are signed out (and no device stays
        trusted), this one stays in."""
        user = signed_in(request)
        confirm_password(user, body.current_password, request)
        accounts.change_password(user, body.new_password, keep_token=session_token(request))
        codes.forget_devices(user.id)
        _log("password_changed", user_id=user.id)
        return {"ok": True}

    # ---------------- admin ----------------
    @app.get("/v1/admin/users")
    def admin_users(request: Request):
        require_admin(identify(request))
        return {"users": accounts.list_users(), "user_daily_cap_usd": s.user_daily_cap_usd}

    @app.post("/v1/admin/users/{user_id}/{action}")
    def admin_user_action(user_id: str, action: str, request: Request):
        admin = require_admin(identify(request))
        if action not in ("disable", "enable", "delete") or not re.fullmatch(UUID_PATTERN, user_id):
            raise ApiError(404, "not_found", "No such action.")
        if action == "delete":
            removed = accounts.delete_user(user_id, admin)
            _log("user_deleted", user_id=user_id, by=admin.id, questions=removed)
            return {"id": user_id, "deleted": True, "questions_removed": removed}
        user = accounts.set_disabled(user_id, action == "disable", admin)
        _log("user_" + action, user_id=user.id, by=admin.id)
        return {"id": user.id, "disabled": user.disabled}

    @app.get("/v1/admin/invites")
    def admin_invites(request: Request):
        require_admin(identify(request))
        return {"invites": accounts.list_invites()}

    @app.post("/v1/admin/invites")
    def admin_create_invite(body: InviteRequest, request: Request):
        """A one-time invite for an email, emailed to that address when send is true. The
        code is in this response only (the link is also shown as a backup to copy)."""
        admin = require_admin(identify(request))
        code, invite = accounts.create_invite(body.email, admin)
        _log("invite_created", invite_id=invite["id"], by=admin.id)
        mail = {"sent": False, "mode": mailer.mode}
        if body.send:
            link = f"{s.app_url.rstrip('/')}/signup?invite={code}"
            try:
                mailer.send(invite_mail(invite["email"], admin.name, link))
                mail["sent"] = True
            except MailError as e:
                _log("mail_failed", mode=mailer.mode, error=str(e))
        return {"code": code, "invite": invite, "mail": mail}

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
