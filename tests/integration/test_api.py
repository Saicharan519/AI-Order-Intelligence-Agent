"""API contract, tracing, and protection tests (M9) with a FAKE model and the real database.

The fake model uses the Gemini configuration, which is billed at $0, so these tests never
add cost to the real ledger; every row they write is tagged "test:api" and deleted at the
end. Secret values are only handled in memory; assertions compare names, never values.
"""

import json

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orderintel.agent.session import SessionStore
from orderintel.api.app import create_app
from orderintel.config import get_settings
from orderintel.db.connect import connect_agent, connect_owner
from orderintel.llm.budget import Limits, PostgresLedger
from orderintel.llm.client import LLMClient
from orderintel.redact import secret_values
from orderintel.trace.queries import summary
from orderintel.trace.recorder import TraceRecorder
from tests.fixtures.fake_llm import fake_config
from tests.integration.test_ask_fake import CANCELED_SQL, ROUTE_ANSWER, RoleFake

pytestmark = pytest.mark.integration

try:
    with connect_agent() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

CODE = "test-access-code-not-real"
TAG = "test:api"
H = {"X-Access-Code": CODE}
GOOD = RoleFake(
    ROUTE_ANSWER,
    CANCELED_SQL,
    {"headline": "625 orders were canceled.", "notes": [], "caveats": []},
)


def settings(**update):
    base = {"access_code": SecretStr(CODE), "rate_limit_per_ip_per_min": 50}
    return get_settings().model_copy(update={**base, **update})


def make_client(transport=None, limits=None, **update):
    s = settings(**update)
    llm = LLMClient(
        fake_config(limits, name="gemini"),
        PostgresLedger(s),
        None,
        transport or GOOD,
        sleep=lambda x: None,
    )
    app = create_app(
        s, client=llm, recorder=TraceRecorder(s), store=SessionStore(), trace_config=TAG
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    with connect_owner() as conn:
        conn.execute(
            "DELETE FROM trace.requests WHERE config_name LIKE %s AND kind = 'llm_call'", (TAG + '%',)
        )
        conn.execute("DELETE FROM trace.requests WHERE config_name LIKE %s", (TAG + '%',))


def trace_text(request_id: str) -> str:
    """Everything stored for a request (its row, its LLM calls, its steps) as one string."""
    with connect_owner() as conn:
        rows = conn.execute(
            "SELECT row_to_json(r)::text FROM trace.requests r WHERE id = %s OR parent_id = %s",
            (request_id, request_id),
        ).fetchall()
        steps = conn.execute(
            "SELECT payload::text FROM trace.steps WHERE request_id = %s", (request_id,)
        ).fetchall()
    return "\n".join(r[0] for r in rows + steps)


def secret_names_in(text: str) -> list[str]:
    return [name for name, value in secret_values().items() if value in text]


# ---------- contract (FR-01, FR-08) ----------


def test_ask_returns_the_contract_shape():
    r = make_client().post(
        "/v1/ask", json={"question": "How many orders were canceled?"}, headers=H
    )
    assert r.status_code == 200
    body = r.json()
    for key in [
        "request_id",
        "route",
        "headline",
        "components",
        "scope",
        "evidence",
        "caveats",
        "grounding",
        "followups",
        "usage",
    ]:
        assert key in body
    assert body["route"] == "answer" and body["headline"] == "625 orders were canceled."
    scope = body["scope"]
    for key in [
        "period",
        "population",
        "filters",
        "definitions",
        "assumptions",
        "n",
        "partial_period_warnings",
    ]:
        assert key in scope  # FR-08: the scope statement is always present
    ev = body["evidence"][0]
    assert ev["sql"] and ev["validator"]["ok"] and ev["rows_preview"] and "ms" in ev  # FR-10


def test_health_needs_no_code_and_reveals_nothing():
    r = make_client().get("/v1/health")
    assert r.status_code == 200 and r.json() == {
        "status": "ok",
        "database": "ok",
        "llm_enabled": True,
    }


# ---------- access code ----------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/ask"),
        ("get", "/v1/budget"),
        ("get", "/v1/requests/x"),
        ("post", "/v1/sessions/s1/scope/clear"),
    ],
)
def test_protected_endpoints_need_the_code(method, path):
    c = make_client()
    kwargs = {"json": {"question": "hi"}} if path == "/v1/ask" else {}
    assert getattr(c, method)(path, **kwargs).status_code == 401
    wrong = getattr(c, method)(path, headers={"X-Access-Code": "nope"}, **kwargs)
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "unauthorized"


def test_no_access_code_configured_fails_closed():
    c = make_client(access_code=None)
    r = c.post("/v1/ask", json={"question": "hi"}, headers={"X-Access-Code": ""})
    assert r.status_code == 503 and r.json()["error"]["code"] == "access_not_configured"


# ---------- tracing (FR-15, NFR-06) ----------


