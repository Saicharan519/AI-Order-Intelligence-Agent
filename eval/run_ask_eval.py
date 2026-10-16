"""Ask-mode evaluation (T-6.7): routing (SC-07), faithfulness (SC-06), latency (SC-10).

Runs every golden item (both splits; routing and faithfulness are measured, nothing is
tuned on the test split) plus PRD Examples 1 and 2 through the full Ask graph.

    python eval/run_ask_eval.py --estimate
    python eval/run_ask_eval.py --approved [--ids id1,id2]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orderintel.agent.ask import ask, build_graph  # noqa: E402
from orderintel.agent.router import ROUTER_MAX_TOKENS, system_prompt  # noqa: E402
from orderintel.config import PROJECT_ROOT, get_settings  # noqa: E402
from orderintel.evaluation.ablation import reference_rows  # noqa: E402
from orderintel.evaluation.compare import compare_results  # noqa: E402
from orderintel.evaluation.golden import load_golden  # noqa: E402
from orderintel.evaluation.stats import percentile, wilson_interval  # noqa: E402
from orderintel.llm.budget import LimitExceeded, PostgresLedger  # noqa: E402
from orderintel.llm.cache import ResponseCache  # noqa: E402
from orderintel.llm.client import LLMClient, LLMError, provider_config  # noqa: E402
from orderintel.llm.pricing import PRICES, estimate_tokens  # noqa: E402

OUT = PROJECT_ROOT / "eval" / "results" / "ask_all_deepseek.json"
REPORT = PROJECT_ROOT / "eval" / "reports" / "ask_eval.md"
EXAMPLES = [
    ("prd_example_1", "Top 5 categories by revenue in 2017"),
    ("prd_example_2", "How is the late-delivery rate trending?"),
]


def estimate(n_items: int, model: str) -> dict:
    p = PRICES[model]["offpeak"]
    router_in = estimate_tokens(system_prompt()) + 30
    answer_in = 1200  # rules + scope + up to 50 rows
    expected = (
        n_items * ((router_in * p.miss + 80 * p.out) + (answer_in * p.miss + 150 * p.out)) / 1e6
    )
    worst_p = PRICES[model]["peak"]
    worst = (
        n_items
        * (
            (router_in * worst_p.miss + ROUTER_MAX_TOKENS * worst_p.out)
            + 2 * (3000 * worst_p.miss + 600 * worst_p.out)
            + 3 * (3200 * worst_p.miss + 800 * worst_p.out)
        )
        / 1e6
    )
    return {"items": n_items, "expected_usd": round(expected, 4), "worst_case_usd": round(worst, 4)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--approved", action="store_true")
    ap.add_argument("--ids", help="comma-separated golden ids (subset)")
    ap.add_argument(
        "--recheck",
        action="store_true",
        help="re-run the current checkers on the stored answers (no model calls)",
    )
    args = ap.parse_args(argv)
    if args.recheck:
        rows = json.loads(OUT.read_text(encoding="utf-8"))["items"]
        rechecked = recheck(rows)
        write_report(rows, rechecked)
        for x in rechecked:
            if x["untraced"] != x["original_untraced"] or x["causal"] != x["original_causal"]:
                print(
                    f"  {x['id']}: untraced {x['original_untraced']} -> {x['untraced']}; "
                    f"causal {x['original_causal']} -> {x['causal']}"
                )
        print(
            f"re-checked {len(rechecked)} answers: "
            f"{sum(not x['untraced'] for x in rechecked)} fully traced, "
            f"{sum(bool(x['causal']) for x in rechecked)} with causal wording"
        )
        return 0

    items = load_golden()
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i.id in wanted]
    examples = [] if args.ids else EXAMPLES
    cfg = provider_config("deepseek")
    if args.estimate:
        e = estimate(len(items) + len(examples), cfg.model)
        print(
            f"{e['items']} questions: expected ${e['expected_usd']:.4f}, "
            f"worst case ${e['worst_case_usd']:.4f} (SQL calls mostly cached from M5)"
        )
        return 0
    if not args.approved:
        print("Refusing to make paid calls without --approved.")
        return 1

    client = LLMClient(cfg, PostgresLedger(), ResponseCache(get_settings().llm_cache_dir))
    graph = build_graph(client)
    rows = []
    for gid, question, item in [(i.id, i.question, i) for i in items] + [
        (eid, q, None) for eid, q in examples
    ]:
        try:
            r = ask(client, question, config_name="eval:ask", graph=graph)
        except (LimitExceeded, LLMError) as e:
            print(f"STOPPED at {gid}: {e}")
            break
        route_ok = item is None or r.route in item.expected_route
        sql_correct = None
        if item is not None and item.answerable and r.status == "ok":
            preview_sql = r.evidence[0].sql
            from orderintel.agent.pipeline import eval_execute

            _, result_rows, _ = eval_execute(preview_sql)
            sql_correct = any(
                compare_results(
                    ref,
                    result_rows,
                    ordered=item.ordering == "ordered",
                    allow_extra_columns=item.allow_extra_columns,
                ).match
                for ref in reference_rows(item)
            )
        rows.append(
            {
                "id": gid,
                "split": item.split if item else "example",
                "category": item.category if item else "example",
                "question": question,
                "expected_route": item.expected_route if item else ["answer"],
                "route": r.route,
                "status": r.status,
                "route_ok": route_ok,
                "sql_correct": sql_correct,
                "headline": r.headline,
                "notes": r.notes,
                "caveats": r.caveats,
                "warnings": r.warnings,
                "grounding": r.grounding.model_dump(),
                "components": [
                    c["type"] + ":" + str(c.get("kind", c.get("variant", ""))) for c in r.components
                ],
                "scope": r.scope.model_dump(),
                "sql": r.evidence[0].sql if r.evidence else None,
                "usage": r.usage.model_dump(),
            }
        )
        print(
            f"  {gid:<14} route={r.route:<11}{'ok ' if route_ok else 'BAD'} status={r.status:<10}"
            f" untraced={r.grounding.untraced} regen={r.grounding.regenerated} "
            f"{r.usage.latency_ms} ms ${r.usage.cost_usd:.5f}"
        )

    OUT.write_text(
        json.dumps(
            {"run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "items": rows},
            indent=1,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
        newline="\n",
    )
    write_report(rows)
    return 0


def recheck(rows: list[dict]) -> list[dict]:
    """Re-run the CURRENT grounding check and lint on the stored final answers (no model
    calls): their SQL is executed again for the evidence rows. Used when a checker is fixed
    after a run, so both the original and the re-checked result can be reported."""
    from orderintel.agent.grounding import causal_findings, check_grounding
    from orderintel.agent.pipeline import eval_execute

    out = []
    for r in rows:
        if r["status"] != "ok" or not r["sql"]:
            continue
        _, evidence_rows, _ = eval_execute(r["sql"])
        scope = r["scope"]
        context = [
            r["question"],
            scope["period"]["start"],
            scope["period"]["end"],
            str(scope["n"]),
            *scope["partial_period_warnings"],
            *scope["assumptions"],
        ]
        prose = "\n".join([r["headline"], *r["notes"], *r["caveats"]])
        g = check_grounding(prose, evidence_rows, context)
        out.append(
            {
                "id": r["id"],
                "untraced": g.untraced,
                "causal": causal_findings(prose),
                "original_untraced": r["grounding"]["untraced"],
                "original_causal": r["grounding"]["causal_terms"],
            }
        )
    return out


def write_report(rows: list[dict], rechecked: list[dict] | None = None) -> None:
    labelled = [r for r in rows if r["split"] != "example"]
    routed_ok = sum(r["route_ok"] for r in labelled)
    answered = [r for r in rows if r["status"] == "ok"]
    faithful = sum(not r["grounding"]["untraced"] for r in answered)
    first_try = sum(
        not r["grounding"]["untraced"] and not r["grounding"]["regenerated"] for r in answered
    )
    causal = sum(bool(r["grounding"]["causal_terms"]) for r in answered)
    lat = [r["usage"]["latency_ms"] for r in rows]
    cost = sum(r["usage"]["cost_usd"] for r in rows)
    scored = [r for r in answered if r["sql_correct"] is not None]
    lo, hi = wilson_interval(routed_ok, len(labelled))
    flo, fhi = wilson_interval(faithful, len(answered))
    lines = [
        "# Ask-mode evaluation (M6)",
        "",
        "Generated by `eval/run_ask_eval.py`: every golden item (both splits) plus PRD Examples "
        "1 and 2 through the full Ask graph (router, SQL with validator and repairs, answer "
        "writer, grounding check, causal lint). Model `deepseek-flash`, thinking disabled.",
        "",
        "| Metric | Result | Target |",
        "|---|---|---|",
        f"| Routing (SC-07) | {routed_ok}/{len(labelled)} = {routed_ok / len(labelled):.0%} "
        f"(CI {lo:.0%}-{hi:.0%}) | ≥ 90% |",
        f"| Faithfulness: answers with no untraced number after ≤ 1 regeneration (SC-06) | "
        f"{faithful}/{len(answered)} = {faithful / len(answered):.0%} "
        f"(CI {flo:.0%}-{fhi:.0%}) | ≥ 95% |",
        f"| Faithful on the first try (no regeneration) | {first_try}/{len(answered)} | — |",
        f"| Answers still using causal wording | {causal}/{len(answered)} | 0 |",
        f"| SQL correct among answered golden items | {sum(r['sql_correct'] for r in scored)}/"
        f"{len(scored)} | — |",
        f"| Latency p50 / p95, full Ask (SC-10) | {percentile(lat, 50) / 1000:.1f} s / "
        f"{percentile(lat, 95) / 1000:.1f} s | p95 ≤ 20 s |",
        f"| Cost, all {len(rows)} questions | ${cost:.4f} "
        f"(${cost / len(rows):.5f} per question) | — |",
        "",
        "## Routing errors",
        "",
    ]
    bad = [r for r in labelled if not r["route_ok"]]
    lines += [
        f"- `{r['id']}` ({r['category']}): expected {r['expected_route']}, got "
        f"`{r['route']}`: {r['question']}"
        for r in bad
    ] or ["None."]
    lines += ["", "## Answers with untraced numbers (after regeneration)", ""]
    unt = [r for r in answered if r["grounding"]["untraced"]]
    lines += [f'- `{r["id"]}`: {r["grounding"]["untraced"]} in "{r["headline"]}"' for r in unt] or [
        "None."
    ]
    if rechecked:
        faithful_now = sum(not x["untraced"] for x in rechecked)
        causal_now = sum(bool(x["causal"]) for x in rechecked)
        changed = [
            x
            for x in rechecked
            if x["untraced"] != x["original_untraced"] or x["causal"] != x["original_causal"]
        ]
        lines += [
            "",
            "## Re-check with corrected checkers (no new model calls)",
            "",
            "After the run, two checker false positives were fixed (with regression tests): "
            "digits at the start of hexadecimal ids (`4869f7a5…`) were read as numbers, and "
            'a methodological "excluded because the data is sparse" was read as a causal '
            "claim. In M7 the grounding check was also made stricter: long result columns "
            "allow only adjacent, first/last, and max/min comparisons, because allowing all "
            "pairs let 67 of 200 random invented percentages pass on a 20-month series "
            "(now 39 of 200). The stored final answers were re-checked with the current "
            "checkers; "
            "their SQL was re-executed for the evidence rows. The model's answers are "
            "unchanged; the regeneration decisions above were made by the original checkers.",
            "",
            "| Metric | Original checkers | Corrected checkers |",
            "|---|---|---|",
            f"| Answers with no untraced number | {faithful}/{len(answered)} | "
            f"{faithful_now}/{len(rechecked)} |",
            f"| Answers with causal wording | {causal}/{len(answered)} | "
            f"{causal_now}/{len(rechecked)} |",
            "",
            "Changed items: " + (", ".join(f"`{x['id']}`" for x in changed) or "none") + ".",
        ]
    lines += ["", "## PRD examples", ""]
    for r in rows:
        if r["split"] == "example":
            lines += (
                [
                    f"**{r['question']}** ({', '.join(r['components'])})",
                    "",
                    f"> {r['headline']}",
                    "",
                ]
                + [f"> - {n}" for n in r["notes"]]
                + [
                    "",
                    f"Scope: {r['scope']['period']}; definitions: "
                    f"{'; '.join(r['scope']['definitions'])}; caveats: {r['caveats']}",
                    "",
                ]
            )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    sys.exit(main())
