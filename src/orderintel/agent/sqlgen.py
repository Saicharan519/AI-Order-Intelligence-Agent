"""SQL-generation prompts for ablation configurations A to D (technical design 8.3).

All configurations share the same rules text, model, and temperature; only the data
description changes:

  A  raw table DDL (comments stripped, so no trap hints leak into the baseline)
  B  A + glossary definitions (term and definition only: the "where implemented" column
     names views that B cannot see)
  C  analytics view documentation (from the database comments) + full glossary
  D  C, plus validator, EXPLAIN gate, and up to two repairs (agent/repair.py)

Prompt layout for caching: the system message (rules + schema + glossary) is identical for
every question in a configuration, so the provider's prefix cache can serve it; the
question goes last, in the user message.
"""

from __future__ import annotations

import re
from functools import lru_cache

from orderintel.config import PROJECT_ROOT
from orderintel.guard.allowlists import load_allowlist

PROMPT_VERSION = "sqlgen-v1"  # final prompt: eval/reviews/prompt_selection.yaml
SQLGEN_MAX_TOKENS = 800
CONFIGS = ("A", "B", "C", "D")

RULES_FILE = PROJECT_ROOT / "prompts" / f"{PROMPT_VERSION.replace('-', '_rules_')}.md"
RAW_DDL_FILE = PROJECT_ROOT / "db" / "migrations" / "001_raw_schema.sql"
GLOSSARY_FILE = PROJECT_ROOT / "glossary" / "glossary.md"


@lru_cache
def raw_ddl() -> str:
    sql = RAW_DDL_FILE.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    lines = [line.rstrip() for line in sql.splitlines()]
    text = "\n".join(line for line in lines if line.strip())
    return "Tables in schema raw (PostgreSQL DDL):\n\n" + text


@lru_cache
def views_doc() -> str:
    lines = ["Views in schema analytics (query only these):"]
    for view, spec in load_allowlist()["views"].items():
        lines.append(f"\nanalytics.{view}: {spec['comment']}")
        for col, meta in spec["columns"].items():
            note = f" -- {meta['comment']}" if meta["comment"] else ""
            lines.append(f"  {col} {meta['type']}{note}")
    return "\n".join(lines)


@lru_cache
def glossary(include_implementation: bool) -> str:
    text = GLOSSARY_FILE.read_text(encoding="utf-8")
    if include_implementation:
        return "Business glossary:\n\n" + text
    out = []
    for line in text.splitlines():
        if line.startswith("Version "):
            continue  # intro paragraph refers to the analytics views, which B cannot see
        line = re.sub(r" \(`[a-z_]+\.[a-z_]+`\)", "", line)  # inline view-column references
        cells = (
            [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|")
            else None
        )
        if cells and len(cells) == 3:
            if set(cells[0]) <= {"-", " "}:
                out.append("|---|---|")
            else:
                out.append(f"| {cells[0]} | {cells[1]} |")
        else:
            out.append(line)
    return "Business glossary (definitions):\n\n" + "\n".join(out)


@lru_cache
def system_prompt(config: str) -> str:
    rules = RULES_FILE.read_text(encoding="utf-8").strip()
    if config == "A":
        parts = [rules, raw_ddl()]
    elif config == "B":
        parts = [rules, raw_ddl(), glossary(include_implementation=False)]
    elif config in ("C", "D"):
        parts = [rules, views_doc(), glossary(include_implementation=True)]
    else:
        raise ValueError(f"unknown configuration {config!r}")
    return "\n\n".join(parts)


def build_messages(config: str, question: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt(config)},
        {"role": "user", "content": question},
    ]


def repair_messages(previous: list[dict], reply: str, feedback: str) -> list[dict]:
    """Config D: show the model its last answer and why it failed, ask for a fix."""
    return previous + [
        {"role": "assistant", "content": reply},
        {
            "role": "user",
            "content": (
                "That SQL could not be used: "
                + feedback
                + "\nReturn the corrected JSON object only."
            ),
        },
    ]


def parse_reply(content: str) -> tuple[str | None, list[str], str | None]:
    """(sql, assumptions, error). Tolerates code fences; never raises."""
    import json

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [], f"reply is not valid JSON ({e.msg})"
    if not isinstance(data, dict):
        return None, [], "reply is not a JSON object"
    sql = data.get("sql")
    assumptions = data.get("assumptions") or []
    if sql is not None and not isinstance(sql, str):
        return None, [], "'sql' must be a string or null"
    return (
        (sql.strip() or None) if isinstance(sql, str) else None,
        [str(a) for a in assumptions],
        None,
    )
