"""low_review_diagnosis (T-7.3): why were review scores low in a month (optionally a state)?

Population: orders purchased in the month that have a review (latest answered review per
order). Baseline: every other month of the analysis window, same state filter. Verdict
"elevated" when the 1-star share is at least baseline + 3 points AND at least 1.3 x baseline
AND at least 100 reviews. The top driver is the delivery group (late, on time, not
delivered) that added the most 1-star reviews per 100 reviews compared with the baseline:
contribution_g = one_star_g / reviews (period) - one_star_g / reviews (baseline).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from orderintel.playbooks.base import MIN_GROUP, PlaybookParams, PlaybookRun, Step, pct, run_steps

NAME = "low_review_diagnosis"
STATE_FILTER = "(CAST(:state AS TEXT) IS NULL OR customer_state = :state)"
WINDOW = "purchase_month >= :w_start AND purchase_month < :w_end"
MIN_SAMPLE = 100
ELEVATED_POINTS = 3.0
ELEVATED_RATIO = 1.3
GROUP_SQL = (
    "CASE WHEN NOT is_delivered THEN 'not_delivered' WHEN is_late THEN 'late' ELSE 'on_time' END"
)

STEPS = [
    Step(
        "kpi",
        f"""
        SELECT purchase_month = :p_month AS in_period,
               count(review_score) AS n_reviews,
               round(avg(review_score), 2) AS avg_score,
               count(*) FILTER (WHERE review_score = 1) AS one_star
        FROM orders WHERE review_score IS NOT NULL AND {WINDOW} AND {STATE_FILTER}
        GROUP BY 1""",
    ),
    Step(
        "one_star_by_delivery",
        f"""
        SELECT purchase_month = :p_month AS in_period,
               {GROUP_SQL} AS delivery_group,
               count(review_score) AS n_reviews,
               count(*) FILTER (WHERE review_score = 1) AS one_star
        FROM orders WHERE review_score IS NOT NULL AND {WINDOW} AND {STATE_FILTER}
        GROUP BY 1, 2""",
    ),
    Step(
        "category",
        f"""
        SELECT i.category,
               count(DISTINCT o.order_id) FILTER (WHERE o.purchase_month = :p_month) AS n_period,
               round(avg(o.review_score) FILTER (WHERE o.purchase_month = :p_month), 2)
                   AS avg_period,
               round(avg(o.review_score) FILTER (WHERE o.purchase_month <> :p_month), 2)
                   AS avg_base
        FROM orders o JOIN order_items i ON i.order_id = o.order_id
        WHERE o.review_score IS NOT NULL AND o.purchase_month >= :w_start
          AND o.purchase_month < :w_end
          AND (CAST(:state AS TEXT) IS NULL OR o.customer_state = :state)
        GROUP BY i.category
        HAVING count(DISTINCT o.order_id) FILTER (WHERE o.purchase_month = :p_month) >= {MIN_GROUP}
        ORDER BY i.category""",
    ),
    Step(
        "sellers",
        f"""
        SELECT i.seller_id,
               count(DISTINCT o.order_id) AS n_period,
               round(avg(o.review_score), 2) AS avg_period,
               count(DISTINCT o.order_id) FILTER (WHERE o.review_score = 1) AS one_star
        FROM orders o JOIN order_items i ON i.order_id = o.order_id
        WHERE o.review_score IS NOT NULL AND o.purchase_month = :p_month
          AND o.purchase_month >= :w_start AND o.purchase_month < :w_end
          AND (CAST(:state AS TEXT) IS NULL OR o.customer_state = :state)
        GROUP BY i.seller_id
        HAVING count(DISTINCT o.order_id) >= {MIN_GROUP}
        ORDER BY i.seller_id""",
    ),
]


@dataclass
class GroupScore:
    name: str
    n: int
    value: float | None
    baseline: float | None = None


@dataclass
class ReviewFindings:
    playbook: str
    period: str
    state: str | None
    verdict: str  # elevated | nothing_notable | insufficient_data
    reviews: int
    avg_score: float | None
    avg_score_baseline: float | None
    one_star_share: float | None
    one_star_share_baseline: float | None
    delta_points: float | None
    top_driver: str = "none"  # late_delivery | on_time_orders | not_delivered | none
    one_star_from: dict[str, float] = field(default_factory=dict)  # % of the period's 1-stars
    contribution_points: dict[str, float] = field(default_factory=dict)
    worst_categories: list[GroupScore] = field(default_factory=list)
    worst_sellers: list[GroupScore] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


DRIVER_NAME = {
    "late": "late_delivery",
    "on_time": "on_time_orders",
    "not_delivered": "not_delivered",
}


def compute_findings(run: PlaybookRun) -> ReviewFindings:
    p = run.params
    k = {r["in_period"]: r for r in run.step("kpi").as_dicts()}
    cur, ref = k.get(True), k.get(False)
    n = cur["n_reviews"] if cur else 0
    share = pct(cur["one_star"], n) if cur else None
    base = pct(ref["one_star"], ref["n_reviews"]) if ref else None
    delta = None if share is None or base is None else round(share - base, 1)
    if n < MIN_SAMPLE or share is None or base is None:
        verdict = "insufficient_data"
    elif delta >= ELEVATED_POINTS and share >= ELEVATED_RATIO * base:
        verdict = "elevated"
    else:
        verdict = "nothing_notable"
    f = ReviewFindings(
        NAME,
        p.period,
        p.state,
        verdict,
        n,
        float(cur["avg_score"]) if cur else None,
        float(ref["avg_score"]) if ref else None,
        share,
        base,
        delta,
    )

    groups = run.step("one_star_by_delivery").as_dicts()
    total_cur = sum(g["n_reviews"] for g in groups if g["in_period"])
    total_ref = sum(g["n_reviews"] for g in groups if not g["in_period"])
    one_cur = sum(g["one_star"] for g in groups if g["in_period"])
    for name in ("late", "on_time", "not_delivered"):
        c = next((g for g in groups if g["in_period"] and g["delivery_group"] == name), None)
        r = next((g for g in groups if not g["in_period"] and g["delivery_group"] == name), None)
        c1 = c["one_star"] if c else 0
        r1 = r["one_star"] if r else 0
        f.one_star_from[name] = pct(c1, one_cur) or 0.0
        if total_cur and total_ref:
            f.contribution_points[name] = round(100 * (c1 / total_cur - r1 / total_ref), 1)
    if verdict == "elevated" and f.contribution_points:
        g, size = max(f.contribution_points.items(), key=lambda kv: kv[1])
        f.top_driver = DRIVER_NAME[g] if size > 0 else "none"

    cats = [c for c in run.step("category").as_dicts() if c["avg_base"] is not None]
    cats.sort(key=lambda c: (float(c["avg_period"]) - float(c["avg_base"]), c["category"]))
    f.worst_categories = [
        GroupScore(c["category"], c["n_period"], float(c["avg_period"]), float(c["avg_base"]))
        for c in cats[:3]
    ]
    sellers = run.step("sellers").as_dicts()
    sellers.sort(key=lambda s: (float(s["avg_period"]), s["seller_id"]))
    f.worst_sellers = [
        GroupScore(s["seller_id"], s["n_period"], float(s["avg_period"])) for s in sellers[:3]
    ]
    f.caveats = [
        "Review scores are associations with delivery outcomes, not proof of cause.",
        "Each order counts once, with its latest answered review; review text is not used.",
    ]
    if n < MIN_SAMPLE:
        f.caveats.append(f"Only {n} reviewed orders in the period: too few to judge.")
    return f


def run(params: PlaybookParams, settings=None) -> tuple[PlaybookRun, ReviewFindings]:
    r = run_steps(NAME, STEPS, params, settings)
    return r, compute_findings(r)
