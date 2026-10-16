"""M0b calibration: ten small calls to an LLM provider (Q-02).

Measures latency, token usage (including cache hits and reasoning tokens), thinking
controls, JSON output, and realistic SQL-generation prompts. API keys are read from .env
and never printed. Uses development-split questions only.

    python scripts/calibrate.py --provider deepseek   # primary (paid, cost under $0.01)
    python scripts/calibrate.py --provider gemini     # second provider (free tier)
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from dotenv import dotenv_values
from openai import OpenAI, OpenAIError

from orderintel.config import PROJECT_ROOT
from orderintel.guard.allowlists import load_allowlist

ENV = dotenv_values(PROJECT_ROOT / ".env")

TINY = [{"role": "user", "content": 'Reply with exactly this JSON and nothing else: {"ok": true}'}]


def schema_prompt() -> str:
    lines = ["PostgreSQL views in schema analytics (query only these):"]
    for view, spec in load_allowlist()["views"].items():
        lines.append(f"\n{view}: {spec['comment']}")
        for col, meta in spec["columns"].items():
            note = f" -- {meta['comment']}" if meta["comment"] else ""
            lines.append(f"  {col} {meta['type']}{note}")
    glossary = (PROJECT_ROOT / "glossary" / "glossary.md").read_text(encoding="utf-8")
    return "\n".join(lines) + "\n\nBusiness glossary:\n" + glossary


def sql_messages(question: str) -> list[dict]:
    system = (
        "You write one PostgreSQL SELECT over the analytics views to answer the question. "
        'Return only JSON: {"sql": "...", "assumptions": ["..."]}.\n\n' + schema_prompt()
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


JSON_OBJECT = {"type": "json_object"}

# DeepSeek: thinking is ON by default (effort high); disabled explicitly on every call
# except one control call that shows what the default costs.
NO_THINK = {"extra_body": {"thinking": {"type": "disabled"}}}
DEEPSEEK_CALLS: list[tuple[str, str, dict]] = [
    ("latency_1", "primary", {"messages": TINY, **NO_THINK}),
    ("latency_2", "primary", {"messages": TINY, **NO_THINK}),
    ("latency_3", "primary", {"messages": TINY, **NO_THINK}),
    ("thinking_default_control", "primary", {"messages": TINY}),
    (
        "json_object",
        "primary",
        {
            "messages": [
                {
                    "role": "user",
                    "content": 'Capital of Brazil as JSON {"city": "...", "state": "..."}.',
                }
            ],
            "response_format": JSON_OBJECT,
            **NO_THINK,
        },
    ),
    (
        "sqlgen_canceled",
        "primary",
        {
            "messages": sql_messages("How many orders were canceled?"),
            "response_format": JSON_OBJECT,
            **NO_THINK,
        },
    ),
    (
        "sqlgen_late_rate",
        "primary",
        {
            "messages": sql_messages("What is the overall late-delivery rate, as a percentage?"),
            "response_format": JSON_OBJECT,
            **NO_THINK,
        },
    ),
    (
        "sqlgen_canceled_repeat_cache",
        "primary",
        {
            "messages": sql_messages("How many orders were canceled?"),
            "response_format": JSON_OBJECT,
            **NO_THINK,
        },
    ),
    (
        "sqlgen_monthly",
        "primary",
        {
            "messages": sql_messages("Show the number of orders per month in 2017."),
            "response_format": JSON_OBJECT,
            **NO_THINK,
        },
    ),
    ("comparison_model", "comparison", {"messages": TINY, **NO_THINK}),
]

GEMINI_THINK_LOW = {"reasoning_effort": "low"}
GEMINI_CALLS: list[tuple[str, str, dict]] = [
    ("latency_1", "primary", {"messages": TINY, **GEMINI_THINK_LOW}),
    ("latency_2", "primary", {"messages": TINY, **GEMINI_THINK_LOW}),
    ("latency_3", "primary", {"messages": TINY, **GEMINI_THINK_LOW}),
    ("thinking_minimal", "primary", {"messages": TINY, "reasoning_effort": "minimal"}),
    ("thinking_none", "primary", {"messages": TINY, "reasoning_effort": "none"}),
    (
        "thinking_visible",
        "primary",
        {
            "messages": TINY,
            "extra_body": {
                "extra_body": {
                    "google": {
                        "thinking_config": {"thinking_level": "low", "include_thoughts": True}
                    }
                }
            },
        },
    ),
    (
        "json_schema",
        "primary",
        {
            "messages": [
                {"role": "user", "content": "Give the capital of Brazil and its state code."}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "city",
                    "schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}, "state": {"type": "string"}},
                        "required": ["city", "state"],
                    },
                },
            },
            **GEMINI_THINK_LOW,
        },
    ),
    (
        "sqlgen_low",
        "primary",
        {
            "messages": sql_messages("How many orders were canceled?"),
            "response_format": JSON_OBJECT,
            **GEMINI_THINK_LOW,
        },
    ),
    (
        "sqlgen_medium",
        "primary",
        {
            "messages": sql_messages("What is the overall late-delivery rate, as a percentage?"),
            "response_format": JSON_OBJECT,
            "reasoning_effort": "medium",
        },
    ),
    ("comparison_model", "comparison", {"messages": TINY, **GEMINI_THINK_LOW}),
]

PROVIDERS = {
    "deepseek": {
        "key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "models": {"primary": "DEEPSEEK_MODEL_PRIMARY", "comparison": "DEEPSEEK_MODEL_COMPARISON"},
        "calls": DEEPSEEK_CALLS,
        "spacing_s": 1.0,
    },
    "gemini": {
        "key": "GEMINI_API_KEY",
        "base_url": "GEMINI_BASE_URL",
        "models": {"primary": "GEMINI_MODEL", "comparison": "GEMINI_MODEL"},
        "calls": GEMINI_CALLS,
        "spacing_s": 6.0,  # 10 calls per minute, below the 12 RPM cap
    },
}


def redact(text: str, key: str) -> str:
    return text.replace(key, "[REDACTED]") if key else text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    args = parser.parse_args(argv)
    cfg = PROVIDERS[args.provider]
    key = ENV.get(cfg["key"]) or ""
    if not key:
        print(f"{cfg['key']} is empty in .env; add the key first.")
        return 1

    client = OpenAI(api_key=key, base_url=ENV[cfg["base_url"]], max_retries=0, timeout=120)
    models = {role: ENV[var] for role, var in cfg["models"].items()}
    results = []
    for i, (name, which, kwargs) in enumerate(cfg["calls"]):
        if i:
            time.sleep(cfg["spacing_s"])
        started = time.perf_counter()
        row = {"call": name, "model": models[which]}
        try:
            r = client.chat.completions.create(
                model=models[which], temperature=0, max_tokens=2048, **kwargs
            )
            msg = r.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            row |= {
                "ok": True,
                "seconds": round(time.perf_counter() - started, 2),
                "finish_reason": r.choices[0].finish_reason,
                "usage": r.usage.model_dump() if r.usage else None,
                "content_chars": len(content),
                "reasoning_chars": len(reasoning),
                "content_preview": content[:400],
            }
        except OpenAIError as e:
            row |= {
                "ok": False,
                "seconds": round(time.perf_counter() - started, 2),
                "error": type(e).__name__,
                "status": getattr(e, "status_code", None),
                "message": redact(str(e), key)[:300],
            }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))

    out = PROJECT_ROOT / "eval" / "cache" / f"calibration_{args.provider}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(r["ok"] for r in results)
    print(f"\n{ok} of {len(results)} calls succeeded; raw results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
