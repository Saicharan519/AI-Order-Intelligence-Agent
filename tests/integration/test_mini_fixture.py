"""Synthetic mini fixture (M7 part 2): planted anomalies and data traps.

Builds the separate database orderintel_mini (scripts/build_mini_db.py) and runs the
late-delivery playbook on it, without any model calls. Two planted anomalies must be found
with the right driver and location (SC-08); control months and an unplanted rebuild must
report nothing notable, so a detection cannot come from the fixture itself.
"""

import psycopg
import pytest

from orderintel.db.connect import connect_eval, connect_superuser
from orderintel.playbooks import late_delivery
from orderintel.playbooks.base import PlaybookParams
from scripts.build_mini_db import build, mini_settings
from tests.fixtures.mini_olist.generate import OTHER_SELLERS, PLANT_SELLER, PLANTS, TRAPS

pytestmark = pytest.mark.integration


def _server_available() -> bool:
    try:
        with connect_superuser() as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


if not _server_available():
    pytest.skip("database server not reachable", allow_module_level=True)


def run(period, state=None):
    return late_delivery.run(PlaybookParams(period=period, state=state), settings=mini_settings())[
        1
    ]


@pytest.fixture(scope="module")
def planted():
    build(plants=True)
    return mini_settings()


# ---------- planted anomalies ----------


def test_planted_transit_detected_for_the_state(planted):
    t = PLANTS["transit"]
    f = run(t["month"], t["state"])
    assert f.verdict == "elevated"
    assert f.top_driver == "carrier_transit"
    assert f.transit_days - f.transit_days_baseline > 8  # most of the +10 days shows up
    assert abs(f.handling_days - f.handling_days_baseline) < 0.5


def test_planted_transit_state_ranked_first_without_a_state_filter(planted):
    f = run(PLANTS["transit"]["month"])
    assert f.verdict == "elevated"
    assert f.top_driver == "carrier_transit"
    assert f.top_states[0].name == PLANTS["transit"]["state"]
    assert f.systemic is False  # concentrated in one state, not spread everywhere


def test_planted_handling_detected_and_seller_named(planted):
    f = run(PLANTS["handling"]["month"])
    assert f.verdict == "elevated"
    assert f.top_driver == "seller_handling"
    assert f.top_sellers[0].name == PLANT_SELLER
    # the planted seller stands out clearly; the others sit at their own baseline
    assert f.top_sellers[0].excess_late_orders >= 20
    assert all(s.excess_late_orders <= 3 for s in f.top_sellers[1:])
    assert len(f.top_sellers) == 3 and {s.name for s in f.top_sellers[1:]} <= set(OTHER_SELLERS)


@pytest.mark.parametrize("period,state", [("2017-06", None), ("2017-06", "RJ"), ("2018-01", "SP")])
def test_control_months_report_nothing_notable(planted, period, state):
    f = run(period, state)
    assert f.verdict == "nothing_notable"
    assert f.top_driver == "none"


def test_small_state_sample_is_not_judged(planted):
    f = run("2018-01", "MG")  # 60 delivered orders, below the 100-order minimum
    assert f.verdict == "insufficient_data"
    assert any("too few to judge" in c for c in f.caveats)


# ---------- data traps (views neutralise each one) ----------


def q(sql, *params):
    with connect_eval(mini_settings()) as conn:
        return conn.execute(sql, params).fetchall()


def test_trap_multi_payment_is_one_row(planted):
    rows = q(
        "SELECT payment_count, payment_types FROM analytics.payments WHERE order_id = %s",
        TRAPS["multi_payment_order"],
    )
    assert rows == [(2, "credit_card+voucher")]


def test_trap_duplicate_review_keeps_the_latest(planted):
    rows = q(
        "SELECT review_score FROM analytics.reviews WHERE order_id = %s",
        TRAPS["duplicate_review_order"],
    )
    assert rows == [(2,)]