@pytest.mark.realdata
def test_request_is_traced_end_to_end():
    c = make_client()
    body = c.post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=H).json()
    t = c.get(f"/v1/requests/{body['request_id']}", headers=H)
    assert t.status_code == 200
    trace = t.json()
    assert trace["status"] == "ok" and trace["route"] == "answer"
    kinds = [s["kind"] for s in trace["steps"]]
    assert kinds.count("llm") == 3  # router, SQL generation, answer: linked through parent_id
    assert {"validator", "sql", "grounding", "lint"} <= set(kinds)
    llm = [s for s in trace["steps"] if s["kind"] == "llm"]
    assert all(s["payload"]["tokens_in"] > 0 and s["ms"] is not None for s in llm)
    assert trace["response"]["headline"] == "625 orders were canceled."


def test_secrets_never_reach_traces_or_logs(caplog):
    caplog.set_level("INFO", logger="orderintel.api")
    secret = secret_values()["oi_trace_password"]  # in memory only
    c = make_client()
    body = c.post(
        "/v1/ask",
        json={"question": f"How many orders were canceled? my password is {secret}"},
        headers=H,
    ).json()
    stored = trace_text(body["request_id"])
    assert secret_names_in(stored) == []
    assert "[REDACTED:oi_trace_password]" in stored
    assert secret_names_in(caplog.text) == []


def test_budget_block_is_structured_and_traced():
    c = make_client(limits=Limits(total_cap_usd=0.0001, daily_cap_usd=0.40))
    r = c.post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=H)
    assert r.status_code == 503 and r.json()["error"]["code"] == "budget_exhausted"
    with connect_owner() as conn:
        status, error = conn.execute(
            "SELECT status, error FROM trace.requests WHERE config_name = %s AND kind = 'request' "
            "ORDER BY created_at DESC LIMIT 1",
            (TAG,),
        ).fetchone()
    assert status == "error" and error == "budget_total"


def test_unexpected_error_hides_details():
    def broken(model, messages, params):
        raise RuntimeError("internal detail that must not leak")

    r = make_client(transport=broken).post("/v1/ask", json={"question": "Count orders"}, headers=H)
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "Something went wrong."}}


def test_provider_outage_is_a_502():
    def down(model, messages, params):
        raise httpx_connect_error()

    r = make_client(transport=down).post("/v1/ask", json={"question": "Count orders"}, headers=H)
    assert r.status_code == 502 and r.json()["error"]["code"] == "provider_error"


def httpx_connect_error():
    from openai import APIConnectionError

    return APIConnectionError(request=httpx.Request("POST", "http://fake.invalid"))


# ---------- protections ----------


def test_rate_limit_per_ip():
    c = make_client(rate_limit_per_ip_per_min=2)
    codes = [
        c.post(
            "/v1/ask", json={"question": "How many orders were canceled?"}, headers=H
        ).status_code
        for _ in range(3)
    ]
    assert codes[:2] == [200, 200] and codes[2] == 429


def test_rate_limit_response_has_retry_after():
    c = make_client(rate_limit_per_ip_per_min=1)
    c.post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=H)
    r = c.post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited"


def test_kill_switch_blocks_without_calling_the_model():
    fake = RoleFake(ROUTE_ANSWER, CANCELED_SQL, {"headline": "x", "notes": [], "caveats": []})
    r = make_client(transport=fake, llm_enabled=False).post(
        "/v1/ask", json={"question": "Count orders"}, headers=H
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_disabled"
    assert fake.calls == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"question": ""}, {"question": "x" * 501}, {"question": "ok", "session_id": "bad id!"}],
)
def test_invalid_requests_are_structured_and_do_not_echo_input(payload):
    r = make_client().post("/v1/ask", json=payload, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert "x" * 50 not in r.text and "bad id!" not in r.text


def test_budget_endpoint():
    b = make_client().get("/v1/budget", headers=H).json()
    assert b["total_cap_usd"] == 1.90 and 0 <= b["total_usd"] <= 1.90
    assert b["remaining_total_usd"] == pytest.approx(1.90 - b["total_usd"], abs=1e-6)


def test_scope_clear_and_unknown_requests():
    c = make_client()
    assert c.post("/v1/sessions/s-1/scope/clear", headers=H).json() == {
        "session_id": "s-1",
        "cleared": False,
    }
    assert c.post("/v1/sessions/bad id/scope/clear", headers=H).status_code == 422
    assert c.get("/v1/requests/not-a-uuid", headers=H).status_code == 404
    assert c.get("/v1/requests/00000000-0000-0000-0000-000000000000", headers=H).status_code == 404


def test_admin_summary_query_runs():
    make_client().post("/v1/ask", json={"question": "How many orders were canceled?"}, headers=H)
    out = summary(days=1)
    assert out["requests"] >= 1 and out["p95_ms"] >= out["p50_ms"] >= 0
    assert 0 <= out["rejection_rate"] <= 1
    assert any(r["route"] == "answer" for r in out["routes"])
    json.dumps(out)  # serialisable for the admin script
