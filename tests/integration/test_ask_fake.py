"""Ask mode end to end with a FAKE model (no spend) and the real database: every graph edge."""

import json

import psycopg
import pytest

from orderintel.agent.ask import ask, build_graph
from orderintel.agent.session import SessionStore
from orderintel.db.connect import connect_agent
from orderintel.llm.budget import MemoryLedger
from orderintel.llm.client import LLMClient
from tests.fixtures.fake_llm import DEEPSEEK_USAGE, fake_config

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

ROUTE_ANSWER = {"route": "answer", "reason": "aggregate", "params": {}}
CANCELED_SQL = {
    "sql": "SELECT count(*) FROM orders WHERE order_status = 'canceled'",
    "assumptions": ["canceled = order_status canceled"],
}


class RoleFake:
    """Replies by role, recognised from the system prompt; records every call."""

    def __init__(self, router, sqlgen, answer, narrate=None):
        self.replies = {"router": router, "sqlgen": sqlgen, "answer": answer, "narrate": narrate}
        self.calls: list[str] = []
        self.messages: list[list[dict]] = []

    def __call__(self, model, messages, params):
        system = messages[0]["content"]
        role = (
            "router"
            if system.startswith("You route questions")
            else "answer"
            if system.startswith("You write the short answer")
            else "narrate"
            if system.startswith("You narrate")
            else "sqlgen"
        )
        self.calls.append(role)
        self.messages.append(messages)
        n = self.calls.count(role)
        reply = self.replies[role]
        reply = reply(n) if callable(reply) else reply
        return (reply if isinstance(reply, str) else json.dumps(reply)), dict(DEEPSEEK_USAGE)


def run(fake, question="How many orders were canceled?", session_id=None, store=None):
    client = LLMClient(fake_config(), MemoryLedger(), None, fake, sleep=lambda s: None)
    store = store or SessionStore()
    return ask(
        client, question, graph=build_graph(client, store), session_id=session_id, store=store
    )


def test_answer_path_grounded():
    fake = RoleFake(
        ROUTE_ANSWER,
        CANCELED_SQL,
        {"headline": "625 orders were canceled.", "notes": [], "caveats": []},
    )
    r = run(fake)
    assert r.status == "ok" and r.route == "answer"
    assert r.headline == "625 orders were canceled."
    assert r.components[0]["variant"] == "answer_card"
    assert r.grounding.untraced == [] and not r.grounding.regenerated
    assert r.evidence[0].rows_preview == [[625.0]] and r.evidence[0].validator.ok
    assert r.scope.period.source == "default" and r.scope.assumptions
    assert fake.calls == ["router", "sqlgen", "answer"]
    assert r.usage.llm_calls == 3 and r.usage.cost_usd > 0


def test_untraced_number_triggers_one_regeneration():
    answers = {
        1: {"headline": "650 orders were canceled."},
        2: {"headline": "625 orders were canceled."},
    }
    fake = RoleFake(ROUTE_ANSWER, CANCELED_SQL, lambda n: answers[n])
    r = run(fake)
    assert r.grounding.regenerated and r.grounding.untraced == [] and r.warnings == []
    assert fake.calls.count("answer") == 2


def test_persistent_untraced_number_is_shown_as_warning():
    fake = RoleFake(ROUTE_ANSWER, CANCELED_SQL, {"headline": "650 orders were canceled."})
    r = run(fake)
    assert r.status == "ok" and r.grounding.untraced == ["650"]
    assert any("could not be traced" in w for w in r.warnings)
    assert fake.calls.count("answer") == 2  # one regeneration only


def test_causal_wording_is_regenerated_then_flagged():
    fake = RoleFake(
        ROUTE_ANSWER,
        CANCELED_SQL,
        {"headline": "625 orders were canceled because of late deliveries."},
    )
    r = run(fake)
    assert r.grounding.causal_terms == ["because"]
    assert any("causal" in w for w in r.warnings)


def test_refuse_runs_no_sql():
    fake = RoleFake({"route": "refuse", "reason": "forecasting is out of scope"}, CANCELED_SQL, {})
    r = run(fake, "Forecast December 2018 orders.")
    assert r.status == "refused" and r.evidence == []
    assert fake.calls == ["router"]


def test_invalid_router_reply_becomes_clarify_and_runs_no_sql():
    fake = RoleFake("Sure! DROP TABLE raw.orders", CANCELED_SQL, {})
    r = run(fake)
    assert r.route == "clarify" and r.status == "clarify" and fake.calls == ["router"]


def test_sql_failure_after_repairs_gives_no_fabricated_answer():
    bad = {"sql": "SELECT * FROM raw.orders", "assumptions": []}  # VR-04 every time
    fake = RoleFake(ROUTE_ANSWER, bad, {"headline": "should never be called"})
    r = run(fake)
    assert r.status == "sql_failed" and "No answer" in r.headline
    assert "answer" not in fake.calls and fake.calls.count("sqlgen") == 3
    assert r.evidence[0].sql == "SELECT * FROM raw.orders"


def test_sql_model_declines():
    fake = RoleFake(ROUTE_ANSWER, {"sql": None, "assumptions": ["no such data"]}, {})
    r = run(fake)
    assert r.status == "refused" and r.caveats == ["no such data"]


