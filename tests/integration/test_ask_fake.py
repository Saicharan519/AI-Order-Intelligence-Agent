"""Ask mode end to end with a FAKE model (no spend) and the real database: every graph edge."""

import json

import psycopg
import pytest

from orderintel.agent.ask import ask, build_graph
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

    def __init__(self, router, sqlgen, answer):
        self.replies = {"router": router, "sqlgen": sqlgen, "answer": answer}
        self.calls: list[str] = []

    def __call__(self, model, messages, params):
        system = messages[0]["content"]
        role = (
            "router"
            if system.startswith("You route questions")
            else "answer"
            if system.startswith("You write the short answer")
            else "sqlgen"
        )
        self.calls.append(role)
        n = self.calls.count(role)
        reply = self.replies[role]
        reply = reply(n) if callable(reply) else reply
        return (reply if isinstance(reply, str) else json.dumps(reply)), dict(DEEPSEEK_USAGE)


def run(fake, question="How many orders were canceled?"):
    client = LLMClient(fake_config(), MemoryLedger(), None, fake, sleep=lambda s: None)
    return ask(client, question, graph=build_graph(client))


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


def test_investigate_route_is_placeholder_until_m7():
    fake = RoleFake(
        {
            "route": "investigate",
            "playbook": "late_delivery_diagnosis",
            "params": {"period": "2018-03", "state": None},
        },
        CANCELED_SQL,
        {},
    )
    r = run(fake, "Why was March 2018 so bad for deliveries?")
    assert r.status == "not_available" and "2018-03" in r.headline and fake.calls == ["router"]


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
