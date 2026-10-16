"""M2 numeric acceptance: the analytics views reproduce the figures computed independently on
raw tables in M1 (scripts/check_counts.py) and the PRD examples.

All queries run as oi_agent, i.e. through exactly the path the product will use.
"""

from decimal import Decimal

import psycopg
import pytest

from orderintel.db.connect import connect_agent

pytestmark = [pytest.mark.integration, pytest.mark.realdata]


@pytest.fixture(scope="module")
def q():
    try:
        conn = connect_agent()
    except psycopg.Error:
        pytest.skip("database not reachable")
    with conn:
        yield lambda sql: conn.execute(sql).fetchall()


def test_grain_one_row_per_key(q):
    assert q("SELECT count(*), count(DISTINCT order_id) FROM orders") == [(99_441, 99_441)]
    assert q("SELECT count(*), count(DISTINCT order_id) FROM payments") == [(99_440, 99_440)]
    assert q("SELECT count(*), count(DISTINCT order_id) FROM reviews") == [(98_673, 98_673)]
    assert q("SELECT count(*) FROM order_items") == [(112_650,)]
    assert q("SELECT count(*) FROM sellers") == [(3_095,)]


def test_delivered_and_late_by_date(q):
    assert q(
        "SELECT count(*) FILTER (WHERE is_delivered), count(*) FILTER (WHERE is_late), "
        "round(100.0 * avg(is_late::int), 2) FROM orders"
    ) == [(96_470, 6_534, Decimal("6.77"))]
    # is_late is NULL (not false) for orders that were not delivered
    assert q("SELECT count(*) FROM orders WHERE NOT is_delivered AND is_late IS NOT NULL") == [(0,)]


def test_payments_view_prevents_fan_out(q):
    total = Decimal("13591643.70")
    assert q("SELECT sum(items_revenue) FROM orders") == [(total,)]
    assert q("SELECT sum(price) FROM order_items") == [(total,)]
    # the same join that inflated revenue by 4.54% on raw tables is now harmless
    assert q("SELECT sum(i.price) FROM order_items i LEFT JOIN payments p USING (order_id)") == [
        (total,)
    ]


def test_2017_revenue_definition(q):
    assert q(
        "SELECT sum(price), count(DISTINCT order_id) FROM order_items "
        "WHERE is_sale AND purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01'"
    ) == [(Decimal("6108492.27"), 44_375)]


def test_prd_example_1_top_categories_2017(q):
    rows = q(
        """WITH t AS (
             SELECT category, sum(price) rev, count(DISTINCT order_id) n FROM order_items
             WHERE is_sale AND purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01'
             GROUP BY 1)
           SELECT category, round(rev)::int, round(100 * rev / sum(rev) OVER (), 1), n
           FROM t ORDER BY rev DESC LIMIT 5"""
    )
    assert rows == [
        ("bed_bath_table", 497_971, Decimal("8.2"), 4_496),
        ("watches_gifts", 486_519, Decimal("8.0"), 2_114),
        ("health_beauty", 481_143, Decimal("7.9"), 3_382),
        ("sports_leisure", 447_547, Decimal("7.3"), 3_621),
        ("computers_accessories", 400_491, Decimal("6.6"), 2_606),
    ]


def test_prd_example_2_monthly_late_rate(q):
    rows = q(
        "SELECT round(100.0 * avg(is_late::int), 1) FROM orders "
        "WHERE is_delivered AND purchase_month BETWEEN '2017-01-01' AND '2018-08-01' "
        "GROUP BY purchase_month ORDER BY purchase_month"
    )
    expected = [2.9, 3.0, 4.6, 6.6, 3.0, 3.0, 2.8, 2.9, 4.4, 4.2,
                12.4, 7.5, 5.7, 14.1, 19.0, 4.5, 6.6, 1.2, 3.4, 6.2]
    assert [float(r[0]) for r in rows] == expected


def test_prd_example_3_headline_march_2018(q):
    assert q(
        "SELECT count(*) FILTER (WHERE is_late), count(*) FROM orders "
        "WHERE is_delivered AND purchase_month = '2018-03-01'"
    ) == [(1_328, 7_003)]


def test_customers_are_people(q):
    assert q("SELECT count(DISTINCT customer_unique_id) FROM orders") == [(96_096,)]


def test_multi_seller_orders(q):
    assert q("SELECT count(*) FROM orders WHERE seller_count > 1") == [(1_278,)]


def test_categories_unknown_and_untranslated(q):
    rows = dict(q(
        "SELECT category, count(DISTINCT product_id) FROM order_items "
        "WHERE category IN ('unknown', 'pc_gamer', "
        "'portateis_cozinha_e_preparadores_de_alimentos') GROUP BY 1"
    ))
    assert rows["unknown"] == 610
    assert set(rows) == {"unknown", "pc_gamer", "portateis_cozinha_e_preparadores_de_alimentos"}
    assert q("SELECT count(*) FROM order_items WHERE category IS NULL") == [(0,)]


def test_impossible_stage_durations_are_null(q):
    assert q(
        "SELECT count(*) FILTER (WHERE seller_handling_days < 0), "
        "count(*) FILTER (WHERE carrier_transit_days < 0), "
        "count(*) FILTER (WHERE seller_handling_days IS NULL AND carrier_ts IS NOT NULL), "
        "count(*) FILTER (WHERE carrier_transit_days IS NULL "
        "AND carrier_ts IS NOT NULL AND delivered_ts IS NOT NULL) FROM orders"
    ) == [(0, 0, 166, 23)]


def test_orders_without_items_have_zero_revenue(q):
    assert q("SELECT count(*), sum(items_revenue) FROM orders WHERE item_count = 0") == [
        (775, Decimal("0"))
    ]


def test_latest_review_kept_per_order(q):
    assert q("SELECT round(avg(review_score), 2), count(review_score) FROM orders") == [
        (Decimal("4.09"), 98_673)
    ]


def test_data_coverage_flags_partial_and_empty_months(q):
    rows = q("SELECT to_char(month, 'YYYY-MM'), orders_count FROM data_coverage "
             "WHERE is_partial ORDER BY month")
    assert rows == [("2016-09", 4), ("2016-10", 324), ("2016-11", 0), ("2016-12", 1),
                    ("2018-09", 16), ("2018-10", 4)]
    assert q("SELECT count(*) FROM data_coverage WHERE in_analysis_window") == [(20,)]
    assert q("SELECT bool_and(NOT is_partial) FROM data_coverage WHERE in_analysis_window") == [
        (True,)
    ]
