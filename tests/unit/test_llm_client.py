"""LLM client, pricing, budget guard, cache, and retries, with a fake model (no network)."""

import datetime as dt

import httpx
import pytest
from openai import InternalServerError, RateLimitError

from orderintel.llm.budget import LedgerEntry, LimitExceeded, Limits, MemoryLedger
from orderintel.llm.cache import ResponseCache, cache_key
from orderintel.llm.client import LLMError
from orderintel.llm.pricing import Usage, cost_usd, is_deepseek_peak, worst_case_cost_usd
from tests.fixtures.fake_llm import fake_client

MSGS = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q1"}]


def call(client, **kw):
    return client.complete(MSGS, config_name="test", prompt_version="v-test", max_tokens=800, **kw)


def _http_error(cls, status):
    req = httpx.Request("POST", "http://fake.invalid")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


# ---------- pricing ----------
def test_peak_hours():
    assert is_deepseek_peak(dt.datetime(2026, 10, 16, 2, 0, tzinfo=dt.UTC))  # Fri 02:00
    assert is_deepseek_peak(dt.datetime(2026, 10, 16, 9, 59, tzinfo=dt.UTC))
    assert not is_deepseek_peak(dt.datetime(2026, 10, 16, 10, 38, tzinfo=dt.UTC))
    assert not is_deepseek_peak(dt.datetime(2026, 10, 16, 5, 0, tzinfo=dt.UTC))
    assert not is_deepseek_peak(dt.datetime(2026, 10, 17, 2, 0, tzinfo=dt.UTC))  # Saturday


def test_cost_matches_calibration_measurement():
    # sqlgen_canceled at 10:38 UTC Friday (off-peak) cost $0.000319 (docs/provider_facts.md)
    u = Usage.from_response(
        "deepseek",
        {
            "prompt_tokens": 1853,
            "completion_tokens": 68,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 1853,
        },
    )
    when = dt.datetime(2026, 10, 16, 10, 38, tzinfo=dt.UTC)
    assert cost_usd("deepseek-flash", u, when) == pytest.approx(0.000319, abs=1e-6)
    assert cost_usd("deepseek-flash", u, when.replace(hour=2)) == pytest.approx(0.000638, abs=1e-6)


def test_cache_hits_are_cheaper():
    when = dt.datetime(2026, 10, 16, 12, tzinfo=dt.UTC)
    miss = Usage(1860, 0, 1860, 100)
    hit = Usage(1860, 1664, 196, 100)
    assert cost_usd("deepseek-flash", hit, when) < cost_usd("deepseek-flash", miss, when) / 2


def test_usage_parsing_per_provider():
    ds = Usage.from_response(
        "deepseek",
        {
            "prompt_tokens": 44,
            "completion_tokens": 26,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 44,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    )
    assert ds.reasoning_tokens == 20 and ds.cache_miss_tokens == 44
    gm = Usage.from_response(
        "gemini", {"prompt_tokens": 1988, "completion_tokens": 169, "total_tokens": 3185}
    )
    assert gm.reasoning_tokens == 1028  # hidden thinking tokens (provider_facts finding 3)


def test_worst_case_is_an_upper_bound():
    when = dt.datetime(2026, 10, 16, 2, tzinfo=dt.UTC)  # peak
    actual = cost_usd("deepseek-flash", Usage(3000, 0, 3000, 800), when)
    assert worst_case_cost_usd("deepseek-flash", 3000, 800) >= actual


# ---------- client ----------
def test_successful_call_records_usage_and_cost():
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1", "assumptions": []})
    r = call(client)
    assert r.json()["sql"] == "SELECT 1"
    assert not r.cached and r.cost_usd > 0
    assert len(client.ledger.entries) == 1 and client.ledger.entries[0].status == "ok"
    assert transport.calls[0]["params"]["response_format"] == {"type": "json_object"}
    assert transport.calls[0]["params"]["max_tokens"] == 800


def test_cache_hit_makes_no_call_and_costs_nothing(tmp_path):
    cache = ResponseCache(tmp_path)
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1"}, cache=cache)
    first, second = call(client), call(client)
    assert len(transport.calls) == 1
    assert second.cached and second.cost_usd == 0 and second.content == first.content
    assert len(client.ledger.entries) == 1  # cached calls are not billed


def test_cache_key_changes_with_prompt_version_and_params():
    base = cache_key("m", MSGS, {"t": 0}, "v1")
    assert base != cache_key("m", MSGS, {"t": 0}, "v2")
    assert base != cache_key("m", MSGS, {"t": 1}, "v1")
    assert base != cache_key("other", MSGS, {"t": 0}, "v1")


def test_no_cache_flag_forces_a_call(tmp_path):
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1"}, cache=ResponseCache(tmp_path))
    call(client)
    call(client, use_cache=False)
    assert len(transport.calls) == 2


def test_api_key_is_never_cached(tmp_path):
    client, _ = fake_client(lambda q, n: {"sql": "SELECT 1"}, cache=ResponseCache(tmp_path))
    call(client)
    for f in tmp_path.rglob("*.json"):
        assert "fake-test-key-not-real" not in f.read_text(encoding="utf-8")


def test_total_budget_blocks_before_any_request():
    ledger = MemoryLedger()
    ledger.record(LedgerEntry("old", "deepseek-flash", "ok", cost_usd=1.8999))
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1"}, ledger=ledger)
    with pytest.raises(LimitExceeded) as e:
        call(client)
    assert e.value.code == "budget_total"
    assert transport.calls == []


def test_daily_budget_blocks():
    client, transport = fake_client(
        lambda q, n: {"sql": "SELECT 1"}, limits=Limits(total_cap_usd=1.9, daily_cap_usd=0.0001)
    )
    with pytest.raises(LimitExceeded) as e:
        call(client)
    assert e.value.code == "budget_daily" and transport.calls == []


def test_quota_rpm_blocks():
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1"}, limits=Limits(max_rpm=2))
    call(client, use_cache=False)
    call(client, use_cache=False)
    with pytest.raises(LimitExceeded) as e:
        call(client, use_cache=False)
    assert e.value.code == "quota_rpm" and len(transport.calls) == 2


def test_retries_then_succeeds():
    def responder(q, n):
        return _http_error(RateLimitError, 429) if n == 1 else {"sql": "SELECT 1"}

    client, transport = fake_client(responder)
    r = call(client)
    assert r.retries == 1 and len(transport.calls) == 2


def test_retries_are_bounded_and_recorded():
    client, transport = fake_client(lambda q, n: _http_error(InternalServerError, 503))
    with pytest.raises(LLMError) as e:
        call(client)
    assert e.value.code == "provider_error"
    assert len(transport.calls) == 3  # first try + two retries
    assert client.ledger.entries[-1].status == "error"


def test_dry_run_makes_no_call():
    client, transport = fake_client(lambda q, n: {"sql": "SELECT 1"})
    client.dry_run = True
    r = call(client)
    assert r.dry_run and r.estimated_cost_usd > 0 and transport.calls == []
