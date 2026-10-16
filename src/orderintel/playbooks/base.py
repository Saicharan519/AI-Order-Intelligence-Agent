"""Playbook framework (T-7.1; technical design 2.4).

A playbook is a fixed sequence of SQL steps over the analytics views. Parameters are typed
and validated (Pydantic) before use, then substituted into each step's syntax tree as SQL
literals (sqlglot placeholders such as :p_month), never by string formatting. The rendered
SQL then passes the same validator and executor as model-written SQL (FR-04), so playbooks
have no privileged path to the database. Findings are computed in code from step results.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import sqlglot
from pydantic import BaseModel, field_validator
from sqlglot import exp

from orderintel.agent.router import BR_STATES, FIRST_MONTH, LAST_MONTH
from orderintel.db.executor import QueryResult, execute
from orderintel.guard.validator import validate

WINDOW_START = dt.date(2017, 1, 1)
WINDOW_END = dt.date(2018, 9, 1)  # exclusive: the analysis window ends with August 2018
MIN_GROUP = 30  # ranking eligibility (glossary)


class PlaybookParams(BaseModel):
    period: str  # YYYY-MM
    state: str | None = None

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        if len(v) != 7 or not (FIRST_MONTH <= v <= LAST_MONTH):
            raise ValueError(f"period must be a month between {FIRST_MONTH} and {LAST_MONTH}")
        dt.date.fromisoformat(v + "-01")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        if v is None:
            return None
        v = v.upper()
        if v not in BR_STATES:
            raise ValueError(f"unknown state {v!r}")
        return v

    @property
    def month(self) -> dt.date:
        return dt.date.fromisoformat(self.period + "-01")

    def sql_values(self) -> dict[str, object]:
        return {
            "p_month": self.month,
            "state": self.state,
            "w_start": WINDOW_START,
            "w_end": WINDOW_END,
        }


def _literal(value: object) -> exp.Expression:
    if value is None:
        return exp.Null()
    if isinstance(value, dt.date):
        return exp.cast(exp.Literal.string(value.isoformat()), "date")
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, int | float):
        return exp.Literal.number(value)
    if isinstance(value, str):
        return exp.Literal.string(value)
    raise TypeError(f"unsupported parameter type {type(value).__name__}")


def render(sql: str, values: dict[str, object]) -> str:
    """Substitute :name placeholders with typed literals in the syntax tree."""
    tree = sqlglot.parse_one(sql, read="postgres")
    missing = {p.name for p in tree.find_all(exp.Placeholder)} - set(values)
    if missing:
        raise KeyError(f"no value for placeholders {sorted(missing)}")

    def sub(node):
        return _literal(values[node.name]) if isinstance(node, exp.Placeholder) else node

    return tree.transform(sub).sql(dialect="postgres")


@dataclass(frozen=True)
class Step:
    name: str
    sql: str
    only_without_state: bool = False


@dataclass
class StepResult:
    name: str
    sql: str
    columns: list[str]
    rows: list[tuple]
    ms: int

    def as_dicts(self) -> list[dict]:
        return [dict(zip(self.columns, r, strict=True)) for r in self.rows]


@dataclass
class PlaybookRun:
    playbook: str
    params: PlaybookParams
    steps: list[StepResult] = field(default_factory=list)

    def step(self, name: str) -> StepResult | None:
        return next((s for s in self.steps if s.name == name), None)


def run_steps(
    playbook: str, steps: list[Step], params: PlaybookParams, settings=None
) -> PlaybookRun:
    run = PlaybookRun(playbook, params)
    for step in steps:
        if step.only_without_state and params.state:
            continue
        rendered = render(step.sql, params.sql_values())
        v = validate(rendered)
        if not v.ok:  # a playbook step that fails the validator is a bug, not a user error
            raise RuntimeError(f"{playbook}.{step.name} failed validation: {v.feedback()}")
        res: QueryResult = execute(v.validated, settings=settings)
        run.steps.append(StepResult(step.name, v.sql, res.columns, res.rows, res.ms))
    return run


def ratio(num, den) -> float | None:
    return float(num) / float(den) if den else None


def pct(num, den) -> float | None:
    r = ratio(num, den)
    return None if r is None else round(100 * r, 1)