ROUTE_MARCH = {
    "route": "investigate",
    "playbook": "late_delivery_diagnosis",
    "params": {"period": "2018-03", "state": None},
}
GOOD_NARRATION = {
    "headline": "19.0% of 7,003 delivered orders were late versus a 5.8% baseline.",
    "summary_points": [
        "Carrier transit averaged 12.97 days versus 9.06, about 3.9 days longer.",
        "RJ had 864 delivered orders with a 34.5% late rate.",
    ],
    "caveats": ["Associations only."],
    "top_driver": "carrier_transit",
}


def test_investigation_runs_playbook_and_checks_narration():
    fake = RoleFake(ROUTE_MARCH, CANCELED_SQL, {}, GOOD_NARRATION)
    r = run(fake, "Why was March 2018 so bad for deliveries?")
    assert r.status == "ok" and r.route == "investigate"
    report = r.components[0]
    assert report["type"] == "report" and report["verdict"] == "elevated"
    assert report["top_driver"] == "carrier_transit"
    assert (
        report["findings"]["late_orders"] == 1328 and report["findings"]["delivered_orders"] == 7003
    )
    assert r.grounding.untraced == [] and r.warnings == [] and not r.grounding.regenerated
    assert len(r.evidence) == 6 and all(e.kind == "playbook_step" for e in r.evidence)
    assert fake.calls == ["router", "narrate"]  # no SQL generation: playbook SQL is fixed
    assert r.scope.period.start == "2018-03-01" and r.scope.period.end == "2018-03-31"
    assert any(f.inherits_scope for f in r.followups)


def test_narration_with_wrong_driver_and_invented_number_is_regenerated_then_flagged():
    bad = dict(
        GOOD_NARRATION,
        top_driver="seller_handling",
        headline="21.4% were late, mostly due to slow sellers.",
    )
    fake = RoleFake(ROUTE_MARCH, CANCELED_SQL, {}, bad)
    r = run(fake, "Why was March 2018 so bad for deliveries?")
    assert fake.calls.count("narrate") == 2 and r.grounding.regenerated
    assert "21.4%" in r.grounding.untraced
    joined = " ".join(r.warnings)
    assert "different top driver" in joined and "causal" in joined and "traced" in joined


def test_negative_control_verdict():
    route = dict(ROUTE_MARCH, params={"period": "2017-07", "state": None})
    narration = {
        "headline": "July 2017 was not unusual: 2.8% late versus a 7.0% baseline.",
        "summary_points": [],
        "caveats": [],
        "top_driver": "none",
    }
    fake = RoleFake(route, CANCELED_SQL, {}, narration)
    r = run(fake, "Why were deliveries so bad in July 2017?")
    assert r.components[0]["verdict"] == "nothing_notable" and r.warnings == []
    assert r.followups == []


def test_follow_up_inherits_investigation_scope():
    store = SessionStore()
    run(
        RoleFake(ROUTE_MARCH, CANCELED_SQL, {}, GOOD_NARRATION),
        "Why was March 2018 so bad for deliveries?",
        session_id="s1",
        store=store,
    )
    follow_sql = {
        "sql": "SELECT count(*) FROM orders WHERE is_late AND customer_state = 'RJ' "
        "AND purchase_month = '2018-03-01'",
        "assumptions": [],
    }
    fake = RoleFake(ROUTE_ANSWER, follow_sql, {"headline": "298 late orders."})
    r = run(fake, "How many RJ orders were late?", session_id="s1", store=store)
    sql_prompt = fake.messages[fake.calls.index("sqlgen")][-1]["content"]
    assert "Active scope from the previous investigation" in sql_prompt and "2018-03" in sql_prompt
    assert r.scope.filters and "2018-03" in r.scope.filters[0]
    assert not any("may not apply the inherited scope" in w for w in r.warnings)


def test_follow_up_that_drops_the_scope_is_flagged():
    store = SessionStore()
    run(
        RoleFake(ROUTE_MARCH, CANCELED_SQL, {}, GOOD_NARRATION),
        "Why was March 2018 so bad for deliveries?",
        session_id="s2",
        store=store,
    )
    fake = RoleFake(ROUTE_ANSWER, CANCELED_SQL, {"headline": "625 orders were canceled."})
    r = run(fake, "How many orders were canceled?", session_id="s2", store=store)
    assert any("may not apply the inherited scope" in w for w in r.warnings)


def test_cleared_or_other_session_has_no_inherited_scope():
    store = SessionStore()
    run(
        RoleFake(ROUTE_MARCH, CANCELED_SQL, {}, GOOD_NARRATION),
        "Why was March 2018 so bad?",
        session_id="s3",
        store=store,
    )
    assert store.clear("s3")
    fake = RoleFake(ROUTE_ANSWER, CANCELED_SQL, {"headline": "625 orders were canceled."})
    r = run(fake, session_id="s3", store=store)
    assert r.scope.filters == [] and r.warnings == []
    r2 = run(fake, session_id="other", store=store)
    assert r2.scope.filters == []


def test_trend_gets_line_chart_and_partial_month_warning():
    sql = {
        "sql": "SELECT purchase_month, count(*) AS orders FROM orders "
        "WHERE purchase_month >= '2018-06-01' GROUP BY 1 ORDER BY 1",
        "assumptions": [],
    }
    fake = RoleFake(
        ROUTE_ANSWER,
        sql,
        {"headline": "Orders fell from 6,167 in June to 4 in October 2018.", "caveats": []},
    )
    r = run(fake, "Monthly orders since June 2018")
    assert r.components[0]["kind"] == "line"
    assert r.scope.partial_period_warnings == [
        "2018-09 is a partial month (16 orders)",
        "2018-10 is a partial month (4 orders)",
    ]
    assert r.grounding.untraced == []
