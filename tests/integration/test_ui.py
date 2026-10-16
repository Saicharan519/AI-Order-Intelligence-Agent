"""UI tests (T-9.3, T-9.5; FR-10, Q-08), headless with Streamlit's AppTest.

The responses the UI renders are REAL API responses: produced by the actual API, agent,
validator, and database with a fake model (billed at $0, rows tagged and deleted). A fake
API object then replays them to the UI, so the UI is tested against the true contract.
"""

from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from orderintel.agent.session import SessionStore
from orderintel.api.app import create_app
from orderintel.config import get_settings
from orderintel.db.connect import connect_agent, connect_owner
from orderintel.llm.budget import PostgresLedger
from orderintel.llm.client import LLMClient
from orderintel.ui.view import ERROR_MESSAGES, STATUS_MESSAGES, ApiResult, to_number, usage_line
from tests.fixtures.fake_llm import fake_config
from tests.integration.test_ask_fake import GOOD_NARRATION, ROUTE_ANSWER, ROUTE_MARCH, RoleFake

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

APP = str(Path(__file__).parents[2] / "src" / "orderintel" / "ui" / "app.py")
CODE = "test-access-code-not-real"
TAG = "test:ui"
EX1, EX2, EX3 = (
    "Top 5 categories by revenue in 2017",
    "How is the late-delivery rate trending?",
    "Why was March 2018 so bad for deliveries?",
)
TOP5_SQL = {
    "sql": "SELECT category, round(sum(price), 2) AS revenue FROM order_items "
    "WHERE is_sale AND purchase_date >= '2017-01-01' AND purchase_date < '2018-01-01' "
    "GROUP BY category ORDER BY revenue DESC LIMIT 5",
    "assumptions": ["revenue = item price of sale orders"],
}
TREND_SQL = {
    "sql": "SELECT purchase_month, round(100.0 * count(*) FILTER (WHERE is_late) / count(*), 2) "
    "AS late_rate_pct FROM orders WHERE is_delivered AND purchase_month >= '2017-01-01' "
    "AND purchase_month < '2018-09-01' GROUP BY purchase_month ORDER BY purchase_month",
    "assumptions": [],
}
NO_NUMBERS = {"headline": "Bed, bath and table led 2017 revenue.", "notes": [], "caveats": []}
TREND = {"headline": "The late-delivery rate peaked in early 2018.", "notes": [], "caveats": []}
UNTRACED = {"headline": "Revenue reached 123,456,789 in 2017.", "notes": [], "caveats": []}


def real_response(fake, question):
    s = get_settings().model_copy(update={"access_code": SecretStr(CODE)})
    llm = LLMClient(fake_config(name="gemini"), PostgresLedger(s), None, fake, sleep=lambda x: None)
    c = TestClient(create_app(s, client=llm, store=SessionStore(), trace_config=TAG))
    r = c.post("/v1/ask", json={"question": question}, headers={"X-Access-Code": CODE})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def responses():
    out = {
        EX1: real_response(RoleFake(ROUTE_ANSWER, TOP5_SQL, NO_NUMBERS), EX1),
        EX2: real_response(RoleFake(ROUTE_ANSWER, TREND_SQL, TREND), EX2),
        EX3: real_response(RoleFake(ROUTE_MARCH, {}, {}, GOOD_NARRATION), EX3),
        "untraced": real_response(RoleFake(ROUTE_ANSWER, TOP5_SQL, UNTRACED), "revenue 2017"),
        "clarify": real_response(
            RoleFake({"route": "clarify", "reason": "ambiguous", "options": ["a", "b"]}, {}, {}),
            "What about sales?",
        ),
        "sql_failed": real_response(
            RoleFake(ROUTE_ANSWER, {"sql": "SELECT * FROM raw.customers", "assumptions": []}, {}),
            "Show me customers",
        ),
    }
    with connect_owner() as conn:
        conn.execute(
            "DELETE FROM trace.requests WHERE config_name LIKE %s AND kind = 'llm_call'", (TAG + '%',)
        )
        conn.execute("DELETE FROM trace.requests WHERE config_name LIKE %s", (TAG + '%',))
    return out


class FakeApi:
    def __init__(self, responses, error=None):
        self.responses, self.error = responses, error
        self.asked: list[tuple[str, str]] = []
        self.cleared: list[str] = []

    def ask(self, code, question, session_id):
        self.asked.append((code, question))
        if self.error:
            return ApiResult(False, error_code=self.error, status_code=503)
        return ApiResult(True, data=self.responses[question], status_code=200)

    def budget(self, code):
        return ApiResult(
            True,
            data={"total_usd": 0.06, "today_usd": 0.01, "total_cap_usd": 1.9, "daily_cap_usd": 0.4},
            status_code=200,
        )

    def clear_scope(self, code, session_id):
        self.cleared.append(session_id)
        return ApiResult(True, data={"cleared": True}, status_code=200)


def start(api):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["api"] = api
    at.run()
    at.text_input(key="access_code").set_value(CODE).run()
    return at


def click_example(at, i):
    at.button(key=f"example_{i}").click().run()
    return at


