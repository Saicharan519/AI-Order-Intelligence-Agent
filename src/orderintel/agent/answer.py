"""Answer writer (FR-07; technical design 2.3 step 7).

The model receives the question, the scope, column names, and at most 50 result rows, and
returns headline / notes / caveats / follow-ups as JSON. Tables and charts are rendered by
code from the rows, never by the model. The grounding check and causal lint run on the
returned text; one regeneration with feedback is allowed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from orderintel.agent.scope import Scope
from orderintel.config import PROJECT_ROOT
from orderintel.evaluation.compare import normalise_value
from orderintel.llm.client import LLMClient

ANSWER_VERSION = "answer-v1"
ANSWER_MAX_TOKENS = 600
MAX_ROWS_TO_MODEL = 50
ANSWER_FILE = PROJECT_ROOT / "prompts" / "answer_v1.md"


@dataclass
class AnswerText:
    headline: str = ""
    notes: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    parse_error: str = ""

    def prose(self) -> str:
        """All model-written text that the grounding check and lint inspect."""
        return "\n".join([self.headline, *self.notes, *self.caveats])


def parse_answer(content: str) -> AnswerText:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError) as e:
        return AnswerText(parse_error=f"answer reply is not a JSON object ({e})")

    def strings(key, limit):
        value = data.get(key) or []
        return [str(v) for v in value][:limit] if isinstance(value, list) else []

    return AnswerText(
        headline=str(data.get("headline") or ""),
        notes=strings("notes", 3),
        caveats=strings("caveats", 5),
        followups=strings("followups", 2),
    )


def answer_messages(
    question: str, scope: Scope, columns: list[str], rows: list[tuple]
) -> list[dict]:
    payload = {
        "question": question,
        "scope": {k: v for k, v in asdict(scope).items() if k != "period_source"},
        "columns": columns,
        "rows": [[normalise_value(v) for v in r] for r in rows[:MAX_ROWS_TO_MODEL]],
        "rows_shown": min(len(rows), MAX_ROWS_TO_MODEL),
        "rows_total": len(rows),
    }
    return [
        {"role": "system", "content": ANSWER_FILE.read_text(encoding="utf-8").strip()},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def write_answer(
    client: LLMClient,
    question: str,
    scope: Scope,
    columns: list[str],
    rows: list[tuple],
    feedback: str | None = None,
    previous: str | None = None,
    config_name: str = "ask",
):
    messages = answer_messages(question, scope, columns, rows)
    if feedback and previous is not None:
        messages += [
            {"role": "assistant", "content": previous},
            {"role": "user", "content": feedback + "\nReturn the corrected JSON object only."},
        ]
    result = client.complete(
        messages,
        config_name=config_name,
        prompt_version=ANSWER_VERSION,
        max_tokens=ANSWER_MAX_TOKENS,
        question=question,
    )
    return parse_answer(result.content), result
