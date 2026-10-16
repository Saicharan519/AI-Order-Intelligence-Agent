"""Investigation evaluation (T-7.5, T-7.6; SC-08): 15 cases plus 5 follow-ups.

For each case the full Ask graph runs; checked against the independent labels in
eval/golden/investigation_labels.yaml:
  * routing: playbook, period, and state exactly as expected (or not "investigate" when no
    playbook applies);
  * finding fidelity: playbook verdict and top driver equal the labels;
  * narration: every number traced to the findings, narrated driver equals the computed
    one, no causal wording (after at most one regeneration).
Follow-ups run in the same session after their investigation and must (a) mention the
inherited scope in their SQL and (b) return the reference answer (raw-table SQL below).

    python eval/run_investigation_eval.py --estimate
    python eval/run_investigation_eval.py --approved
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import yaml

from orderintel.agent.ask import ask, build_graph
from orderintel.agent.pipeline import eval_execute
from orderintel.agent.session import SessionStore
from orderintel.config import PROJECT_ROOT, get_settings
from orderintel.db.connect import connect_eval
from orderintel.evaluation.compare import compare_results
from orderintel.llm.budget import LimitExceeded, PostgresLedger
from orderintel.llm.cache import ResponseCache
from orderintel.llm.client import LLMClient, LLMError, provider_config

GOLDEN = PROJECT_ROOT / "eval" / "golden"
OUT = PROJECT_ROOT / "eval" / "results" / "investigation_deepseek.json"
REPORT = PROJECT_ROOT / "eval" / "reports" / "investigation_report.md"

DELIVERED = "o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL"
LATE = "o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date"
MAR18 = "o.order_purchase_timestamp >= '2018-03-01' AND o.order_purchase_timestamp < '2018-04-01'"
FEB18 = "o.order_purchase_timestamp >= '2018-02-01' AND o.order_purchase_timestamp < '2018-03-01'"

FOLLOWUPS = [
    {
        "id": "fu_01",
        "after": "inv_late_01",
        "question": "Which 5 sellers had the most late orders?",
        "ordering": "ordered",
        "allow_extra_columns": True,
        "reference_sql": f"""SELECT i.seller_id, count(DISTINCT o.order_id)
        FROM raw.order_items i JOIN raw.orders o ON o.order_id = i.order_id
        WHERE {DELIVERED} AND {LATE} AND {MAR18}
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5""",
    },
    {
        "id": "fu_02",
        "after": "inv_late_04",
        "question": "How many late orders were there?",
        "reference_sql": f"""SELECT count(*) FROM raw.orders o
        JOIN raw.customers c ON c.customer_id = o.customer_id
        WHERE {DELIVERED} AND {LATE} AND {MAR18} AND c.customer_state = 'RJ'""",
    },
    {
        "id": "fu_03",
        "after": "inv_late_02",
        "question": "What was the average carrier transit time in days?",
        "reference_sql": f"""SELECT round(avg(extract(epoch FROM o.order_delivered_customer_date
              - o.order_delivered_carrier_date) / 86400), 2)
        FROM raw.orders o WHERE {DELIVERED} AND {FEB18}
          AND o.order_delivered_customer_date >= o.order_delivered_carrier_date""",
    },
    {
        "id": "fu_04",
        "after": "inv_late_05",
        "question": "How many orders were delivered?",
        "reference_sql": f"""SELECT count(*) FROM raw.orders o
        JOIN raw.customers c ON c.customer_id = o.customer_id
        WHERE {DELIVERED} AND {MAR18} AND c.customer_state = 'MG'""",
    },
    {
        "id": "fu_05",
        "after": "inv_rev_01",
        "question": "What share of reviews were 1-star?",
        "reference_sql": f"""WITH r AS (SELECT DISTINCT ON (order_id) order_id, review_score
            FROM raw.order_reviews
            ORDER BY order_id, review_answer_timestamp DESC, review_creation_date DESC,
                     review_row_id DESC)
        SELECT round(100.0 * count(*) FILTER (WHERE r.review_score = 1) / count(*), 2)
        FROM raw.orders o JOIN r ON r.order_id = o.order_id WHERE {MAR18}""",
    },
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--approved", action="store_true")
    args = ap.parse_args(argv)
    cases = [
        c
        for c in yaml.safe_load((GOLDEN / "investigation.yaml").read_text(encoding="utf-8"))
        if "fixture" not in c
    ]
    labels = yaml.safe_load((GOLDEN / "investigation_labels.yaml").read_text(encoding="utf-8"))
    if args.estimate:
        calls = len(cases) * 2.3 + len(FOLLOWUPS) * 3.2
        print(
            f"{len(cases)} cases + {len(FOLLOWUPS)} follow-ups: about {calls:.0f} calls, "
            f"expected about ${calls * 0.00025:.3f} (worst case about ${calls * 0.004:.2f})"
        )
        return 0
    if not args.approved:
        print("Refusing to make paid calls without --approved.")
        return 1

    client = LLMClient(
        provider_config("deepseek"), PostgresLedger(), ResponseCache(get_settings().llm_cache_dir)
    )
    store = SessionStore()
    graph = build_graph(client, store)
    rows = []
    try:
        for c in cases:
            r = ask(
                client,
                c["question"],
                config_name="eval:investigate",
                graph=graph,
                session_id=c["id"],
                store=store,
            )
            lab = labels[c["id"]]
            report = next((x for x in r.components if x["type"] == "report"), None)
            if c.get("playbook") is None:
                route_ok = r.route != "investigate"
                verdict = driver = None
            else:
                p = c["params"]
                f = report["findings"] if report else {}
                route_ok = (
                    r.route == "investigate"
                    and report is not None
                    and report["playbook"] == c["playbook"]
                    and f.get("period") == p["period"]
                    and f.get("state") == p.get("state")
                )
                verdict, driver = (
                    (report["verdict"], report["top_driver"]) if report else (None, None)
                )
            row = {
                "id": c["id"],
                "question": c["question"],
                "route": r.route,
                "route_ok": route_ok,
                "label": lab,
                "verdict": verdict,
                "top_driver": driver,
                "verdict_ok": verdict == lab["verdict"] if c.get("playbook") else None,
                "driver_ok": driver == lab["top_driver"] if c.get("playbook") else None,
                "headline": r.headline,
                "notes": r.notes,
                "caveats": r.caveats,
                "warnings": r.warnings,
                "grounding": r.grounding.model_dump(),
                "usage": r.usage.model_dump(),
            }
            rows.append(row)
            print(
                f"  {c['id']:<12} route={r.route:<11}{'ok ' if route_ok else 'BAD'} "
                f"verdict={verdict} ({'ok' if row['verdict_ok'] else row['verdict_ok']}) "
                f"driver={driver} untraced={r.grounding.untraced} warnings={len(r.warnings)} "
                f"{r.usage.latency_ms} ms"
            )
        fus = []
        for fu in FOLLOWUPS:
            r = ask(
                client,
                fu["question"],
                config_name="eval:investigate",
                graph=graph,
                session_id=fu["after"],
                store=store,
            )
            correct = None
            if r.status == "ok" and r.evidence and r.evidence[0].sql:
                _, got, _ = eval_execute(r.evidence[0].sql)
                with connect_eval() as conn:
                    ref = conn.execute(fu["reference_sql"]).fetchall()
                correct = compare_results(
                    ref,
                    got,
                    ordered=fu.get("ordering") == "ordered",
                    allow_extra_columns=fu.get("allow_extra_columns", False),
                ).match
            scope_ok = bool(r.scope.filters) and not any(
                "may not apply the inherited scope" in w for w in r.warnings
            )
            fus.append(
                {
                    "id": fu["id"],
                    "after": fu["after"],
                    "question": fu["question"],
                    "status": r.status,
                    "correct": correct,
                    "scope_ok": scope_ok,
                    "sql": r.evidence[0].sql if r.evidence else None,
                    "headline": r.headline,
                    "warnings": r.warnings,
                    "usage": r.usage.model_dump(),
                }
            )
            print(
                f"  {fu['id']} after {fu['after']}: correct={correct} scope_ok={scope_ok} "
                f"{r.headline[:80]}"
            )
    except (LimitExceeded, LLMError) as e:
        print(f"STOPPED: {e}")
        return 1

    OUT.write_text(
        json.dumps(
            {
                "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "cases": rows,
                "followups": fus,
            },
            indent=1,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
        newline="\n",
    )
    write_report(rows, fus)
    return 0


def write_report(rows: list[dict], fus: list[dict]) -> None:
    played = [r for r in rows if r["verdict_ok"] is not None]
    positives = [r for r in played if r["label"]["verdict"] == "elevated"]
    negatives = [r for r in played if r["label"]["verdict"] == "nothing_notable"]
    traced = sum(not r["grounding"]["untraced"] for r in played)
    no_warning = sum(not r["warnings"] for r in played)
    cost = sum(r["usage"]["cost_usd"] for r in rows) + sum(f["usage"]["cost_usd"] for f in fus)
    lines = [
        "# Investigation evaluation (M7 part 1)",
        "",
        "Generated by `eval/run_investigation_eval.py`. Labels: `eval/golden/investigation_labels.yaml` "
        "(computed from raw tables, independently of the playbooks).",
        "",
        "| Check | Result | Target (SC-08) |",
        "|---|---|---|",
        f"| Routing: playbook and parameters exactly right (or no investigation when none applies) | "
        f"{sum(r['route_ok'] for r in rows)}/{len(rows)} | — |",
        f"| Every number in the narration traced to the findings | {traced}/{len(played)} | "
        f"all cases |",
        f"| Verdict equals the independent label | {sum(r['verdict_ok'] for r in played)}/{len(played)} | — |",
        f"| Top driver agrees, positive cases | {sum(r['driver_ok'] for r in positives)}/{len(positives)} | "
        f"≥ 90% |",
        f"| Negative controls report nothing notable | {sum(r['verdict_ok'] for r in negatives)}/"
        f"{len(negatives)} | all |",
        f"| Narrations with no warning (grounding, driver, causal wording) | {no_warning}/{len(played)} | — |",
        f"| Follow-ups that kept the inherited scope | {sum(f['scope_ok'] for f in fus)}/{len(fus)} | — |",
        f"| Follow-ups answered correctly | {sum(bool(f['correct']) for f in fus)}/{len(fus)} | — |",
        "| Planted anomalies detected | not run yet (M7 part 2, mini fixture) | 2/2 |",
        f"| Cost | ${cost:.4f} | — |",
        "",
        "## Cases",
        "",
        "| Case | Expected | Got | Driver (expected / got) | Untraced | Warnings |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['id']}` | {r['label']['verdict']} | {r['verdict'] or r['route']} | "
            f"{r['label']['top_driver']} / {r['top_driver']} | "
            f"{', '.join(r['grounding']['untraced']) or '-'} | "
            f"{'; '.join(r['warnings']) or '-'} |"
        )
    lines += [
        "",
        "## Follow-ups",
        "",
        "| Follow-up | After | Correct | Scope kept | SQL |",
        "|---|---|---|---|---|",
    ]
    for f in fus:
        lines.append(
            f"| `{f['id']}` {f['question']} | `{f['after']}` | {f['correct']} | "
            f"{f['scope_ok']} | `{(f['sql'] or '')[:120]}` |"
        )
    lines += ["", "## Example narration (inv_late_01)", ""]
    ex = next((r for r in rows if r["id"] == "inv_late_01"), None)
    if ex:
        lines += (
            [f"> {ex['headline']}", ""]
            + [f"> - {n}" for n in ex["notes"]]
            + ["", f"Caveats: {ex['caveats']}"]
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    sys.exit(main())
