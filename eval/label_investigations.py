"""Independent labels for the investigation cases (T-7.6, technical design 8.6).

Expected verdicts and top drivers are computed from the RAW tables with SQL written here,
not with the analytics views or the playbook code, so a playbook defect shows up as a
disagreement. The decision rules are the ones fixed in the plan before any narration run
(late: >= baseline + 3 points, >= 1.5 x baseline, >= 100 orders; reviews: 1-star share
>= baseline + 3 points, >= 1.3 x baseline, >= 100 reviews).

    python eval/label_investigations.py      # writes eval/golden/investigation_labels.yaml
"""

from __future__ import annotations

import sys

import yaml

from orderintel.config import PROJECT_ROOT
from orderintel.db.connect import connect_eval

CASES = PROJECT_ROOT / "eval" / "golden" / "investigation.yaml"
OUT = PROJECT_ROOT / "eval" / "golden" / "investigation_labels.yaml"

DELIVERED = "o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL"
LATE = "o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date"
WINDOW = "o.order_purchase_timestamp >= '2017-01-01' AND o.order_purchase_timestamp < '2018-09-01'"
IN_MONTH = "date_trunc('month', o.order_purchase_timestamp) = %(month)s::date"


def state_clause(state):
    return "AND c.customer_state = %(state)s" if state else ""


def late_label(conn, month: str, state: str | None) -> dict:
    sql = f"""
        SELECT ({IN_MONTH}) AS in_period, count(*) AS n,
               count(*) FILTER (WHERE {LATE}) AS late,
               avg(extract(epoch FROM o.order_delivered_carrier_date - o.order_purchase_timestamp) / 86400)
                   FILTER (WHERE o.order_delivered_carrier_date >= o.order_purchase_timestamp) AS handling,
               avg(extract(epoch FROM o.order_delivered_customer_date - o.order_delivered_carrier_date) / 86400)
                   FILTER (WHERE o.order_delivered_customer_date >= o.order_delivered_carrier_date) AS transit,
               avg(extract(epoch FROM o.order_estimated_delivery_date - o.order_purchase_timestamp) / 86400)
                   AS promised
        FROM raw.orders o JOIN raw.customers c ON c.customer_id = o.customer_id
        WHERE {DELIVERED} AND {WINDOW} {state_clause(state)}
        GROUP BY 1"""  # noqa: S608
    rows = {r[0]: r for r in conn.execute(sql, {"month": month + "-01", "state": state})}
    cur, ref = rows[True], rows[False]
    rate, base = 100 * cur[2] / cur[1], 100 * ref[2] / ref[1]
    elevated = cur[1] >= 100 and rate - base >= 3 and rate >= 1.5 * base
    driver = "none"
    if elevated:
        moves = {
            "seller_handling": cur[3] - ref[3],
            "carrier_transit": cur[4] - ref[4],
            "shorter_promise": ref[5] - cur[5],
        }
        name, size = max(moves.items(), key=lambda kv: kv[1])
        driver = name if size > 0 else "none"
    return {
        "verdict": "elevated" if elevated else "nothing_notable",
        "top_driver": driver,
        "evidence": {
            "n": cur[1],
            "late_rate": round(rate, 2),
            "baseline_rate": round(base, 2),
            "transit_delta_days": round(float(cur[4] - ref[4]), 2),
            "handling_delta_days": round(float(cur[3] - ref[3]), 2),
            "promised_delta_days": round(float(cur[5] - ref[5]), 2),
        },
    }


def review_label(conn, month: str, state: str | None) -> dict:
    sql = f"""
        WITH r AS (
            SELECT DISTINCT ON (order_id) order_id, review_score FROM raw.order_reviews
            ORDER BY order_id, review_answer_timestamp DESC, review_creation_date DESC,
                     review_row_id DESC)
        SELECT ({IN_MONTH}) AS in_period,
               CASE WHEN NOT ({DELIVERED}) THEN 'not_delivered'
                    WHEN {LATE} THEN 'late' ELSE 'on_time' END AS grp,
               count(*) AS n, count(*) FILTER (WHERE r.review_score = 1) AS one_star
        FROM raw.orders o JOIN r ON r.order_id = o.order_id
        JOIN raw.customers c ON c.customer_id = o.customer_id
        WHERE {WINDOW} {state_clause(state)}
        GROUP BY 1, 2"""  # noqa: S608
    rows = conn.execute(sql, {"month": month + "-01", "state": state}).fetchall()
    n_cur = sum(r[2] for r in rows if r[0])
    n_ref = sum(r[2] for r in rows if not r[0])
    one_cur = sum(r[3] for r in rows if r[0])
    one_ref = sum(r[3] for r in rows if not r[0])
    share, base = 100 * one_cur / n_cur, 100 * one_ref / n_ref
    elevated = n_cur >= 100 and share - base >= 3 and share >= 1.3 * base
    contrib = {}
    for g in ("late", "on_time", "not_delivered"):
        c = sum(r[3] for r in rows if r[0] and r[1] == g)
        b = sum(r[3] for r in rows if not r[0] and r[1] == g)
        contrib[g] = 100 * (c / n_cur - b / n_ref)
    names = {"late": "late_delivery", "on_time": "on_time_orders", "not_delivered": "not_delivered"}
    driver = "none"
    if elevated:
        g, size = max(contrib.items(), key=lambda kv: kv[1])
        driver = names[g] if size > 0 else "none"
    return {
        "verdict": "elevated" if elevated else "nothing_notable",
        "top_driver": driver,
        "evidence": {
            "n": n_cur,
            "one_star_share": round(share, 2),
            "baseline_share": round(base, 2),
            "contribution_points": {k: round(v, 2) for k, v in contrib.items()},
        },
    }


def main() -> int:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    labels = {}
    with connect_eval() as conn:
        for c in cases:
            if "fixture" in c:
                continue
            if c.get("playbook") is None:
                labels[c["id"]] = {
                    "verdict": "not_applicable",
                    "top_driver": None,
                    "evidence": {"note": "no playbook applies"},
                }
                continue
            month, state = c["params"]["period"], c["params"].get("state")
            fn = late_label if c["playbook"] == "late_delivery_diagnosis" else review_label
            labels[c["id"]] = fn(conn, month, state)
            lab = labels[c["id"]]
            print(
                f"  {c['id']:<12} {lab['verdict']:<16} {str(lab['top_driver']):<16} "
                f"{lab['evidence']}"
            )
    header = (
        "# Generated by eval/label_investigations.py from the raw tables (independent of "
        "the views and playbooks).\n# Do not edit by hand; re-run the script.\n"
    )
    OUT.write_text(
        header + yaml.safe_dump(labels, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUT.name} ({len(labels)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