def texts(at) -> str:
    parts = [
        m.value
        for kind in ("markdown", "caption", "info", "warning", "error", "subheader")
        for m in getattr(at, kind)
    ]
    return "\n".join(str(p) for p in parts)


# ---------- the three PRD examples (T-9.4) ----------


def test_example_1_table_bar_chart_scope_and_evidence(responses):
    api = FakeApi(responses)
    at = click_example(start(api), 0)
    assert api.asked == [(CODE, EX1)]  # the typed code is what is sent
    assert at.subheader[0].value == "Bed, bath and table led 2017 revenue."
    df = at.dataframe[0].value
    assert list(df.columns) == ["category", "revenue"] and len(df) == 5
    assert df["revenue"].dtype.kind == "f"  # decimals rendered as numbers, not strings
    assert len(at.get("vega_lite_chart")) == 1  # bar chart
    assert any("Period: 2017-01-01 to 2017-12-31" in m.value for m in at.markdown)
    assert "SELECT" in at.code[0].value  # FR-10: SQL visible
    assert any("validator: passed" in m.value for m in at.markdown)
    assert "model calls" in texts(at)


def test_example_2_line_chart(responses):
    at = click_example(start(FakeApi(responses)), 1)
    assert len(at.get("vega_lite_chart")) == 1
    assert len(at.dataframe[0].value) == 20  # January 2017 to August 2018


def test_example_3_report_scope_bar_and_clear(responses):
    api = FakeApi(responses)
    at = click_example(start(api), 2)
    labels = [m.label for m in at.metric]
    assert "Late rate" in labels and "Delivered orders" in labels
    assert any("Verdict:" in m.value and "carrier transit" in m.value for m in at.markdown)
    assert any(m.value.startswith("Session scope") for m in at.info)
    assert len(at.code) == 7  # every playbook step's SQL is shown
    at.button(key=next(b.key for b in at.button if b.label == "Clear scope")).click().run()
    assert api.cleared and not any(m.value.startswith("Session scope") for m in at.info)


def test_followup_button_asks_the_followup(responses):
    api = FakeApi({**responses})
    at = click_example(start(api), 2)
    fu = responses[EX3]["followups"][0]
    api.responses[fu["question"]] = responses[EX1]
    at.button(key="followup_0").click().run()
    at.run()
    assert api.asked[-1] == (CODE, fu["question"])


# ---------- error states (T-9.5) ----------


@pytest.mark.parametrize(
    "code", ["budget_exhausted", "rate_limited", "llm_disabled", "unauthorized"]
)
def test_api_errors_are_explained(responses, code):
    at = click_example(start(FakeApi(responses, error=code)), 0)
    assert at.error[0].value == ERROR_MESSAGES[code]
    assert not at.subheader  # no stale result


@pytest.mark.parametrize("key,status", [("clarify", "clarify"), ("sql_failed", "sql_failed")])
def test_status_messages(responses, key, status):
    at = start(FakeApi({EX1: responses[key]}))
    at = click_example(at, 0)
    assert responses[key]["status"] == status
    level, msg = STATUS_MESSAGES[status]
    assert msg in [m.value for m in getattr(at, level)]


def test_untraced_number_warning(responses):
    assert responses["untraced"]["grounding"]["untraced"]
    at = click_example(start(FakeApi({EX1: responses["untraced"]})), 0)
    assert any("could not be traced" in w.value for w in at.warning)


def test_access_code_is_never_rendered(responses):
    at = click_example(start(FakeApi(responses)), 0)
    assert CODE not in texts(at)
    assert at.text_input(key="access_code").proto.type == 1  # TextInput.PASSWORD


# ---------- view helpers ----------


def test_view_helpers():
    assert to_number("497971.12") == 497971.12 and to_number("12") == 12 and to_number("SP") == "SP"
    line = usage_line(
        {
            "llm_calls": 3,
            "cached_calls": 1,
            "tokens_in": 5000,
            "tokens_out": 120,
            "cost_usd": 0.00031,
            "latency_ms": 2800,
        }
    )
    assert line == "3 model calls, 1 cached · 5,000 tokens in, 120 out · $0.00031 · 2.8 s"


def test_local_mode_uses_the_server_code_without_showing_it(responses, monkeypatch):
    # The test sets its own fake code, so it never depends on (or touches) the real one.
    fake_code = "local-mode-test-code-not-real"
    monkeypatch.setenv("ACCESS_CODE", fake_code)
    monkeypatch.setattr("sys.argv", ["app.py", "--local"])
    get_settings.cache_clear()
    try:
        api = FakeApi(responses)
        at = AppTest.from_file(APP, default_timeout=90)
        at.session_state["api"] = api
        at.run()
        assert not [t for t in at.text_input if t.key == "access_code"]  # no field to type
        at.button(key="example_0").click().run()
        assert api.asked[0][0] == fake_code
        assert fake_code not in texts(at)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_dollar_amounts_are_not_read_as_math():
    from orderintel.ui.view import md

    assert md("R$497,971 and R$486,519") == r"R\$497,971 and R\$486,519"
