"""Investigation narration (T-7.4; FR-11): the model explains findings computed in code.

Checks on every narration: number grounding against the findings, top-driver agreement
(the narrated driver must equal the computed one), and the causal-language lint. One
regeneration with feedback is allowed; anything still failing becomes a visible warning.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from orderintel.agent.grounding import (
    causal_findings,
    check_against,
    extract_numbers,
    pair_derivations,
)
from orderintel.config import PROJECT_ROOT
from orderintel.llm.client import LLMClient, LLMResult

NARRATE_VERSION = "narrate-v1"
NARRATE_MAX_TOKENS = 800
NARRATE_FILE = PROJECT_ROOT / "prompts" / "narrate_v1.md"


@dataclass
class Narration:
    headline: str = ""
    summary_points: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    top_driver: str | None = None
    parse_error: str = ""

    def prose(self) -> str:
        return "\n".join([self.headline, *self.summary_points, *self.caveats])


@dataclass
class NarrationCheck:
    numbers_checked: int
    untraced: list[str]
    causal_terms: list[str]
    driver_agrees: bool

    @property
    def ok(self) -> bool:
        return not self.untraced and not self.causal_terms and self.driver_agrees


def parse_narration(content: str) -> Narration:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        d = json.loads(text)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError) as e:
        return Narration(parse_error=f"narration is not a JSON object ({e})")
    points = d.get("summary_points") or []
    caveats = d.get("caveats") or []
    return Narration(
        headline=str(d.get("headline") or ""),
        summary_points=[str(p) for p in points][:5] if isinstance(points, list) else [],
        caveats=[str(c) for c in caveats][:6] if isinstance(caveats, list) else [],
        top_driver=str(d["top_driver"]) if d.get("top_driver") is not None else None,
    )


def findings_numbers(obj) -> list[float]:
    """Every number in the findings, flattened (nested lists and dicts included)."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out += findings_numbers(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            out += findings_numbers(v)
    return out


COMPARABLE_PAIRS = [  # findings fields a narrator may compare with each other
    ("late_rate", "baseline_rate"),
    ("rate", "baseline_rate"),
    ("value", "baseline"),
    ("one_star_share", "one_star_share_baseline"),
    ("avg_score", "avg_score_baseline"),
    ("review_avg_late", "review_avg_on_time"),
    ("one_star_share_late", "one_star_share_on_time"),
    ("late_orders", "delivered_orders"),
    ("rate_excluding_top2_states", "baseline_rate"),
]


def narration_allowed(findings: dict, question: str) -> set[float]:
    """Allowed numbers for a narration: every findings value (and its percentage form),
    plus comparisons between RELATED fields only: a value and its own baseline
    (x / x_baseline), the pairs above, and the same pairs inside each group entry.
    Arbitrary cross-field arithmetic is not allowed: with dozens of numbers it would make
    almost any invented number "traceable"."""
    numbers = findings_numbers(findings)
    allowed = set(numbers) | {v * 100 for v in numbers} | {v / 100 for v in numbers}

    def add_pairs(d: dict):
        for key, value in d.items():
            other = d.get(f"{key}_baseline")
            if isinstance(value, int | float) and isinstance(other, int | float):
                allowed.update(pair_derivations(float(value), float(other)))
        for a, b in COMPARABLE_PAIRS:
            va, vb = d.get(a), d.get(b)
            if isinstance(va, int | float) and isinstance(vb, int | float):
                allowed.update(pair_derivations(float(va), float(vb)))
        for v in d.values():
            if isinstance(v, dict):
                add_pairs(v)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, dict):
                        add_pairs(x)

    add_pairs(findings)
    for text in (question, findings.get("period") or ""):
        allowed.update(n.value for n in extract_numbers(text))
    return allowed


def check_narration(n: Narration, findings: dict, question: str) -> NarrationCheck:
    g = check_against(n.prose(), narration_allowed(findings, question))
    return NarrationCheck(
        g.numbers_checked,
        g.untraced,
        causal_findings(n.prose()),
        (n.top_driver or "none") == findings.get("top_driver", "none"),
    )


def narrate_messages(question: str, findings: dict) -> list[dict]:
    return [
        {"role": "system", "content": NARRATE_FILE.read_text(encoding="utf-8").strip()},
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "findings": findings}, ensure_ascii=False, default=str
            ),
        },
    ]


def narrate(
    client: LLMClient, question: str, findings: dict, config_name: str = "ask"
) -> tuple[Narration, NarrationCheck, list[LLMResult], bool]:
    messages = narrate_messages(question, findings)
    results = []
    r = client.complete(
        messages,
        config_name=config_name,
        prompt_version=NARRATE_VERSION,
        max_tokens=NARRATE_MAX_TOKENS,
        question=question,
    )
    results.append(r)
    n = parse_narration(r.content)
    check = check_narration(n, findings, question)
    regenerated = False
    if n.parse_error or not check.ok:
        problems = [n.parse_error] if n.parse_error else []
        if check.untraced:
            problems.append("these numbers are not in the findings: " + ", ".join(check.untraced))
        if check.causal_terms:
            problems.append("avoid causal wording: " + ", ".join(check.causal_terms))
        if not check.driver_agrees:
            problems.append(f"top_driver must be exactly {findings.get('top_driver')!r}")
        retry = messages + [
            {"role": "assistant", "content": r.content},
            {
                "role": "user",
                "content": "Please fix: "
                + "; ".join(problems)
                + "\nReturn the corrected JSON object only.",
            },
        ]
        r = client.complete(
            retry,
            config_name=config_name,
            prompt_version=NARRATE_VERSION,
            max_tokens=NARRATE_MAX_TOKENS,
            question=question,
        )
        results.append(r)
        n = parse_narration(r.content)
        check = check_narration(n, findings, question)
        regenerated = True
    return n, check, results, regenerated
