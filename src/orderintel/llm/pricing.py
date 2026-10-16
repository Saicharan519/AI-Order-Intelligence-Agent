"""Token usage and cost (technical design 10.3).

Prices are per 1M tokens, from the providers' official pricing pages (retrieved
2026-10-15). DeepSeek charges half price off-peak; Gemini prices are paid-tier prices used
only for a notional cost, because this project uses Gemini's free tier.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

PRICES_RETRIEVED = "2026-10-15"


@dataclass(frozen=True)
class Price:
    miss: float  # input, cache miss
    hit: float  # input, cache hit
    out: float  # output (including any reasoning tokens)


PRICES: dict[str, dict[str, Price]] = {
    "deepseek-flash": {"peak": Price(0.30, 0.006, 1.20), "offpeak": Price(0.15, 0.003, 0.60)},
    "deepseek-v4-pro": {"peak": Price(1.32, 0.044, 3.96), "offpeak": Price(0.66, 0.022, 1.98)},
    # notional only (free tier is used); no peak/off-peak distinction
    "gemini-3.5-flash-lite": {"peak": Price(0.30, 0.30, 2.50), "offpeak": Price(0.30, 0.30, 2.50)},
}
BILLED_PROVIDERS = {"deepseek"}


def is_deepseek_peak(when: dt.datetime) -> bool:
    """Peak: 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday (Chinese public holidays,
    which are off-peak, are not modelled; treating them as peak over-estimates cost)."""
    utc = when.astimezone(dt.UTC)
    return utc.weekday() < 5 and (1 <= utc.hour < 4 or 6 <= utc.hour < 10)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @classmethod
    def from_response(cls, provider: str, usage: dict | None) -> Usage:
        u = usage or {}
        prompt = int(u.get("prompt_tokens") or 0)
        completion = int(u.get("completion_tokens") or 0)
        if provider == "deepseek":
            hit = int(u.get("prompt_cache_hit_tokens") or 0)
            miss = int(u.get("prompt_cache_miss_tokens") or max(prompt - hit, 0))
            details = u.get("completion_tokens_details") or {}
            reasoning = int(details.get("reasoning_tokens") or 0)
        else:
            # Gemini's compatible endpoint hides thinking tokens; they are the gap between
            # total and prompt + completion (docs/provider_facts.md, finding 3).
            hit, miss = 0, prompt
            total = int(u.get("total_tokens") or prompt + completion)
            reasoning = max(total - prompt - completion, 0)
        return cls(prompt, hit, miss, completion, reasoning)


def price_for(model: str, when: dt.datetime) -> Price:
    table = PRICES.get(model)
    if table is None:
        raise KeyError(f"no price for model {model!r}; add it to PRICES before use")
    return table["peak" if is_deepseek_peak(when) else "offpeak"]


def cost_usd(model: str, usage: Usage, when: dt.datetime) -> float:
    p = price_for(model, when)
    billable_out = usage.completion_tokens + (
        usage.reasoning_tokens if not model.startswith("deepseek") else 0
    )  # DeepSeek's completion_tokens already include reasoning tokens
    return (
        usage.cache_miss_tokens * p.miss + usage.cache_hit_tokens * p.hit + billable_out * p.out
    ) / 1_000_000


def worst_case_cost_usd(model: str, est_input_tokens: int, max_tokens: int) -> float:
    """Upper bound used by the budget guard: peak price, no cache hits, full max_tokens."""
    p = PRICES[model]["peak"]
    return (est_input_tokens * p.miss + max_tokens * p.out) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (about 3 characters per token for English and SQL)."""
    return len(text) // 3 + 1
