"""Run an ablation configuration over a golden split and score it (M5, FR-17).

Execution accuracy is computed over answerable items only (PRD section 11): a run is
correct if its result matches the reference or any accepted alternative under the M3
comparer. Out-of-scope items are routing cases (M6) and are not sent in M5.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from orderintel.agent.pipeline import SQLRun, run_question
from orderintel.agent.sqlgen import PROMPT_VERSION, SQLGEN_MAX_TOKENS, build_messages
from orderintel.config import PROJECT_ROOT
from orderintel.db.connect import connect_eval
from orderintel.evaluation.compare import compare_results, normalise_value
from orderintel.evaluation.golden import GoldenItem, load_golden
from orderintel.evaluation.stats import percentile, wilson_interval
from orderintel.llm.client import LLMClient
from orderintel.llm.pricing import PRICES, estimate_tokens

RESULTS_DIR = PROJECT_ROOT / "eval" / "results"


@dataclass
class ItemResult:
    id: str
    category: str
    split: str
    question: str
    status: str
    correct: bool
    reason: str
    sql: str | None
    assumptions: list[str]
    repairs: int
    attempts: list[dict]
    row_count: int
    rows_preview: list[list]
    cost_usd: float
    latency_ms: int
    tokens_in: int
    tokens_cache_hit: int
    tokens_out: int
    llm_calls: int
    cached_calls: int
    failure_tag: str = ""  # set by manual review; auto_tag is a starting suggestion
    auto_tag: str = ""


@dataclass
class RunSummary:
    config: str
    split: str
    model: str
    prompt_version: str
    started_at: str
    n: int
    ran: int
    correct: int
    accuracy: float
    ci95: tuple[float, float]
    by_category: dict[str, dict]
    repairs_used: int
    cost_usd: float
    llm_calls: int
    cached_calls: int
    latency_p50_ms: float
    latency_p95_ms: float
    items: list[ItemResult] = field(default_factory=list)


def answerable_items(split: str, ids: list[str] | None = None) -> list[GoldenItem]:
    items = [i for i in load_golden() if i.split == split and i.answerable]
    if ids:
        items = [i for i in items if i.id in ids]
    return items


def reference_rows(item: GoldenItem) -> list[list[tuple]]:
    with connect_eval() as conn:
        return [conn.execute(sql).fetchall() for sql in item.references]


def score(item: GoldenItem, run: SQLRun, refs: list[list[tuple]]) -> tuple[bool, str]:
    if not run.ran:
        return False, run.status + (f": {run.error}" if run.error else "")
    reasons = []
    for ref in refs:
        c = compare_results(
            ref,
            run.rows,
            ordered=item.ordering == "ordered",
            allow_extra_columns=item.allow_extra_columns,
        )
        if c.match:
            return True, ""
        reasons.append(c.reason)
    return False, reasons[0]


def auto_tag(run: SQLRun, correct: bool) -> str:
    if correct:
        return ""
    return {
        "declined": "over_refusal",
        "parse_error": "other",
        "rejected": "wrong_table_or_column",
        "exec_error": "dialect_error",
    }.get(run.status, "needs_review")


def run_config(
    client: LLMClient, config: str, split: str, ids: list[str] | None = None, progress=print
) -> RunSummary:
    items = answerable_items(split, ids)
    started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    results: list[ItemResult] = []
    for item in items:
        run = run_question(client, config, item.question, label=f"eval:{split}")
        correct, reason = score(item, run, reference_rows(item))
        preview = [[normalise_value(v) for v in row] for row in run.rows[:5]]
        res = ItemResult(
            id=item.id,
            category=item.category,
            split=item.split,
            question=item.question,
            status=run.status,
            correct=correct,
            reason=reason,
            sql=run.sql,
            assumptions=run.assumptions,
            repairs=run.repairs,
            attempts=[asdict(a) for a in run.attempts],
            row_count=len(run.rows),
            rows_preview=preview,
            cost_usd=round(run.cost_usd, 8),
            latency_ms=run.latency_ms,
            tokens_in=run.tokens_in,
            tokens_cache_hit=run.tokens_cache_hit,
            tokens_out=run.tokens_out,
            llm_calls=run.llm_calls,
            cached_calls=run.cached_calls,
            auto_tag=auto_tag(run, correct),
        )
        results.append(res)
        progress(
            f"  {config} {item.id:<10} {'CORRECT' if correct else 'wrong  '} "
            f"{run.status:<11} repairs={run.repairs} ${run.cost_usd:.5f}"
            + ("" if correct else f"  ({reason[:70]})")
        )
    return summarise(config, split, client.cfg.model, started, results)


def summarise(config, split, model, started, results: list[ItemResult]) -> RunSummary:
    n = len(results)
    correct = sum(r.correct for r in results)
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r.category, {"n": 0, "correct": 0})
        c["n"] += 1
        c["correct"] += r.correct
    latencies = [r.latency_ms for r in results if r.cached_calls < r.llm_calls]
    return RunSummary(
        config=config,
        split=split,
        model=model,
        prompt_version=PROMPT_VERSION,
        started_at=started,
        n=n,
        ran=sum(r.status == "ok" for r in results),
        correct=correct,
        accuracy=correct / n if n else 0.0,
        ci95=wilson_interval(correct, n),
        by_category=by_cat,
        repairs_used=sum(r.repairs for r in results),
        cost_usd=round(sum(r.cost_usd for r in results), 6),
        llm_calls=sum(r.llm_calls for r in results),
        cached_calls=sum(r.cached_calls for r in results),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        items=results,
    )


def save(summary: RunSummary, provider: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{summary.split}_{summary.config}_{provider}.json"
    path.write_text(
        json.dumps(asdict(summary), indent=1, ensure_ascii=False, default=str),
        encoding="utf-8",
        newline="\n",
    )
    return path


def estimate(
    config: str,
    split: str,
    model: str,
    ids: list[str] | None = None,
    expected_output_tokens: int = 150,
) -> dict:
    """Cost estimate before a paid run: expected (prefix cached after the first call,
    off-peak) and worst case (peak, no cache, every D item using both repairs, full
    max_tokens)."""
    items = answerable_items(split, ids)
    p_off, p_peak = PRICES[model]["offpeak"], PRICES[model]["peak"]
    system_tokens = estimate_tokens(build_messages(config, "")[0]["content"])
    calls_expected = len(items) * (1.2 if config == "D" else 1.0)
    calls_worst = len(items) * (3 if config == "D" else 1)
    expected = worst = 0.0
    for k, item in enumerate(items):
        q_tokens = estimate_tokens(item.question)
        miss = system_tokens + q_tokens if k == 0 else q_tokens
        hit = 0 if k == 0 else system_tokens
        expected += (miss * p_off.miss + hit * p_off.hit + expected_output_tokens * p_off.out) / 1e6
        worst += ((system_tokens + q_tokens) * p_peak.miss + SQLGEN_MAX_TOKENS * p_peak.out) / 1e6
    if config == "D":
        expected *= 1.2
        worst *= 3
    return {
        "config": config,
        "split": split,
        "items": len(items),
        "calls_expected": round(calls_expected),
        "calls_worst": calls_worst,
        "system_prompt_tokens": system_tokens,
        "expected_usd": round(expected, 5),
        "worst_case_usd": round(worst, 5),
    }
