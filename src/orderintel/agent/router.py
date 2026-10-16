"""Router (FR-02, FR-05; technical design 2.3): answer, investigate, clarify, or refuse.

The model's JSON is validated with Pydantic: routes and playbooks are enums, and an
investigation needs a valid month inside the data. Anything invalid becomes "clarify", so
a malformed or manipulated reply can never trigger SQL by itself.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from orderintel.config import PROJECT_ROOT
from orderintel.llm.client import LLMClient

ROUTER_VERSION = "router-v1"
ROUTER_MAX_TOKENS = 300
ROUTER_FILE = PROJECT_ROOT / "prompts" / "router_v1.md"
FIRST_MONTH, LAST_MONTH = "2016-09", "2018-10"
BR_STATES = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

Route = Literal["answer", "investigate", "clarify", "refuse"]
Playbook = Literal["late_delivery_diagnosis", "low_review_diagnosis"]


class InvestigationParams(BaseModel):
    period: str | None = None
    state: str | None = None

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        if v is None:
            return v
        if not re.fullmatch(r"\d{4}-\d{2}", v) or not (FIRST_MONTH <= v <= LAST_MONTH):
            raise ValueError(f"period {v!r} is not a month between {FIRST_MONTH} and {LAST_MONTH}")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        if v in (None, "", "null"):
            return None
        v = v.upper()
        if v not in BR_STATES:
            raise ValueError(f"unknown state {v!r}")
        return v


class RouterDecision(BaseModel):
    route: Route
    reason: str = ""
    clarifying_question: str | None = None
    playbook: Playbook | None = None
    params: InvestigationParams = InvestigationParams()
    fallback: bool = False  # True when the reply was invalid and clarify was forced

    @model_validator(mode="after")
    def _consistent(self):
        if self.route == "investigate" and (self.playbook is None or self.params.period is None):
            raise ValueError("investigate needs a playbook and a period")
        if self.route == "clarify" and not self.clarifying_question:
            self.clarifying_question = "Could you say a bit more about what you want to know?"
        return self


def system_prompt() -> str:
    return ROUTER_FILE.read_text(encoding="utf-8").strip()


def parse_decision(content: str) -> RouterDecision:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data.get("params"), dict):
            data["params"] = {
                k: (None if v in ("null", "") else v) for k, v in data["params"].items()
            }
        if data.get("playbook") in ("null", ""):
            data["playbook"] = None
        return RouterDecision.model_validate(data)
    except (json.JSONDecodeError, ValidationError, AttributeError, TypeError) as e:
        return RouterDecision(
            route="clarify",
            reason=f"router reply was invalid ({type(e).__name__})",
            clarifying_question="Could you rephrase the question?",
            fallback=True,
        )


def route(
    client: LLMClient, question: str, config_name: str = "ask"
) -> tuple[RouterDecision, object]:
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": question},
    ]
    result = client.complete(
        messages,
        config_name=config_name,
        prompt_version=ROUTER_VERSION,
        max_tokens=ROUTER_MAX_TOKENS,
        question=question,
    )
    return parse_decision(result.content), result