def test_trap_categories_null_and_untranslated(planted):
    rows = q(
        "SELECT product_id, category FROM analytics.order_items WHERE product_id IN (%s, %s)",
        TRAPS["null_category_product"],
        TRAPS["untranslated_product"],
    )
    assert dict(rows) == {
        TRAPS["null_category_product"]: "unknown",
        TRAPS["untranslated_product"]: "pc_gamer",
    }


def test_trap_multi_seller_and_same_day_and_missing_date(planted):
    rows = dict(
        (r[0], r[1:])
        for r in q(
            "SELECT order_id, seller_count, is_delivered, delivery_days, review_score "
            "FROM analytics.orders WHERE order_id IN (%s, %s, %s, %s)",
            TRAPS["multi_seller_order"],
            TRAPS["same_day_order"],
            TRAPS["delivered_no_date_order"],
            TRAPS["no_review_order"],
        )
    )
    assert rows[TRAPS["multi_seller_order"]][0] == 2
    assert rows[TRAPS["same_day_order"]][1] is True and rows[TRAPS["same_day_order"]][2] < 1
    assert rows[TRAPS["delivered_no_date_order"]][1] is False  # status delivered, no date
    assert rows[TRAPS["no_review_order"]][3] is None


def test_trap_empty_months_are_visible(planted):
    rows = dict(
        q("SELECT month, orders_count FROM analytics.data_coverage WHERE month < '2017-01-01'")
    )
    assert [str(m)[:7] for m, n in sorted(rows.items()) if n == 0] == ["2016-11", "2016-12"]


def test_agent_role_sees_only_the_views_on_the_fixture(planted):
    from orderintel.db.connect import connect_agent

    with connect_agent(planted) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT count(*) FROM raw.orders")


# ---------- counterfactual: the same fixture without the plants ----------


@pytest.fixture(scope="module")
def unplanted(planted):
    build(plants=False)
    yield mini_settings()
    build(plants=True)  # leave the database in its usual, planted state


@pytest.mark.parametrize("period,state", [("2018-03", "RJ"), ("2018-03", None), ("2017-10", None)])
def test_without_plants_nothing_is_detected(unplanted, period, state):
    f = run(period, state)
    assert f.verdict == "nothing_notable", (period, state, f.late_rate, f.baseline_rate)


def test_no_playbook_finding_contradicts_another_in_any_month(planted):
    """Both playbooks, every month of the data (including the partial edges)."""
    from orderintel.db.connect import connect_agent
    from orderintel.playbooks import PLAYBOOKS
    from orderintel.playbooks.base import PlaybookParams
    from orderintel.playbooks.checks import inconsistencies

    with connect_agent(planted) as c:
        months = [
            m[0].isoformat()[:7]
            for m in c.execute("SELECT month FROM analytics.data_coverage ORDER BY 1").fetchall()
        ]
    found = {}
    for name, module in PLAYBOOKS.items():
        for m in months:
            _, f = module.run(PlaybookParams(period=m), planted)
            if problems := inconsistencies(f.as_dict()):
                found[(name, m)] = problems
    assert found == {}


@pytest.mark.realdata
def test_no_contradictions_on_the_real_data_including_partial_months():
    """The real data has the partial edge months (Sep 2016, Oct 2018) the bug appeared in.
    Partial months and the first and last month of the analysis window (all 26 months take
    two and a half minutes and add nothing: the window months share the same code path)."""
    from orderintel.db.connect import connect_agent
    from orderintel.playbooks import PLAYBOOKS
    from orderintel.playbooks.checks import inconsistencies

    with connect_agent() as c:
        months = [
            m[0].isoformat()[:7]
            for m in c.execute(
                "SELECT month FROM analytics.data_coverage WHERE is_partial OR month IN "
                "((SELECT min(month) FROM analytics.data_coverage WHERE in_analysis_window),"
                " (SELECT max(month) FROM analytics.data_coverage WHERE in_analysis_window))"
                " ORDER BY 1"
            ).fetchall()
        ]
    assert len(months) >= 3
    found = {}
    for name, module in PLAYBOOKS.items():
        for m in months:
            _, f = module.run(PlaybookParams(period=m))
            if problems := inconsistencies(f.as_dict()):
                found[(name, m)] = problems
    assert found == {}
