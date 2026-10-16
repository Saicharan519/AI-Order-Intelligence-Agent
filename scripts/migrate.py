"""Apply database migrations.

Two phases:
  1. Roles (as the bootstrap superuser): create or update roles with passwords from .env.
     Role creation is done in Python, not SQL files, so passwords are passed safely as
     literals and never written to disk.
  2. Schema (as oi_owner): apply db/migrations/NNN_*.sql in order, each in its own
     transaction, recorded in meta.schema_migrations with a checksum. An applied file
     that was later edited is an error: write a new migration instead.

Usage:
    python scripts/migrate.py
"""

from __future__ import annotations

import hashlib
import sys

from psycopg import sql

from orderintel.config import PROJECT_ROOT, get_settings
from orderintel.db.connect import connect_owner, connect_superuser

MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"

# Every role: no superuser, cannot create databases or roles (technical design, 6.3).
ROLE_ATTRS = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"

# name: (settings attribute holding the password, connection limit, database privileges,
#        role-level defaults). Object grants (schemas, views, tables) live in the SQL
#        migrations; database-level grants and role defaults need the superuser, so they are here.
# Role defaults are a convenience, not a guarantee: a session can change most of them
# (see docs/postgres_findings.md). temp_file_limit is the exception: only a superuser can set it.
ROLES: dict[str, tuple[str, int, str, dict[str, str]]] = {
    "oi_owner": ("oi_owner_password", 10, "CONNECT, CREATE, TEMPORARY", {}),
    "oi_agent": (
        "oi_agent_password",
        5,
        "CONNECT",
        {
            "statement_timeout": "8s",
            "idle_in_transaction_session_timeout": "15s",
            "default_transaction_read_only": "on",
            "search_path": "analytics",
            "temp_file_limit": "256MB",
        },
    ),
    "oi_trace": ("oi_trace_password", 5, "CONNECT", {"statement_timeout": "5s"}),
    "oi_eval": (
        "oi_eval_password",
        3,
        "CONNECT",
        {
            "statement_timeout": "30s",
            "default_transaction_read_only": "on",
            "temp_file_limit": "1GB",
        },
    ),
    "oi_injtest": (
        "oi_injtest_password",
        2,
        "CONNECT",
        {"statement_timeout": "8s", "default_transaction_read_only": "on"},
    ),
}


def ensure_roles(settings=None) -> None:
    s = settings or get_settings()
    db = sql.Identifier(s.postgres_db)
    with connect_superuser(s, autocommit=True) as conn:
        # Access is by explicit grant only: remove the default PUBLIC privileges.
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")

        for name, (pw_attr, conn_limit, db_privs, defaults) in ROLES.items():
            role = sql.Identifier(name)
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
            verb = sql.SQL("ALTER" if exists else "CREATE")
            password = getattr(s, pw_attr).get_secret_value()
            conn.execute(
                sql.SQL("{} ROLE {} WITH {} CONNECTION LIMIT {} PASSWORD {}").format(
                    verb, role, sql.SQL(ROLE_ATTRS), sql.Literal(conn_limit), sql.Literal(password)
                )
            )
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(db, role))
            conn.execute(
                sql.SQL("GRANT {} ON DATABASE {} TO {}").format(sql.SQL(db_privs), db, role)
            )
            conn.execute(sql.SQL("ALTER ROLE {} RESET ALL").format(role))
            for param, value in defaults.items():
                conn.execute(
                    sql.SQL("ALTER ROLE {} SET {} = {}").format(
                        role, sql.Identifier(param), sql.Literal(value)
                    )
                )
            print(f"roles: {name} {'updated' if exists else 'created'}")


def apply_migrations(settings=None) -> None:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    with connect_owner(settings) as conn:
        conn.execute(
            """
            CREATE SCHEMA IF NOT EXISTS meta;
            CREATE TABLE IF NOT EXISTS meta.schema_migrations (
                version    text PRIMARY KEY,
                checksum   text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        conn.commit()
        applied = dict(
            conn.execute("SELECT version, checksum FROM meta.schema_migrations").fetchall()
        )

        for path in files:
            body = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(body.encode()).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise SystemExit(
                        f"{path.name} was edited after being applied. Add a new migration instead."
                    )
                print(f"skip   {path.name} (already applied)")
                continue
            with conn.transaction():
                conn.execute(body)
                conn.execute(
                    "INSERT INTO meta.schema_migrations (version, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
            print(f"apply  {path.name}")


def main() -> int:
    ensure_roles()
    apply_migrations()
    return 0


if __name__ == "__main__":
    sys.exit(main())
