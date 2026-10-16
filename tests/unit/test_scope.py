"""Scope assembly and output-component rules (FR-08, FR-09, PRD 8.1)."""

import datetime as dt
from decimal import Decimal as D

import pytest

from orderintel.agent.scope import build_scope, choose_components, extract_period

PARTIAL = (
    (dt.date(2016, 9, 1), 4),
    (dt.date(2016, 10, 1), 324),
    (dt.date(2016, 11, 1), 0),
    (dt.date(2016, 12, 1), 1),
    (dt.date(2018, 9, 1), 16),
    (dt.date(2018, 10, 1), 4),
)


@pytest.mark.parametrize(
    ("sql", "start", "end"),
    [
        (
            "SELECT 1 FROM orders WHERE purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01'",
            "2017-01-01",
            "2017-12-31",
        ),
        (
            "SELECT 1 FROM orders WHERE purchase_month BETWEEN '2018-01-01' AND '2018-08-01'",
            "2018-01-01",
            "2018-08-01",
        ),
        (
            "SELECT 1 FROM orders WHERE purchase_date >= DATE '2018-07-01' "
            "AND purchase_date < DATE '2018-08-01'",
            "2018-07-01",
            "2018-07-31",
        ),
        (
            "SELECT 1 FROM orders WHERE extract(year FROM purchase_ts) = 2017",
            "2017-01-01",
            "2017-12-31",
        ),
        ("SELECT count(*) FROM orders", "2016-09-04", "2018-10-17"),
    ],
)
def test_extract_period(sql, start, end):
    s, e, _ = extract_period(sql)
    assert (s.isoformat(), e.isoformat()) == (start, end)


def test_scope_definitions_and_partial_warnings():
    sql = (
        "SELECT purchase_month, avg(is_late::int) FROM orders WHERE is_delivered "
        "AND purchase_month >= '2018-06-01' GROUP BY 1"
    )
    scope = build_scope(sql, ["delivered only"], 5, False, partial=PARTIAL)
    assert scope.period_start == "2018-06-01"
    assert any(d.startswith("Late") for d in scope.definitions)
    assert any(d.startswith("Delivered order") for d in scope.definitions)
    assert scope.partial_period_warnings == [
        "2018-09 is a partial month (16 orders)",
        "2018-10 is a partial month (4 orders)",
    ]
    assert scope.assumptions == ["delivered only"]


def test_no_partial_warning_inside_analysis_window():
    sql = (
        "SELECT 1 FROM orders WHERE purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01'"
    )
    assert build_scope(sql, [], 1, False, partial=PARTIAL).partial_period_warnings == []


def test_component_single_row_is_answer_card():
    c = choose_components(["n"], [(625,)])
    assert c[0]["type"] == "text" and c[0]["variant"] == "answer_card"


def test_component_empty():
    assert choose_components(["n"], [])[0]["variant"] == "empty"


def test_component_time_series_is_line_chart():
    rows = [(dt.date(2017, m, 1), 100 + m) for m in range(1, 13)]
    c = choose_components(["month", "orders"], rows)
    assert c[0] == {"type": "chart", "kind": "line", "x": "month", "y": ["orders"]}
    assert c[1]["type"] == "table"


def test_line_chart_plots_rates_not_counts_when_both_present():
    # regression (M9 end-to-end check, PRD Example 2): counts flattened the rate line
    rows = [(dt.date(2017, m, 1), 4000 + m, 200 + m, 5.0 + m / 10) for m in range(1, 13)]
    c = choose_components(["month", "delivered_orders", "late_orders", "late_rate_pct"], rows)
    assert c[0]["y"] == ["late_rate_pct"]
    assert c[1]["columns"] == ["month", "delivered_orders", "late_orders", "late_rate_pct"]


def test_component_few_groups_table_plus_bar():
    rows = [("SP", 41746), ("RJ", 12852), ("MG", 11635)]
    c = choose_components(["state", "orders"], rows)
    assert [x["type"] for x in c] == ["table", "chart"] and c[1]["kind"] == "bar"


def test_component_many_groups_table_only():
    rows = [(f"cat{i}", D(i)) for i in range(12)]
    assert [x["type"] for x in choose_components(["category", "revenue"], rows)] == ["table"]
