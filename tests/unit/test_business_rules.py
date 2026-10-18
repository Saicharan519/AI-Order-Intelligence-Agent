"""Revenue rule: every SUM/AVG over items_revenue or price must be limited to sales."""

from pathlib import Path

import pytest

from orderintel.guard.business_rules import revenue_violations

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "revenue_without_sale_filter.sql"


def test_the_smoke_question_sql_is_caught():
    """Owner testing: is_sale was used to count sale orders, not to limit the revenue sum."""
    problems = revenue_violations(FIXTURE.read_text(encoding="utf-8"))
    assert problems and "SUM(o.items_revenue)" in problems[0]


def test_the_m10_agg_11_error_is_caught():
    sql = (
        "SELECT ROUND(SUM(items_revenue) / NULLIF(COUNT(CASE WHEN is_sale AND item_count > 0 "
        "THEN order_id END), 0), 2) AS avg_order_value FROM analytics.orders "
        "WHERE purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01'"
    )
    assert revenue_violations(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT sum(price) FROM order_items WHERE is_sale",
        "SELECT category, sum(price) FROM order_items WHERE is_sale AND purchase_month = "
        "'2017-03-01' GROUP BY category",
        "SELECT sum(items_revenue) FILTER (WHERE is_sale) FROM orders",
        "SELECT sum(CASE WHEN is_sale THEN items_revenue ELSE 0 END) FROM orders",
        "WITH s AS (SELECT * FROM orders WHERE is_sale) SELECT sum(items_revenue) FROM s",
        "SELECT sum(t.items_revenue) FROM (SELECT items_revenue FROM orders WHERE is_sale) t",
        "SELECT sum(o.items_revenue) FROM orders o JOIN payments p ON p.order_id = o.order_id "
        "AND o.is_sale",
        # explicit status: a question about canceled orders on purpose
        "SELECT sum(items_revenue) FROM orders WHERE order_status = 'canceled'",
        # not revenue at all
        "SELECT sum(freight_total), avg(payment_total) FROM orders",
        "SELECT count(*) FROM orders",
        # a revenue column computed from sales earlier, then averaged
        "WITH m AS (SELECT purchase_month, sum(items_revenue) FILTER (WHERE is_sale) AS revenue "
        "FROM orders GROUP BY 1) SELECT avg(revenue) FROM m",
    ],
)
def test_sales_limited_or_unrelated_queries_pass(sql):
    assert revenue_violations(sql) == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT sum(price) FROM order_items",
        "SELECT avg(items_revenue) FROM orders WHERE purchase_month = '2018-03-01'",
        "SELECT sum(items_revenue), count(*) FILTER (WHERE is_sale) FROM orders",
        "WITH s AS (SELECT * FROM orders WHERE purchase_month = '2018-03-01') "
        "SELECT sum(items_revenue) FROM s",
    ],
)
def test_unlimited_revenue_is_caught(sql):
    assert revenue_violations(sql)


def test_unparsable_sql_never_blocks():
    assert revenue_violations("SELEC sum(price") == []
