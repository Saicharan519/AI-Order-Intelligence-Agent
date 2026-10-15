"""SC-01: oi_agent cannot write, alter, or read outside the curated views.

Every attack runs twice:
  * role defaults (read-only transactions, 8 s timeout): must fail for any reason;
  * read-only switched off by the session itself: must fail with insufficient_privilege
    (42501). This proves the grants alone contain the agent, because a session can turn
    the read-only default off (see test_postgres_findings.py).
"""

import psycopg
import pytest

from orderintel.db.connect import connect_agent, connect_eval, connect_trace
from tests.integration.agent_attacks import AGENT_MUST_FAIL, AGENT_MUST_SUCCEED

pytestmark = pytest.mark.integration

# These cannot run inside a transaction block, so they are sent in autocommit mode.
NO_TXN = {"alter_system", "create_database"}


def _db_available() -> bool:
    try:
        with connect_agent() as conn:
            conn.execute("SELECT 1 FROM analytics.sellers LIMIT 1")
        return True
    except psycopg.Error:
        return False


if not _db_available():
    pytest.skip("database not reachable or not migrated", allow_module_level=True)


def run_as_agent(sql: str, read_only_off: bool, no_txn: bool) -> psycopg.Error | None:
    with connect_agent(autocommit=True) as conn:
        if read_only_off:
            conn.execute("SET default_transaction_read_only = off")
        try:
            if no_txn:
                conn.execute(sql)
            else:
                with conn.transaction(force_rollback=True):
                    conn.execute(sql)
        except psycopg.Error as e:
            return e
    return None


@pytest.mark.parametrize(("case_id", "sql", "expected"), AGENT_MUST_FAIL, ids=lambda x: x)
def test_attack_fails_with_role_defaults(case_id, sql, expected):
    err = run_as_agent(sql, read_only_off=False, no_txn=case_id in NO_TXN)
    assert err is not None, f"{case_id} SUCCEEDED as oi_agent"


@pytest.mark.parametrize(("case_id", "sql", "expected"), AGENT_MUST_FAIL, ids=lambda x: x)
def test_attack_fails_by_permission_alone(case_id, sql, expected):
    err = run_as_agent(sql, read_only_off=True, no_txn=case_id in NO_TXN)
    assert err is not None, f"{case_id} SUCCEEDED as oi_agent with read-only off"
    assert err.sqlstate == expected, f"{case_id}: {err.sqlstate} {err.diag.message_primary}"


def test_attack_list_size_meets_sc01():
    assert len(AGENT_MUST_FAIL) >= 25


@pytest.mark.parametrize(("view", "sql"), AGENT_MUST_SUCCEED)
def test_agent_can_read_every_view(view, sql):
    with connect_agent() as conn:
        conn.execute(sql).fetchall()


def test_agent_sees_only_analytics_relations():
    """Catalog check: the agent has SELECT on exactly the six views and nothing else."""
    with connect_agent() as conn:
        rows = conn.execute(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND has_table_privilege(c.oid, 'SELECT')
            ORDER BY 1
            """
        ).fetchall()
    assert [r[0] for r in rows] == [
        "analytics.data_coverage",
        "analytics.order_items",
        "analytics.orders",
        "analytics.payments",
        "analytics.reviews",
        "analytics.sellers",
    ]


def test_review_text_not_reachable_through_views():
    with connect_agent() as conn:
        cols = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'analytics' AND column_name LIKE '%comment%'"
        ).fetchall()
    # only the boolean flags, never text
    assert sorted(cols) == [("orders", "has_review_comment"), ("reviews", "has_comment")]


def test_trace_role_cannot_read_business_data():
    with connect_trace() as conn:
        for sql in ("SELECT 1 FROM analytics.orders LIMIT 1", "SELECT 1 FROM raw.orders LIMIT 1"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(sql)


def test_eval_role_is_read_only():
    with connect_eval(autocommit=True) as conn:
        conn.execute("SELECT 1 FROM raw.orders LIMIT 1")
        conn.execute("SELECT 1 FROM analytics.orders LIMIT 1")
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(force_rollback=True):
                conn.execute("DELETE FROM raw.sellers")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction(force_rollback=True):
                conn.execute("SELECT 1 FROM trace.requests")


def test_roles_have_no_dangerous_attributes():
    with connect_agent() as conn:
        rows = conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname LIKE 'oi\\_%' AND "
            "(rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication)"
        ).fetchall()
    assert rows == []
