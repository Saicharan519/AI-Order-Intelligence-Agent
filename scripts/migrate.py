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
ROLE_ATTRS = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"


def ensure_roles() -> None:
    s = get_settings()
    db = sql.Identifier(s.postgres_db)
    with connect_superuser(s, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'oi_owner'").fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL(f"{verb} ROLE oi_owner WITH {ROLE_ATTRS} PASSWORD {{}}").format(  # noqa: S608
                sql.Literal(s.oi_owner_password.get_secret_value())
            )
        )
        # Access is by explicit grant only: remove the default PUBLIC privileges.
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        conn.execute(
            sql.SQL("GRANT CONNECT, CREATE, TEMPORARY ON DATABASE {} TO oi_owner").format(db)
        )
    print(f"roles: oi_owner {'updated' if exists else 'created'}")


def apply_migrations() -> None:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    with connect_owner() as conn:
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
