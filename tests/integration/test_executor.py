"""Executor (technical design 7.3; FR-04, FR-05): read-only, timeout, EXPLAIN ceiling,
row cap, client-side cancel, and the ValidatedSQL-only entry point."""

import psycopg
import pytest

from orderintel.db import executor as ex
from orderintel.db.connect import connect_agent
from orderintel.db.executor import ExecutionError, execute
from orderintel.guard import validator as val
from orderintel.guard.validator import validate
from tests.fixtures.view_queries import VIEW_QUERIES

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.sellers LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)


def run(sql: str, **kw):
    r = validate(sql)
    assert r.ok, r.feedback()
    return execute(r.validated, **kw)


@pytest.mark.parametrize("name", list(VIEW_QUERIES))
def test_legitimate_queries_execute_under_the_ceiling(name):
    res = run(VIEW_QUERIES[name])
    assert res.row_count >= 1
    assert res.explain_cost < ex.DEFAULT_COST_CEILING / 5  # comfortable margin


def test_result_shape():
    res = run("SELECT customer_state, count(*) AS n FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
    assert res.columns == ["customer_state", "n"]
    assert res.rows[0] == ("SP", 41746)
    assert not res.truncated


def test_row_cap_and_truncation_flag():
    res = run("SELECT * FROM order_items")
    assert res.row_count == val.ROW_CAP
    assert res.truncated
    assert "result truncated to 500 rows" in res.notes


def test_exactly_cap_rows_is_not_truncated():
    res = run(f"SELECT order_id FROM orders ORDER BY order_id LIMIT {val.ROW_CAP}")
    assert res.row_count == val.ROW_CAP and not res.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM order_items a, order_items b",
        "SELECT count(*) FROM orders a JOIN orders b ON a.purchase_month = b.purchase_month",
    ],
)
def test_explain_ceiling_refuses_expensive_plans_before_running(sql):
    with pytest.raises(ExecutionError) as e:
        run(sql)
    assert e.value.code == "cost_ceiling"


def test_server_timeout_cancels_slow_query():
    with pytest.raises(ExecutionError) as e:
        run(VIEW_QUERIES["worst_sellers_cte_join"], timeout_s=0.01)
    assert e.value.code == "timeout"


def test_client_timer_cancels_when_server_timeout_is_missing(monkeypatch):
    # Simulate a server timeout that never fires: the client-side timer must cancel.
    real_set_local = ex._set_local

    def no_statement_timeout(conn, name, value):
        if name != "statement_timeout":
            real_set_local(conn, name, value)

    monkeypatch.setattr(ex, "_set_local", no_statement_timeout)
    monkeypatch.setattr(ex, "CANCEL_GRACE_S", 0.0)
    with pytest.raises(ExecutionError) as e:
        run(
            "SELECT count(*) FROM orders a JOIN orders b ON a.purchase_month = b.purchase_month",
            timeout_s=0.5,
            cost_ceiling=float("inf"),
        )
    assert e.value.code == "timeout"


def test_only_validated_sql_is_accepted():
    with pytest.raises(ExecutionError) as e:
        execute("SELECT 1")  # type: ignore[arg-type]
    assert e.value.code == "not_validated"


def test_read_only_even_if_a_write_were_minted():
    # Bypass the validator on purpose (test-only access to its private token) to show the
    # executor's transaction is read-only and the role lacks privileges anyway.
    forged = val.ValidatedSQL("DELETE FROM analytics.sellers", val.ROW_CAP, "", val._TOKEN)
    with pytest.raises(ExecutionError) as e:
        execute(forged)
    assert e.value.code == "database_error"
    with connect_agent() as conn:
        assert conn.execute("SELECT count(*) FROM analytics.sellers").fetchone()[0] == 3095


def test_errors_do_not_leak_connection_details():
    forged = val.ValidatedSQL("SELECT * FROM raw.orders", val.ROW_CAP, "", val._TOKEN)
    with pytest.raises(ExecutionError) as e:
        execute(forged)
    assert "password" not in str(e.value).lower()
    assert e.value.message == "permission denied for schema raw"
