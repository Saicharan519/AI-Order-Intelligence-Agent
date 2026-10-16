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
    python eval/run_investigation_eval.py --recheck   # re-apply the causal lint, no calls
    python eval/run_investigation_eval.py --planted   # planted anomalies on the mini fixture, no calls
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import yaml

from orderintel.agent.ask import ask, build_graph
from orderintel.agent.grounding import causal_findings
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
PLANTED_OUT = PROJECT_ROOT / "eval" / "results" / "investigation_planted.json"

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
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--planted", action="store_true")
    ap.add_argument("--model", help="model override for a comparison run (M10)")
    ap.add_argument("--ids", help="comma-separated case ids (subset; no follow-ups)")
    args = ap.parse_args(argv)
    if args.recheck:
        return recheck()
    if args.planted:
        return planted()
    cases = [
        c
        for c in yaml.safe_load((GOLDEN / "investigation.yaml").read_text(encoding="utf-8"))
        if "fixture" not in c
    ]
    comparison = bool(args.model or args.ids)
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    followups = [] if comparison else FOLLOWUPS
    out_path = OUT.with_name(f"investigation_{args.model or 'subset'}.json") if comparison else OUT
    labels = yaml.safe_load((GOLDEN / "investigation_labels.yaml").read_text(encoding="utf-8"))
    if args.estimate:
        calls = len(cases) * 2.3 + len(followups) * 3.2
        # v4-pro costs about 4.4x flash per input token and 3.3x per output token
        factor = 4.4 if args.model == "deepseek-v4-pro" else 1.0
        print(
            f"{len(cases)} cases + {len(followups)} follow-ups: about {calls:.0f} calls, "
            f"expected about ${calls * 0.00025 * factor:.3f} "
            f"(worst case about ${calls * 0.004 * factor:.2f})"
        )
        return 0
    if not args.approved:
        print("Refusing to make paid calls without --approved.")
        return 1

    client = LLMClient(
        provider_config("deepseek", model=args.model),
        PostgresLedger(),
        ResponseCache(get_settings().llm_cache_dir),
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
        for fu in followups:
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

    out_path.write_text(
        json.dumps(
            {
                "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "model": client.cfg.model,
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
    if comparison:  # the M7 report stays as it is; the comparison report reads this file
        print(f"wrote {out_path}")
        return 0
    write_report(rows, fus)
    return 0


def recheck() -> int:
    """Re-apply the current causal lint to the stored narrations (no API calls). The
    warnings from the paid run are kept as warnings_at_run."""
    data = json.loads(OUT.read_text(encoding="utf-8"))
    for r in data["cases"]:
        r.setdefault("warnings_at_run", list(r["warnings"]))
        prose = "\n".join([r["headline"], *r["notes"], *r["caveats"]])
        terms = causal_findings(prose)
        r["grounding"]["causal_terms"] = terms
        r["warnings"] = [w for w in r["warnings_at_run"] if "causal wording" not in w or terms]
    data["rechecked_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    OUT.write_text(
        json.dumps(data, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8",
        newline="\n",
    )
    write_report(data["cases"], data["followups"], rechecked=True)
    return 0


def planted() -> int:
    """Planted-anomaly cases (SC-08) on the synthetic mini fixture: the playbook runs
    without any model call, on a freshly built orderintel_mini, and must report the
    expected verdict, driver, and location."""
    sys.path.insert(0, str(PROJECT_ROOT))  # scripts/ and tests/fixtures/ are not installed
    from orderintel.playbooks import late_delivery
    from orderintel.playbooks.base import PlaybookParams
    from scripts.build_mini_db import build, mini_settings
    from tests.fixtures.mini_olist.generate import PLANT_SELLER

    cases = [
        c
        for c in yaml.safe_load((GOLDEN / "investigation.yaml").read_text(encoding="utf-8"))
        if "fixture" in c
    ]
    build(plants=True)
    s = mini_settings()
    out = []
    for c in cases:
        p = c["params"]
        _, f = late_delivery.run(PlaybookParams(**p), settings=s)
        checks = {
            "verdict": f.verdict == c["expected_verdict"],
            "top_driver": f.top_driver == c["expected_top_driver"],
        }
        located = None
        if "expected_top_state_unfiltered" in c:
            _, g = late_delivery.run(PlaybookParams(period=p["period"]), settings=s)
            located = g.top_states[0].name if g.top_states else None
            checks["top_state"] = located == c["expected_top_state_unfiltered"]
        if "expected_top_seller" in c:
            expected = PLANT_SELLER if c["expected_top_seller"] == "PLANT_SELLER" else None
            located = f.top_sellers[0].name if f.top_sellers else None
            checks["top_seller"] = located == expected
        out.append(
            {
                "id": c["id"],
                "params": p,
                "verdict": f.verdict,
                "top_driver": f.top_driver,
                "late_rate": f.late_rate,
                "baseline_rate": f.baseline_rate,
                "located": located,
                "checks": checks,
                "detected": all(checks.values()),
            }
        )
        print(f"  {c['id']}: {f.verdict} {f.top_driver} located={located} checks={checks}")
    PLANTED_OUT.write_text(
        json.dumps(
            {"run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "cases": out},
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    data = json.loads(OUT.read_text(encoding="utf-8"))
    write_report(data["cases"], data["followups"], rechecked="rechecked_at" in data)
    return 0 if all(c["detected"] for c in out) else 1


def write_report(rows: list[dict], fus: list[dict], rechecked: bool = False) -> None:
    played = [r for r in rows if r["verdict_ok"] is not None]
    positives = [r for r in played if r["label"]["verdict"] == "elevated"]
    negatives = [r for r in played if r["label"]["verdict"] == "nothing_notable"]
    traced = sum(not r["grounding"]["untraced"] for r in played)
    no_warning = sum(not r["warnings"] for r in played)
    cost = sum(r["usage"]["cost_usd"] for r in rows) + sum(f["usage"]["cost_usd"] for f in fus)
    plants = (
        json.loads(PLANTED_OUT.read_text(encoding="utf-8"))["cases"] if PLANTED_OUT.exists() else []
    )
    planted_cell = (
        f"{sum(c['detected'] for c in plants)}/{len(plants)}" if plants else "not run (`--planted`)"
    )
    lines = [
        "# Investigation evaluation (M7 part 1)",
        "",
        "Generated by `eval/run_investigation_eval.py`. Labels: `eval/golden/investigation_labels.yaml` "
        "(computed from raw tables, independently of the playbooks).",
        "",
    ]
    if rechecked:
        cleared = [r["id"] for r in rows if len(r["warnings"]) < len(r.get("warnings_at_run", []))]
        lines += [
            "Rechecked offline (`--recheck`, no API calls) after a causal-lint fix: a negated "
            'noun such as "not proof of cause" is a disclaimer, not a claim. Warnings cleared: '
            f"{', '.join(cleared) or 'none'}. The original warnings stay in the results JSON as "
            "`warnings_at_run`.",
            "",
        ]
    lines += [
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
        f"| Planted anomalies detected (mini fixture, no model calls) | {planted_cell} | 2/2 |",
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
    if plants:
        lines += [
            "",
            "## Planted anomalies (synthetic mini fixture)",
            "",
            "Built by `scripts/build_mini_db.py` from `tests/fixtures/mini_olist/generate.py`; "
            "the playbook runs without model calls. The same fixture without the plants "
            "reports nothing notable for these months (`tests/integration/test_mini_fixture.py`).",
            "",
            "| Case | Params | Verdict | Late rate vs baseline | Driver | Located | Detected |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in plants:
            lines.append(
                f"| `{c['id']}` | {c['params']} | {c['verdict']} | {c['late_rate']}% vs "
                f"{c['baseline_rate']}% | {c['top_driver']} | `{(c['located'] or '-')[:12]}` | "
                f"{c['detected']} |"
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
