"""Golden question set: schema, loading, and the test-split fingerprint (technical design 8.1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from orderintel.config import PROJECT_ROOT

GOLDEN_DIR = PROJECT_ROOT / "eval" / "golden"
QUESTIONS_FILE = GOLDEN_DIR / "questions.yaml"
TEST_HASH_FILE = GOLDEN_DIR / "test_split.sha256"

Category = Literal["lookup", "aggregate", "trend", "trap", "ambiguous", "out_of_scope"]
Route = Literal["answer", "investigate", "clarify", "refuse"]

CATEGORY_COUNTS = {"lookup": 8, "aggregate": 14, "trend": 12, "trap": 14,
                   "ambiguous": 6, "out_of_scope": 6}
SPLIT_COUNTS = {"dev": 40, "test": 20}


class GoldenItem(BaseModel):
    id: str
    split: Literal["dev", "test"]
    category: Category
    question: str
    reference_sql: str | None = None
    accepted_alternatives: list[str] = Field(default_factory=list)
    ordering: Literal["ordered", "unordered"] = "unordered"
    allow_extra_columns: bool = False
    expected_route: list[Route]
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("expected_route", mode="before")
    @classmethod
    def _route_list(cls, v):
        return [v] if isinstance(v, str) else v

    @model_validator(mode="after")
    def _consistent(self):
        answerable = self.category != "out_of_scope"
        if answerable and not self.reference_sql:
            raise ValueError(f"{self.id}: answerable item needs reference_sql")
        if not answerable and (self.reference_sql or self.expected_route != ["refuse"]):
            raise ValueError(f"{self.id}: out-of-scope item must have no SQL and route refuse")
        return self

    @property
    def answerable(self) -> bool:
        return self.reference_sql is not None

    @property
    def references(self) -> list[str]:
        return [self.reference_sql, *self.accepted_alternatives] if self.reference_sql else []


def load_golden(path: Path = QUESTIONS_FILE) -> list[GoldenItem]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = [GoldenItem.model_validate(d) for d in data]
    ids = [i.id for i in items]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate ids: {sorted(dupes)}")
    return items


def split_fingerprint(items: list[GoldenItem]) -> str:
    """SHA-256 over the canonical JSON of the test items. Any edit changes it."""
    test = sorted((i.model_dump() for i in items if i.split == "test"), key=lambda d: d["id"])
    canonical = json.dumps(test, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
