"""late_delivery_diagnosis (T-7.2): why were deliveries late in a month (optionally a state)?

Baseline = pooled value over every other month of the analysis window (January 2017 to
August 2018), with the same state filter (PRD section 6). Verdict "elevated" when the late
rate is at least baseline + 3 points AND at least 1.5 x baseline AND the sample has at least
100 delivered orders; otherwise "nothing_notable". The top driver is the delivery stage
whose average moved most against the customer: longer seller handling, longer carrier
transit, or a shorter promise. Everything here is computed in code; the model only narrates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from orderintel.playbooks.base import MIN_GROUP, PlaybookParams, PlaybookRun, Step, pct, run_steps

NAME = "late_delivery_diagnosis"
STATE_FILTER = "(CAST(:state AS TEXT) IS NULL OR customer_state = :state)"
WINDOW = "purchase_month >= :w_start AND purchase_month < :w_end"
MIN_SAMPLE = 100
MIN_STATE_SAMPLE = 100
ELEVATED_POINTS = 3.0
ELEVATED_RATIO = 1.5

STEPS = [
    Step(
        "kpi",
        f"""
        SELECT count(*) FILTER (WHERE purchase_month = :p_month) AS n_period,
               count(*) FILTER (WHERE purchase_month = :p_month AND is_late) AS late_period,
               count(*) FILTER (WHERE purchase_month <> :p_month) AS n_base,
               count(*) FILTER (WHERE purchase_month <> :p_month AND is_late) AS late_base
        FROM orders WHERE is_delivered AND {WINDOW} AND {STATE_FILTER}""",
    ),
    Step(
        "stages",
        f"""
        SELECT purchase_month = :p_month AS in_period,
               round(avg(seller_handling_days), 2) AS handling_days,
               round(avg(carrier_transit_days), 2) AS transit_days,
               round(avg(promised_days), 2) AS promised_days,
               count(*) AS n
        FROM orders WHERE is_delivered AND {WINDOW} AND {STATE_FILTER}
        GROUP BY 1""",
    ),
    Step(
        "geography",
        f"""
        SELECT customer_state AS state,
               count(*) FILTER (WHERE purchase_month = :p_month) AS n_period,
               count(*) FILTER (WHERE purchase_month = :p_month AND is_late) AS late_period,
               count(*) FILTER (WHERE purchase_month <> :p_month) AS n_base,
               count(*) FILTER (WHERE purchase_month <> :p_month AND is_late) AS late_base
        FROM orders WHERE is_delivered AND {WINDOW}
        GROUP BY customer_state ORDER BY customer_state""",
        only_without_state=True,
    ),
    Step(
        "category",
        f"""
        SELECT category,
               count(DISTINCT order_id) FILTER (WHERE purchase_month = :p_month) AS n_period,
               count(DISTINCT order_id) FILTER (WHERE purchase_month = :p_month AND is_late)
                   AS late_period,
               count(DISTINCT order_id) FILTER (WHERE purchase_month <> :p_month) AS n_base,
               count(DISTINCT order_id) FILTER (WHERE purchase_month <> :p_month AND is_late)
                   AS late_base
        FROM order_items WHERE is_late IS NOT NULL AND {WINDOW} AND {STATE_FILTER}
        GROUP BY category
        HAVING count(DISTINCT order_id) FILTER (WHERE purchase_month = :p_month) >= {MIN_GROUP}
        ORDER BY category""",
    ),
    Step(
        "sellers",
        f"""
        WITH s AS (
            SELECT seller_id, count(DISTINCT order_id) AS late_orders
            FROM order_items WHERE is_late AND purchase_month = :p_month AND {STATE_FILTER}
            GROUP BY seller_id)
        SELECT count(*) AS sellers_with_late_orders,
               (SELECT sum(late_orders) FROM (
                    SELECT late_orders FROM s ORDER BY late_orders DESC LIMIT 5) t)
                   AS top5_late_orders
        FROM s""",
    ),
    Step(
        "reviews",
        f"""
        SELECT is_late,
               count(review_score) AS n_reviews,
               round(avg(review_score), 2) AS avg_score,
               count(*) FILTER (WHERE review_score = 1) AS one_star
        FROM orders
        WHERE is_delivered AND purchase_month = :p_month AND {STATE_FILTER}
        GROUP BY is_late ORDER BY is_late""",
    ),
]


@dataclass
class GroupRate:
    name: str
    n: int
    rate: float | None
    baseline_rate: float | None
    excess_late_orders: int | None = None


@dataclass
class LateFindings:
    playbook: str
    period: str
    state: str | None
    verdict: str  # elevated | nothing_notable | insufficient_data
    delivered_orders: int
    late_orders: int
    late_rate: float | None
    baseline_rate: float | None
    delta_points: float | None
    handling_days: float | None = None
    handling_days_baseline: float | None = None
    transit_days: float | None = None
    transit_days_baseline: float | None = None
    promised_days: float | None = None
    promised_days_baseline: float | None = None
    top_driver: str = "none"  # carrier_transit | seller_handling | shorter_promise | none
    top_states: list[GroupRate] = field(default_factory=list)
    rate_excluding_top2_states: float | None = None
    systemic: bool | None = None
    top_categories: list[GroupRate] = field(default_factory=list)
    sellers_with_late_orders: int | None = None
    top5_seller_share: float | None = None
    review_avg_late: float | None = None
    review_avg_on_time: float | None = None
    review_n_late: int | None = None
    review_n_on_time: int | None = None
    one_star_share_late: float | None = None
    one_star_share_on_time: float | None = None
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _f(v):
    return None if v is None else float(v)


def compute_findings(run: PlaybookRun) -> LateFindings:
    p = run.params
    k = run.step("kpi").as_dicts()[0]
    rate, base = pct(k["late_period"], k["n_period"]), pct(k["late_base"], k["n_base"])
    delta = None if rate is None or base is None else round(rate - base, 1)
    if k["n_period"] < MIN_SAMPLE or rate is None or base is None:
        verdict = "insufficient_data"
    elif delta >= ELEVATED_POINTS and rate >= ELEVATED_RATIO * base:
        verdict = "elevated"
    else:
        verdict = "nothing_notable"
    f = LateFindings(
        NAME, p.period, p.state, verdict, k["n_period"], k["late_period"], rate, base, delta
    )

    stages = {r["in_period"]: r for r in run.step("stages").as_dicts()}
    cur, ref = stages.get(True), stages.get(False)
    if cur and ref:
        f.handling_days, f.handling_days_baseline = (
            _f(cur["handling_days"]),
            _f(ref["handling_days"]),
        )
        f.transit_days, f.transit_days_baseline = _f(cur["transit_days"]), _f(ref["transit_days"])
        f.promised_days, f.promised_days_baseline = (
            _f(cur["promised_days"]),
            _f(ref["promised_days"]),
        )
        if verdict == "elevated":
            moves = {
                "seller_handling": f.handling_days - f.handling_days_baseline,
                "carrier_transit": f.transit_days - f.transit_days_baseline,
                "shorter_promise": f.promised_days_baseline - f.promised_days,
            }
            driver, size = max(moves.items(), key=lambda kv: kv[1])
            f.top_driver = driver if size > 0 else "none"

    geo = run.step("geography")
    if geo:
        # States are ranked by EXCESS late orders: late orders above what the state's own
        # baseline rate predicts. This answers "where did the extra late orders come from?";
        # ranking by rate would put small states with a few late orders first.
        rows = [r for r in geo.as_dicts() if r["n_period"] >= MIN_STATE_SAMPLE and r["n_base"]]

        def excess(r):
            return r["late_period"] - r["n_period"] * r["late_base"] / r["n_base"]

        ranked = sorted(rows, key=lambda r: (-excess(r), r["state"]))
        f.top_states = [
            GroupRate(
                r["state"],
                r["n_period"],
                pct(r["late_period"], r["n_period"]),
                pct(r["late_base"], r["n_base"]),
                round(excess(r)),
            )
            for r in ranked[:3]
        ]
        top2 = {r["state"] for r in ranked[:2]}
        rest = [r for r in geo.as_dicts() if r["state"] not in top2]
        f.rate_excluding_top2_states = pct(
            sum(r["late_period"] for r in rest), sum(r["n_period"] for r in rest)
        )
        if verdict == "elevated" and f.rate_excluding_top2_states is not None:
            f.systemic = f.rate_excluding_top2_states >= base + ELEVATED_POINTS

    cats = run.step("category").as_dicts()
    cats.sort(key=lambda r: (-(r["late_period"] / r["n_period"]), r["category"]))
    f.top_categories = [
        GroupRate(
            r["category"],
            r["n_period"],
            pct(r["late_period"], r["n_period"]),
            pct(r["late_base"], r["n_base"]),
        )
        for r in cats[:3]
    ]

    s = run.step("sellers").as_dicts()[0]
    f.sellers_with_late_orders = s["sellers_with_late_orders"]
    f.top5_seller_share = pct(s["top5_late_orders"] or 0, f.late_orders)

    reviews = {r["is_late"]: r for r in run.step("reviews").as_dicts()}
    late_r, ok_r = reviews.get(True), reviews.get(False)
    if late_r and ok_r:
        f.review_avg_late, f.review_avg_on_time = _f(late_r["avg_score"]), _f(ok_r["avg_score"])
        f.review_n_late, f.review_n_on_time = late_r["n_reviews"], ok_r["n_reviews"]
        f.one_star_share_late = pct(late_r["one_star"], late_r["n_reviews"])
        f.one_star_share_on_time = pct(ok_r["one_star"], ok_r["n_reviews"])

    f.caveats = [
        "The data shows where delay occurred, not why (observational data).",
        "Order-level lateness is attributed to every seller in a multi-seller order.",
    ]
    if k["n_period"] < MIN_SAMPLE:
        f.caveats.append(f"Only {k['n_period']} delivered orders in the period: too few to judge.")
    return f


def run(params: PlaybookParams, settings=None) -> tuple[PlaybookRun, LateFindings]:
    r = run_steps(NAME, STEPS, params, settings)
    return r, compute_findings(r)
