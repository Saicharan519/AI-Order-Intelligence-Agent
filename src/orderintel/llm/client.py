"""LLM client (technical design 3 and 10.3): one interface for every provider.

Order of operations for each call:
  1. cache lookup (a hit returns immediately and costs nothing);
  2. dry-run mode returns an estimate without calling;
  3. budget/quota guard with the worst-case cost; a breach raises before any request;
  4. request, with at most two retries on 429/503/connection errors;
  5. usage parsed, cost computed, the call recorded in the ledger, the response cached.

The network call is a pluggable `transport`, so tests use a fake model and never spend.
Secrets: the API key is only passed to the SDK; it is never logged, cached, or returned.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError

from orderintel.config import Settings, get_settings
from orderintel.llm.budget import Ledger, LedgerEntry, Limits, check_limits
from orderintel.llm.cache import ResponseCache, cache_key
from orderintel.llm.pricing import Usage, cost_usd, estimate_tokens, worst_case_cost_usd

RETRYABLE = (RateLimitError, InternalServerError, APIConnectionError)
MAX_RETRIES = 2
BACKOFF_S = (2.0, 6.0)

# transport(model, messages, params) -> (content, usage_dict)
Transport = Callable[[str, list[dict], dict], tuple[str, dict]]


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code  # provider_error | not_configured
        self.message = message


@dataclass(frozen=True)
class ProviderConfig:
    name: str  # deepseek | gemini
    model: str
    base_url: str
    api_key: str | None
    params: dict  # provider-specific fixed request parameters
    limits: Limits


def provider_config(name: str, settings: Settings | None = None, model: str | None = None):
    s = settings or get_settings()
    if name == "deepseek":
        return ProviderConfig(
            name="deepseek",
            model=model or s.deepseek_model_primary,
            base_url=s.deepseek_base_url,
            api_key=s.deepseek_api_key.get_secret_value() if s.deepseek_api_key else None,
            # Thinking is on by default (effort high); disabled so temperature applies and
            # no reasoning tokens are billed (docs/provider_facts.md).
            params={"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}},
            limits=Limits(total_cap_usd=s.llm_total_cap_usd, daily_cap_usd=s.llm_daily_cap_usd),
        )
    if name == "gemini":
        return ProviderConfig(
            name="gemini",
            model=model or s.gemini_model,
            base_url=s.gemini_base_url,
            api_key=s.gemini_api_key.get_secret_value() if s.gemini_api_key else None,
            params={"temperature": 0, "reasoning_effort": "low"},
            limits=Limits(max_rpm=s.gemini_max_rpm, max_rpd=s.gemini_max_requests_per_day),
        )
    raise ValueError(f"unknown provider {name!r}")


def openai_transport(cfg: ProviderConfig) -> Transport:
    if not cfg.api_key:
        raise LLMError("not_configured", f"no API key for {cfg.name} in .env")
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, max_retries=0, timeout=120)

    def call(model: str, messages: list[dict], params: dict) -> tuple[str, dict]:
        r = client.chat.completions.create(model=model, messages=messages, **params)
        usage = r.usage.model_dump() if r.usage else {}
        return r.choices[0].message.content or "", usage

    return call


@dataclass
class LLMResult:
    content: str
    model: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    latency_ms: int = 0
    cached: bool = False
    dry_run: bool = False
    estimated_cost_usd: float = 0.0
    retries: int = 0

    def json(self) -> dict:
        return json.loads(self.content)


class LLMClient:
    def __init__(
        self,
        cfg: ProviderConfig,
        ledger: Ledger,
        cache: ResponseCache | None = None,
        transport: Transport | None = None,
        dry_run: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self.ledger = ledger
        self.cache = cache
        self.dry_run = dry_run
        self._transport = transport
        self._sleep = sleep

    def _get_transport(self) -> Transport:
        if self._transport is None:
            self._transport = openai_transport(self.cfg)
        return self._transport

    def complete(
        self,
        messages: list[dict],
        *,
        config_name: str,
        prompt_version: str,
        max_tokens: int,
        json_output: bool = True,
        question: str | None = None,
        use_cache: bool = True,
    ) -> LLMResult:
        params = dict(self.cfg.params, max_tokens=max_tokens)
        if json_output:
            params["response_format"] = {"type": "json_object"}
        key = cache_key(self.cfg.model, messages, params, prompt_version)

        if use_cache and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return LLMResult(hit["content"], self.cfg.model, Usage(**hit["usage"]), cached=True)

        est_in = estimate_tokens(json.dumps(messages, ensure_ascii=False))
        worst = worst_case_cost_usd(self.cfg.model, est_in, max_tokens)
        if self.dry_run:
            return LLMResult("", self.cfg.model, dry_run=True, estimated_cost_usd=worst)

        check_limits(self.ledger, self.cfg.model, worst, self.cfg.limits)

        transport = self._get_transport()
        started = time.perf_counter()
        retries = 0
        while True:
            try:
                content, raw_usage = transport(self.cfg.model, messages, params)
                break
            except RETRYABLE as e:
                if retries >= MAX_RETRIES:
                    self._record_error(config_name, question, started, type(e).__name__)
                    raise LLMError(
                        "provider_error", f"{type(e).__name__} after {retries} retries"
                    ) from e
                self._sleep(BACKOFF_S[retries])
                retries += 1

        usage = Usage.from_response(self.cfg.name, raw_usage)
        now = dt.datetime.now(dt.UTC)
        billed = cost_usd(self.cfg.model, usage, now) if self.cfg.name == "deepseek" else 0.0
        latency = int((time.perf_counter() - started) * 1000)
        self.ledger.record(
            LedgerEntry(
                config_name, self.cfg.model, "ok", usage, billed, latency, question, created_at=now
            )
        )
        if self.cache is not None:
            self.cache.put(
                key,
                {
                    "content": content,
                    "usage": usage.__dict__,
                    "model": self.cfg.model,
                    "prompt_version": prompt_version,
                },
            )
        return LLMResult(
            content,
            self.cfg.model,
            usage,
            billed,
            latency,
            retries=retries,
            estimated_cost_usd=worst,
        )

    def _record_error(self, config_name, question, started, error):
        latency = int((time.perf_counter() - started) * 1000)
        self.ledger.record(
            LedgerEntry(
                config_name,
                self.cfg.model,
                "error",
                latency_ms=latency,
                question=question,
                error=error,
            )
        )
