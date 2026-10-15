"""Q-03: PostgreSQL behaviours the safety design depends on (technical design, section 7.2).

These tests document how PostgreSQL 18 actually behaves for oi_agent. Several are
"dangerous but true" facts: they pass because the database ALLOWS something, which is
why the validator (M4) and executor must add controls on top of the grants. If a future
PostgreSQL version changes one of them, the failing test points at the design to revisit.
"""

import psycopg
import pytest

from orderintel.db.connect import connect_agent

pytestmark = pytest.mark.integration


@pytest.fixture
def agent():
    try:
        conn = connect_agent(autocommit=True)
    except psycopg.Error:
        pytest.skip("database not reachable")
    with conn:
        yield conn


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


# 1. Views execute with the owner's privileges.
def test_views_work_without_raw_privileges(agent):
    assert scalar(agent, "SELECT count(*) FROM analytics.sellers") == 3095
    assert scalar(agent, "SELECT has_schema_privilege('raw', 'USAGE')") is False


# 2. Built-in functions such as pg_sleep are executable by PUBLIC.
def test_pg_sleep_is_callable(agent):
    assert scalar(agent, "SELECT has_function_privilege('pg_sleep(double precision)', 'EXECUTE')")
    agent.execute("SELECT pg_sleep(0.05)")


# 3. set_config changes session settings, including limits, inside a plain SELECT.
def test_set_config_can_disable_statement_timeout(agent):
    assert scalar(agent, "SHOW statement_timeout") == "8s"  # role default
    agent.execute("SELECT set_config('statement_timeout', '0', false)")
    assert scalar(agent, "SHOW statement_timeout") == "0"


def test_set_config_can_disable_read_only_default(agent):
    assert scalar(agent, "SHOW default_transaction_read_only") == "on"
    agent.execute("SELECT set_config('default_transaction_read_only', 'off', false)")
    assert scalar(agent, "SHOW default_transaction_read_only") == "off"


def test_statement_timeout_cancels_when_in_force(agent):
    agent.execute("SET statement_timeout = '200ms'")
    with pytest.raises(psycopg.errors.QueryCanceled):
        agent.execute("SELECT pg_sleep(2)")


# 4. System catalogs are readable: names of raw tables and columns leak, data does not.
def test_catalog_reveals_raw_table_and_column_names(agent):
    cols = scalar(
        agent,
        """SELECT string_agg(attname, ',') FROM pg_attribute a
           JOIN pg_class k ON k.oid = a.attrelid JOIN pg_namespace n ON n.oid = k.relnamespace
           WHERE n.nspname = 'raw' AND k.relname = 'order_reviews' AND attnum > 0""",
    )
    assert "review_comment_message" in cols
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("SELECT review_comment_message FROM raw.order_reviews LIMIT 1")


def test_pg_stats_hides_values_of_unreadable_tables(agent):
    assert scalar(agent, "SELECT count(*) FROM pg_stats WHERE schemaname = 'raw'") == 0


def test_other_sessions_query_text_is_hidden(agent):
    hidden = scalar(
        agent,
        "SELECT bool_and(query = '<insufficient privilege>') FROM pg_stat_activity "
        "WHERE usename IS NOT NULL AND usename <> current_user",
    )
    assert hidden in (True, None)  # None when no other session is connected


# 5. temp_file_limit can only be set by a superuser, so the role default is enforceable.
def test_temp_file_limit_cannot_be_raised(agent):
    assert scalar(agent, "SHOW temp_file_limit") == "256MB"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("SET temp_file_limit = '100GB'")


def test_generate_series_is_callable(agent):
    assert scalar(agent, "SELECT count(*) FROM generate_series(1, 10)") == 10


def test_server_configuration_paths_hidden(agent):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent.execute("SELECT current_setting('data_directory')")
