"""Accounts, sign-in sessions and invites in PostgreSQL (schema app, written as oi_trace).

Invite flow: an admin creates an invite for an email; the one-time code is shown once (only
its hash is stored); the person opens the link, chooses a name and password, and the invite
is used up in the same transaction that creates the account. Sessions expire, end at sign
out, and end at once when an account is disabled.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import psycopg

from orderintel.auth.crypto import (
    DUMMY_HASH,
    hash_password,
    new_token,
    normalise_email,
    password_problem,
    token_hash,
    verify_password,
)
from orderintel.db.connect import connect_trace

SESSION_DAYS = 7
INVITE_DAYS = 7


class AccountError(Exception):
    """A request the user can fix (bad invite, weak password, ...): code + message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: str  # user | admin
    disabled: bool = False

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "role": self.role}


def _user(row) -> User:
    return User(str(row[0]), row[1], row[2], row[3], row[4])


class AccountStore:
    def __init__(self, settings=None) -> None:
        self._connect = lambda: connect_trace(settings)

    # ---------- users ----------
    def create_user(self, email: str, name: str, password: str, role: str = "user") -> User:
        e = normalise_email(email)
        if not e:
            raise AccountError("invalid_email", "Enter a valid email address.")
        name = (name or "").strip()
        if not 1 <= len(name) <= 80:
            raise AccountError("invalid_name", "Enter a name of 1 to 80 characters.")
        if problem := password_problem(password, e):
            raise AccountError("weak_password", problem)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "INSERT INTO app.users (id, email, name, password_hash, role) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id, email, name, role, disabled",
                    (str(uuid.uuid4()), e, name, hash_password(password), role),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise AccountError(
                "email_taken", "An account with this email already exists."
            ) from None
        return _user(row)

    def set_password(self, email: str, password: str) -> bool:
        e = normalise_email(email) or ""
        if problem := password_problem(password, e):
            raise AccountError("weak_password", problem)
        with self._connect() as conn:
            n = conn.execute(
                "UPDATE app.users SET password_hash = %s WHERE email = %s",
                (hash_password(password), e),
            ).rowcount
            conn.execute(
                "DELETE FROM app.sessions WHERE user_id = "
                "(SELECT id FROM app.users WHERE email = %s)",
                (e,),
            )
        return n == 1

    def authenticate(self, email: str, password: str) -> User | None:
        """The user for a correct email and password; None otherwise (same time either way)."""
        e = normalise_email(email) or ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, name, role, disabled, password_hash "
                "FROM app.users WHERE email = %s",
                (e,),
            ).fetchone()
        if row is None:
            verify_password(password, DUMMY_HASH)
            return None
        if not verify_password(password, row[5]) or row[4]:  # wrong password or disabled
            return None
        return _user(row)

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, name, role, disabled FROM app.users WHERE id = %s", (user_id,)
            ).fetchone()
        return _user(row) if row else None

    def set_disabled(self, user_id: str, disabled: bool, by: User) -> User:
        if user_id == by.id:
            raise AccountError("not_allowed", "You cannot disable your own account.")
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE app.users SET disabled = %s WHERE id = %s "
                "RETURNING id, email, name, role, disabled",
                (disabled, user_id),
            ).fetchone()
            if row is None:
                raise AccountError("not_found", "No such user.")
            if disabled:  # ends every session of that user at once
                conn.execute("DELETE FROM app.sessions WHERE user_id = %s", (user_id,))
        return _user(row)

    def list_users(self) -> list[dict]:
        """Every account with its spend today and in total (LLM calls of its requests)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.email, u.name, u.role, u.disabled, u.created_at, u.last_login_at,
                       coalesce(sum(c.cost_usd), 0) AS total_usd,
                       coalesce(sum(c.cost_usd) FILTER (WHERE c.created_at >=
                           date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
                           AS today_usd,
                       count(DISTINCT r.id) AS questions
                FROM app.users u
                LEFT JOIN trace.requests r ON r.user_id = u.id AND r.kind = 'request'
                LEFT JOIN trace.requests c ON c.parent_id = r.id AND c.kind = 'llm_call'
                GROUP BY u.id ORDER BY u.created_at"""
            ).fetchall()
        return [
            {
                "id": str(r[0]),
                "email": r[1],
                "name": r[2],
                "role": r[3],
                "disabled": r[4],
                "created_at": r[5].isoformat(),
                "last_login_at": r[6].isoformat() if r[6] else None,
                "total_usd": round(float(r[7]), 6),
                "today_usd": round(float(r[8]), 6),
                "questions": r[9],
            }
            for r in rows
        ]

    def spend_today(self, user_id: str) -> float:
        with self._connect() as conn:
            v = conn.execute(
                """SELECT coalesce(sum(c.cost_usd), 0) FROM trace.requests c
                    JOIN trace.requests r ON c.parent_id = r.id
                    WHERE r.user_id = %s AND c.kind = 'llm_call'
                      AND c.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                                          AT TIME ZONE 'UTC'""",
                (user_id,),
            ).fetchone()[0]
        return float(v)

    # ---------- sessions ----------
    def create_session(self, user: User) -> str:
        token = new_token()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app.sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, now() + make_interval(days => %s))",
                (token_hash(token), user.id, SESSION_DAYS),
            )
            conn.execute("UPDATE app.users SET last_login_at = now() WHERE id = %s", (user.id,))
        return token

    def user_for_token(self, token: str) -> User | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE app.sessions s SET last_seen_at = now()
                    FROM app.users u
                    WHERE s.token_hash = %s AND s.user_id = u.id
                      AND s.expires_at > now() AND NOT u.disabled
                    RETURNING u.id, u.email, u.name, u.role, u.disabled""",
                (token_hash(token),),
            ).fetchone()
        return _user(row) if row else None

    def end_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM app.sessions WHERE token_hash = %s", (token_hash(token),))

    # ---------- invites ----------
    def create_invite(self, email: str, by: User) -> tuple[str, dict]:
        """A one-time code for this email; the code is returned once and never stored."""
        e = normalise_email(email)
        if not e:
            raise AccountError("invalid_email", "Enter a valid email address.")
        code = new_token()
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM app.users WHERE email = %s", (e,)).fetchone():
                raise AccountError("email_taken", "An account with this email already exists.")
            row = conn.execute(
                "INSERT INTO app.invites (id, code_hash, email, created_by, expires_at) "
                "VALUES (%s, %s, %s, %s, now() + make_interval(days => %s)) "
                "RETURNING id, email, created_at, expires_at",
                (str(uuid.uuid4()), token_hash(code), e, by.id, INVITE_DAYS),
            ).fetchone()
        return code, {
            "id": str(row[0]),
            "email": row[1],
            "created_at": row[2].isoformat(),
            "expires_at": row[3].isoformat(),
            "status": "pending",
        }

    def invite_for_code(self, code: str) -> dict | None:
        """The pending invite for a code, or None if unknown, used, revoked or expired."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, expires_at FROM app.invites WHERE code_hash = %s "
                "AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now()",
                (token_hash(code or ""),),
            ).fetchone()
        return (
            {"id": str(row[0]), "email": row[1], "expires_at": row[2].isoformat()} if row else None
        )

    def accept_invite(self, code: str, name: str, password: str) -> User:
        """Create the account and use up the invite, in one transaction."""
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, email FROM app.invites WHERE code_hash = %s AND used_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > now() FOR UPDATE",
                (token_hash(code or ""),),
            ).fetchone()
            if row is None:
                raise AccountError(
                    "invalid_invite", "This invite link is not valid: it may be used or expired."
                )
            invite_id, email = row
            name = (name or "").strip()
            if not 1 <= len(name) <= 80:
                raise AccountError("invalid_name", "Enter a name of 1 to 80 characters.")
            if problem := password_problem(password, email):
                raise AccountError("weak_password", problem)
            try:
                user_row = conn.execute(
                    "INSERT INTO app.users (id, email, name, password_hash) "
                    "VALUES (%s, %s, %s, %s) RETURNING id, email, name, role, disabled",
                    (str(uuid.uuid4()), email, name, hash_password(password)),
                ).fetchone()
            except psycopg.errors.UniqueViolation:
                raise AccountError(
                    "email_taken", "An account with this email already exists."
                ) from None
            conn.execute(
                "UPDATE app.invites SET used_at = now(), used_by = %s WHERE id = %s",
                (user_row[0], invite_id),
            )
        return _user(user_row)

    def list_invites(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, email, created_at, expires_at, used_at, revoked_at "
                "FROM app.invites ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        now = dt.datetime.now(dt.UTC)

        def status(r) -> str:
            if r[4]:
                return "used"
            if r[5]:
                return "revoked"
            return "expired" if r[3] <= now else "pending"

        return [
            {
                "id": str(r[0]),
                "email": r[1],
                "created_at": r[2].isoformat(),
                "expires_at": r[3].isoformat(),
                "status": status(r),
            }
            for r in rows
        ]

    def revoke_invite(self, invite_id: str) -> bool:
        with self._connect() as conn:
            return (
                conn.execute(
                    "UPDATE app.invites SET revoked_at = now() WHERE id = %s "
                    "AND used_at IS NULL AND revoked_at IS NULL",
                    (invite_id,),
                ).rowcount
                == 1
            )
