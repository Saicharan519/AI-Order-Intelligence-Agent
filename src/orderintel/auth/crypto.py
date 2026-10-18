"""Password hashing and random tokens.

Passwords: scrypt from the standard library (memory-hard, accepted by OWASP's password
storage guidance), a random 16-byte salt per password, parameters stored with the hash so
they can be raised later. Verification compares in constant time.

Tokens (sign-in sessions, invite codes): 32 random bytes from `secrets`; only their SHA-256
is stored, so the database alone cannot be used to sign in or to accept an invite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD, MAX_PASSWORD = 10, 128  # the maximum stops very long inputs costing CPU
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=MAXMEM
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        got = hashlib.scrypt(
            password[:MAX_PASSWORD].encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# Verified against when the email is unknown, so a wrong email takes as long as a wrong
# password and timing does not reveal which emails have accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, email: str = "") -> str | None:
    """Why a new password is not acceptable, in words (None when it is)."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    if email and password.strip().lower() == email.strip().lower():
        return "Do not use your email address as the password."
    if len(set(password)) < 4:
        return "Use a less repetitive password."
    return None


def normalise_email(email: str) -> str | None:
    e = (email or "").strip().lower()
    return e if EMAIL_RE.match(e) and len(e) <= 254 else None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
