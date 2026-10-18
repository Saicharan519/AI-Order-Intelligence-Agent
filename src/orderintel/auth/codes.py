"""Emailed 6-digit codes and trusted devices (schema app, written as oi_trace).

Each code belongs to a secret the server never stores in the clear: for sign-in and password
reset a random challenge token kept in the browser's httpOnly cookie, for an email change the
user's session token. The database keeps sha256(secret) to find the row and
sha256(secret:code) to check the code, so a copy of the table cannot be used to try the
million possible codes offline; online, 5 wrong tries end the code.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from orderintel.auth.crypto import new_token, token_hash
from orderintel.auth.store import AccountError
from orderintel.db.connect import connect_trace

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_SENDS = 5  # per code, including the first
RESEND_WAIT_S = 60
MAX_CODES_PER_HOUR = 10  # per user and purpose: stops anyone flooding an inbox
TRUST_DAYS = 30


def _wrong() -> AccountError:
    return AccountError("wrong_code", "That code is wrong or has expired.")


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _code_hash(secret: str, code: str) -> str:
    return hashlib.sha256(f"{secret}:{code}".encode()).hexdigest()


@dataclass(frozen=True)
class Verified:
    user_id: str
    new_email: str | None


class CodeStore:
    def __init__(self, settings=None) -> None:
        self._connect = lambda: connect_trace(settings)

    def start(self, user_id: str, purpose: str, secret: str, new_email: str | None = None) -> str:
        """A new code for this secret. Earlier unused codes of the same kind end, except for
        sign-in, where two browsers may each be waiting for their own code."""
        code = new_code()
        with self._connect() as conn, conn.transaction():
            recent = conn.execute(
                "SELECT count(*) FROM app.email_codes WHERE user_id = %s AND purpose = %s "
                "AND created_at > now() - interval '1 hour'",
                (user_id, purpose),
            ).fetchone()[0]
            if recent >= MAX_CODES_PER_HOUR:
                raise AccountError(
                    "too_many_codes", "Too many codes were sent. Please wait an hour."
                )
            if purpose != "login":
                conn.execute(
                    "UPDATE app.email_codes SET used_at = now() WHERE user_id = %s "
                    "AND purpose = %s AND used_at IS NULL",
                    (user_id, purpose),
                )
            conn.execute(
                "INSERT INTO app.email_codes (id, user_id, purpose, secret_hash, code_hash, "
                "new_email, expires_at) VALUES (%s, %s, %s, %s, %s, %s, "
                "now() + make_interval(mins => %s))",
                (
                    str(uuid.uuid4()),
                    user_id,
                    purpose,
                    token_hash(secret),
                    _code_hash(secret, code),
                    new_email,
                    CODE_MINUTES,
                ),
            )
        return code

    def resend(self, secret: str, purpose: str) -> tuple[str, str, str | None]:
        """A fresh code for a pending one: (user_id, code, new_email). Wrong tries carry over."""
        code = new_code()
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, new_email, sends, "
                "extract(epoch FROM now() - last_sent_at) FROM app.email_codes "
                "WHERE secret_hash = %s AND purpose = %s AND used_at IS NULL "
                "AND expires_at > now() AND attempts < %s FOR UPDATE",
                (token_hash(secret), purpose, MAX_ATTEMPTS),
            ).fetchone()
            if row is None:
                raise AccountError("code_expired", "This code has expired. Please start again.")
            if row[4] < RESEND_WAIT_S:
                raise AccountError("resend_wait", "Please wait a minute before asking again.")
            if row[3] >= MAX_SENDS:
                raise AccountError("too_many_codes", "Too many codes were sent. Start again.")
            conn.execute(
                "UPDATE app.email_codes SET code_hash = %s, sends = sends + 1, "
                "last_sent_at = now(), expires_at = now() + make_interval(mins => %s) "
                "WHERE id = %s",
                (_code_hash(secret, code), CODE_MINUTES, row[0]),
            )
        return str(row[1]), code, row[2]

    def verify(self, secret: str, purpose: str, code: str) -> Verified:
        """Use up the code if it is right; count a wrong try otherwise (the 5th ends it)."""
        code = (code or "").strip().replace(" ", "")
        result: Verified | None = None
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, new_email, code_hash, attempts FROM app.email_codes "
                "WHERE secret_hash = %s AND purpose = %s AND used_at IS NULL "
                "AND expires_at > now() AND attempts < %s FOR UPDATE",
                (token_hash(secret or ""), purpose, MAX_ATTEMPTS),
            ).fetchone()
            if row is None:
                raise _wrong()
            if len(code) == 6 and hmac.compare_digest(_code_hash(secret, code), row[3]):
                conn.execute("UPDATE app.email_codes SET used_at = now() WHERE id = %s", (row[0],))
                result = Verified(str(row[1]), row[2])
            else:  # committed before the error is raised, so wrong tries always count
                conn.execute(
                    "UPDATE app.email_codes SET attempts = attempts + 1, used_at = CASE "
                    "WHEN attempts + 1 >= %s THEN now() END WHERE id = %s",
                    (MAX_ATTEMPTS, row[0]),
                )
        if result is None:
            raise _wrong()
        return result

    def pending_email_change(self, secret: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT new_email FROM app.email_codes WHERE secret_hash = %s "
                "AND purpose = 'email_change' AND used_at IS NULL AND expires_at > now()",
                (token_hash(secret),),
            ).fetchone()
        return row[0] if row else None

    # ---------- trusted devices ----------
    def trust_device(self, user_id: str) -> str:
        token = new_token()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app.trusted_devices (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, now() + make_interval(days => %s))",
                (token_hash(token), user_id, TRUST_DAYS),
            )
        return token

    def is_trusted(self, user_id: str, token: str | None) -> bool:
        if not token:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM app.trusted_devices WHERE token_hash = %s AND user_id = %s "
                "AND expires_at > now()",
                (token_hash(token), user_id),
            ).fetchone()
        return row is not None

    def forget_devices(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM app.trusted_devices WHERE user_id = %s", (user_id,))
