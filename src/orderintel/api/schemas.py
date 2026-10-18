"""Response contract for Ask (FR-01, FR-08, FR-10; technical design section 9)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Period(BaseModel):
    start: str
    end: str
    source: Literal["sql", "default", "none"] = "none"


class ScopeOut(BaseModel):
    period: Period | None = None
    population: str | None = None
    filters: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    n: int = 0
    truncated: bool = False
    partial_period_warnings: list[str] = Field(default_factory=list)


class ValidatorOut(BaseModel):
    ok: bool
    rules_checked: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    kind: Literal["sql", "playbook_step"] = "sql"
    sql: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    row_count: int = 0
    rows_preview: list[list[Any]] = Field(default_factory=list)
    validator: ValidatorOut | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    ms: int = 0


class Grounding(BaseModel):
    numbers_checked: int = 0
    untraced: list[str] = Field(default_factory=list)
    causal_terms: list[str] = Field(default_factory=list)
    regenerated: bool = False


class Followup(BaseModel):
    label: str
    question: str
    inherits_scope: bool = False


class UsageOut(BaseModel):
    llm_calls: int = 0
    cached_calls: int = 0
    tokens_in: int = 0
    tokens_cache_hit: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class AskResponse(BaseModel):
    request_id: str
    route: Literal["answer", "investigate", "clarify", "refuse", "about"]
    status: Literal["ok", "clarify", "refused", "sql_failed", "not_available", "error"]
    headline: str
    components: list[dict[str, Any]] = Field(default_factory=list)
    scope: ScopeOut = Field(default_factory=ScopeOut)
    evidence: list[Evidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    grounding: Grounding = Field(default_factory=Grounding)
    followups: list[Followup] = Field(default_factory=list)
    usage: UsageOut = Field(default_factory=UsageOut)
