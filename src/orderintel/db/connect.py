"""Database connections, one function per role.

Each role has its own password (technical design, section 6.3). Passwords are read
from settings at connection time and are never logged.
"""

from __future__ import annotations

import psycopg

from orderintel.config import Settings, get_settings


def _connect(user: str, password: str, settings: Settings, **kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=user,
        password=password,
        connect_timeout=10,
        **kwargs,
    )


def connect_superuser(settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """Bootstrap superuser: only for creating roles. Never used by the application."""
    s = settings or get_settings()
    return _connect("postgres", s.postgres_password.get_secret_value(), s, **kwargs)


def connect_owner(settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """oi_owner: owns all objects; used by migrations and the loader only."""
    s = settings or get_settings()
    return _connect("oi_owner", s.oi_owner_password.get_secret_value(), s, **kwargs)


def connect_agent(settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """oi_agent: SELECT on analytics views only. The only role that runs model-written SQL."""
    s = settings or get_settings()
    return _connect("oi_agent", s.oi_agent_password.get_secret_value(), s, **kwargs)


def connect_trace(settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """oi_trace: writes trace tables; cannot read business data."""
    s = settings or get_settings()
    return _connect("oi_trace", s.oi_trace_password.get_secret_value(), s, **kwargs)


def connect_eval(settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """oi_eval: read-only on raw and analytics; evaluation tooling only."""
    s = settings or get_settings()
    return _connect("oi_eval", s.oi_eval_password.get_secret_value(), s, **kwargs)
