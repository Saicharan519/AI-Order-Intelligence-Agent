"""A fake LLM transport for tests: never touches the network, never spends."""

from __future__ import annotations

import json
from collections.abc import Callable

from orderintel.llm.budget import Limits, MemoryLedger
from orderintel.llm.client import LLMClient, ProviderConfig

DEEPSEEK_USAGE = {
    "prompt_tokens": 1860,
    "completion_tokens": 100,
    "prompt_cache_hit_tokens": 1664,
    "prompt_cache_miss_tokens": 196,
}


def fake_config(limits: Limits | None = None, name: str = "deepseek") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model="deepseek-flash" if name == "deepseek" else "gemini-3.5-flash-lite",
        base_url="http://fake.invalid",
        api_key="fake-test-key-not-real",
        params={"temperature": 0},
        limits=limits or Limits(total_cap_usd=1.90, daily_cap_usd=0.40),
    )


class FakeTransport:
    """Replies are produced by `responder(question, call_number)`; JSON dicts are encoded."""

    def __init__(self, responder: Callable[[str, int], dict | str | Exception]):
        self.responder = responder
        self.calls: list[dict] = []

    def __call__(self, model: str, messages: list[dict], params: dict) -> tuple[str, dict]:
        question = next(m["content"] for m in messages if m["role"] == "user")
        self.calls.append({"model": model, "messages": messages, "params": params})
        reply = self.responder(question, len(self.calls))
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return content, dict(DEEPSEEK_USAGE)


def fake_client(responder, cache=None, limits: Limits | None = None, ledger=None):
    transport = FakeTransport(responder)
    client = LLMClient(
        fake_config(limits), ledger or MemoryLedger(), cache, transport, sleep=lambda s: None
    )
    return client, transport
