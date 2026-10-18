"""Pre-check: questions that are answered in code, before the router (no model call).

Three kinds of question have one right answer that does not need a model, and the model
handled them inconsistently in owner testing (the same "why was revenue low in <partial
month>?" was once answered well and once sent to the late-delivery playbook):

* about_data:     "what is this dataset?", "show me the schema", "what can I ask?"
* out_of_range:   a month or year outside the data ("why was 2019 bad?")
* partial_period: a why / low / high question about a month (or 2016) that the data only
                  partly covers, answered with that month's figures next to a typical month

Detection is deterministic (regular expressions on the question), so the same question
always gets the same answer. The queries are fixed, rendered with typed literals, and pass
the same validator and read-only executor as model-written SQL. Every number in the text is
computed here from those rows.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from dataclasses import dataclass, field

from orderintel.api.schemas import AskResponse, Evidence, Followup, Period, ScopeOut, ValidatorOut
from orderintel.catalog import build_catalog
from orderintel.db.executor import execute
from orderintel.evaluation.compare import normalise_value
from orderintel.guard.validator import RULES, validate
from orderintel.playbooks.base import render

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
LABELS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

MONTH_WORD = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
NAMED_MONTH_RE = re.compile(MONTH_WORD + r"\.?,?\s+(?:of\s+)?((?:19|20)\d{2})\b", re.I)
ISO_MONTH_RE = re.compile(r"\b((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])\b")
US_MONTH_RE = re.compile(r"\b(0?[1-9]|1[0-2])[-/]((?:19|20)\d{2})\b")
# A number counts as a year only where a year is expected ("in 2019", "2017 vs 2018"), so
# amounts such as "orders over 2000 reais" are not read as years.
YEAR_RE = re.compile(
    r"(?:\b(?:in|of|during|for|since|from|to|until|till|year|between|and|or|vs\.?|versus|was|were"
    r"|is|are|about|whole|entire|before|after|than)\s+|^\s*)((?:19|20)\d{2})\b"
    r"(?!\s*(?:reais|brl|r\$|orders|items|units))",
    re.I,
)

WHY_RE = re.compile(
    r"\b(why|how come|what happened|explain|reason|so (?:low|high|bad|few|small|poor))\b"
    r"|\b(low|lower|high|higher|bad|poor|weak|few|tiny|small|drop\w*|fell|fall\w*|declin\w*"
    r"|spike\w*|jump\w*|surg\w*|dip\w*|zero|empty|nothing|no orders|missing)\b",
    re.I,
)
_DATA = r"(?:data\s*set|data|database|schema|tables|columns|fields)"
ABOUT_PATTERNS = [
    r"^\s*(?:hi|hello|help)\W*$",
    r"what\s+(?:is|'s)\s+(?:this|the)\s+(?:data\s*set|data|database)"
    r"\s*(?:about|of|for|on)?\s*\W*$",
    r"\b(?:tell me|explain|describe|summari[sz]e)\b.*\b(?:the|this|your)\s+" + _DATA + r"\s*\W*$",
    r"\bwhat\s+(?:data|information|tables|columns|fields)\s+(?:do you have|is there|are there"
    r"|is available|are available|can i (?:use|query|ask about))\b",
    r"\bwhat\s+(?:kind of\s+|type of\s+|sort of\s+)?(?:questions|things)\s+can\s+i\s+ask\b",
    r"\bwhat\s+can\s+i\s+ask\b",
    r"\b(?:show|give|list|display)\s+(?:me\s+)?(?:the\s+|all\s+(?:the\s+)?|your\s+)?"
    r"(?:whole\s+|full\s+|entire\s+)?" + _DATA + r"(?:\s+schema|\s+structure|\s+tables)?\s*\W*$",
]
ABOUT_RE = re.compile("|".join(f"(?:{p})" for p in ABOUT_PATTERNS), re.I)

CACHE_SECONDS = 600


@dataclass
class Precheck:
    kind: str  # about_data | out_of_range | partial_period
    months: list[str] = field(default_factory=list)  # YYYY-MM mentioned in the question
    years: list[int] = field(default_factory=list)
    label: str = ""


@dataclass
class Coverage:
    """Per-month figures for the whole data, from one validated query."""

    months: list[dict]  # month, orders, delivered_orders, revenue, partial, in_window
    sql: str
    ms: int

    @property
    def first(self) -> str:
        return self.months[0]["month"]

    @property
    def last(self) -> str:
        return self.months[-1]["month"]

    def window(self) -> list[dict]:
        return [m for m in self.months if m["in_window"]]

    def get(self, month: str) -> dict | None:
        return next((m for m in self.months if m["month"] == month), None)


COVERAGE_SQL = """
SELECT dc.month, dc.orders_count AS orders, dc.is_partial, dc.in_analysis_window,
       count(o.order_id) FILTER (WHERE o.is_delivered) AS delivered_orders,
       round(coalesce(sum(o.items_revenue) FILTER (WHERE o.is_sale), 0), 2) AS revenue
FROM data_coverage AS dc LEFT JOIN orders AS o ON o.purchase_month = dc.month
GROUP BY dc.month, dc.orders_count, dc.is_partial, dc.in_analysis_window
ORDER BY dc.month"""

_cache: dict[str, tuple[float, Coverage]] = {}
_lock = threading.Lock()


def _run(sql: str, values: dict | None = None, settings=None):
    v = validate(render(sql, values or {}))
    if not v.ok:  # fixed SQL that fails the validator is a bug, not a user error
        raise RuntimeError(f"pre-check query failed validation: {v.feedback()}")
    return v.sql, execute(v.validated, settings=settings)


def coverage(settings=None) -> Coverage:
    key = getattr(settings, "postgres_db", None) or "default"
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    sql, res = _run(COVERAGE_SQL, settings=settings)
    months = [
        {
            "month": r[0].isoformat()[:7],
            "orders": int(r[1]),
            "partial": bool(r[2]),
            "in_window": bool(r[3]),
            "delivered_orders": int(r[4]),
            "revenue": float(r[5]),
        }
        for r in res.rows
    ]
    cov = Coverage(months, sql, res.ms)
    with _lock:
        _cache[key] = (time.monotonic(), cov)
    return cov


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{LABELS[int(m) - 1]} {y}"


def mentioned_months(question: str) -> list[str]:
    found = []
    for name, year in NAMED_MONTH_RE.findall(question):
        found.append(f"{year}-{MONTH_NAMES[name[:3].lower()]:02d}")
    for year, month in ISO_MONTH_RE.findall(question):
        found.append(f"{year}-{int(month):02d}")
    for month, year in US_MONTH_RE.findall(question):
        found.append(f"{year}-{int(month):02d}")
    return list(dict.fromkeys(found))


def mentioned_years(question: str) -> list[int]:
    stripped = ISO_MONTH_RE.sub(" ", US_MONTH_RE.sub(" ", question))
    return sorted({int(y) for y in YEAR_RE.findall(stripped)})


def detect(question: str, cov: Coverage) -> Precheck | None:
    if ABOUT_RE.search(question):
        return Precheck("about_data")
    months = mentioned_months(question)
    years = mentioned_years(question)
    first_year, last_year = int(cov.first[:4]), int(cov.last[:4])
    outside_months = [m for m in months if not (cov.first <= m <= cov.last)]
    outside_years = [y for y in years if not (first_year <= y <= last_year)]
    if outside_months or outside_years:
        labels = [month_label(m) for m in outside_months] + [
            str(y) for y in outside_years if all(not m.startswith(str(y)) for m in outside_months)
        ]
        return Precheck("out_of_range", outside_months, outside_years, " and ".join(labels))
    if not WHY_RE.search(question):
        return None
    if months:
        # Sparse = outside the analysis window, the rule trends and baselines use. (The
        # partial flag, under 500 orders, is data-specific: in the synthetic CI data every
        # month has about 400 orders, and using it intercepted ordinary questions.)
        partial = [m for m in months if cov.get(m) and not cov.get(m)["in_window"]]
        if partial:
            return Precheck("partial_period", months, [], " and ".join(map(month_label, months)))
        return None
    # A whole year that the data only partly covers (2016: four sparse months).
    partial_years = [
        y
        for y in years
        if all(not m["in_window"] for m in cov.months if m["month"].startswith(str(y)))
    ]
    if partial_years and len(partial_years) == len(years):
        months = [m["month"] for m in cov.months if int(m["month"][:4]) in partial_years]
        return Precheck("partial_period", months, partial_years, " and ".join(map(str, years)))
    return None


# ---------------- responses ----------------
def _money(v: float) -> str:
    return f"R${v:,.0f}"


def _evidence(cov: Coverage, rows: list[list]) -> Evidence:
    return Evidence(
        id="e1",
        sql=cov.sql,
        row_count=len(cov.months),
        rows_preview=[[normalise_value(v) for v in r] for r in rows[:10]],
        validator=ValidatorOut(ok=True, rules_checked=list(RULES)),
        ms=cov.ms,
    )


def _window_text(cov: Coverage) -> tuple[str, str, str, str]:
    w = cov.window()
    return (
        month_label(cov.first),
        month_label(cov.last),
        month_label(w[0]["month"]),
        month_label(w[-1]["month"]),
    )


def partial_response(pre: Precheck, cov: Coverage, request_id: str) -> AskResponse:
    first, last, w_start, w_end = _window_text(cov)
    window = cov.window()
    typical_orders = round(statistics.median(m["orders"] for m in window))
    typical_revenue = round(statistics.median(m["revenue"] for m in window))
    rows_m = [cov.get(m) for m in pre.months if cov.get(m)]
    orders = sum(m["orders"] for m in rows_m)
    revenue = round(sum(m["revenue"] for m in rows_m), 2)

    typical_label = f"Typical month ({w_start} to {w_end}, median)"
    columns = ["period", "orders", "delivered_orders", "revenue", "partial_month"]
    rows = [
        [
            month_label(m["month"]),
            m["orders"],
            m["delivered_orders"],
            m["revenue"],
            not m["in_window"],
        ]
        for m in rows_m
    ]
    rows.append([typical_label, typical_orders, None, float(typical_revenue), False])

    if len(rows_m) == 1 and orders == 0:
        headline = (
            f"The data has no orders at all in {pre.label}: the month is a gap in the data's "
            f"coverage, against about {typical_orders:,} orders in a typical month."
        )
    else:
        total = "" if len(rows_m) == 1 else " in total"
        headline = (
            f"{pre.label} is only partly covered by this data: {orders:,} orders and "
            f"{_money(revenue)} revenue{total}, against about {typical_orders:,} orders and "
            f"{_money(typical_revenue)} in a typical month."
        )
    notes = [
        f"The orders run from {first} to {last}, but only {w_start} to {w_end} has steady "
        "volume; the months before and after it have very few orders.",
        "So a low figure here reflects how much of the period the data covers, not how the "
        "business performed.",
    ]
    if any(m["orders"] == 0 for m in rows_m) and orders > 0:
        empty = ", ".join(month_label(m["month"]) for m in rows_m if m["orders"] == 0)
        notes.append(f"{empty} has no orders at all: a gap in the data.")
    return AskResponse(
        request_id=request_id,
        route="answer",
        status="ok",
        headline=headline,
        components=[
            {"type": "chart", "kind": "bar", "x": "period", "y": ["orders"]},
            {"type": "table", "columns": columns, "rows": rows},
        ],
        scope=ScopeOut(
            period=Period(start=min(pre.months) + "-01", end=max(pre.months) + "-01", source="sql"),
            definitions=[
                "Partial month: fewer than 500 orders in the data",
                "Typical month: the median month of the analysis window",
                "Revenue: item prices of orders that are not canceled or unavailable",
            ],
            assumptions=["Answered from the data's coverage, without a model call"],
            n=orders,
        ),
        evidence=[_evidence(cov, rows)],
        notes=notes,
        caveats=["The dataset does not say why these months are sparse."],
        followups=_followups(
            [
                f"What was the monthly revenue from {w_start} to {w_end}?",
                "How is the late-delivery rate trending?",
            ]
        ),
    )


def out_of_range_response(pre: Precheck, cov: Coverage, request_id: str) -> AskResponse:
    first, last, w_start, w_end = _window_text(cov)
    return AskResponse(
        request_id=request_id,
        route="answer",
        status="not_available",
        headline=f"There is no data for {pre.label}: the orders run from {first} to {last}.",
        notes=[
            f"Questions about {first} to {last} can be answered; trends and monthly "
            f"comparisons use {w_start} to {w_end}, the months with steady volume.",
        ],
        scope=ScopeOut(assumptions=["Answered from the data's coverage, without a model call"]),
        evidence=[_evidence(cov, [])],
        followups=_followups(
            [
                f"What was the monthly revenue in {w_end[-4:]}?",
                "How is the late-delivery rate trending?",
            ]
        ),
    )


SAMPLE_SQL = """
SELECT order_id, order_status, purchase_date, customer_state, item_count, items_revenue,
       review_score
FROM orders ORDER BY order_id LIMIT 5"""


def about_response(request_id: str, settings=None) -> AskResponse:
    cat = build_catalog(settings)
    f = cat["facts"]
    sql, sample = _run(SAMPLE_SQL, settings=settings)
    first, last = month_label(f["first_month"]), month_label(f["last_month"])
    views = ", ".join(v["name"] for v in cat["views"])
    return AskResponse(
        request_id=request_id,
        route="about",
        status="ok",
        headline=(
            f"This is the {cat['dataset']['name']} data: {f['orders']:,} orders from {first} "
            f"to {last}, with their items, payments, delivery dates and review scores."
        ),
        components=[
            {
                "type": "about",
                "dataset": cat["dataset"],
                "facts": f,
                "views": [
                    {"name": v["name"], "description": v["description"]} for v in cat["views"]
                ],
                "examples": cat["examples"],
                "limits": cat["limits"],
            },
            {"type": "table", "columns": sample.columns, "rows": [list(r) for r in sample.rows]},
        ],
        notes=[
            cat["dataset"]["description"],
            f"The agent reads {len(cat['views'])} tables: {views}. The table below shows "
            f"{len(sample.rows)} example orders.",
            "Open the data guide for every table's columns, the definitions, and example "
            "questions by topic.",
        ],
        scope=ScopeOut(assumptions=["Answered from the data catalog, without a model call"]),
        evidence=[
            Evidence(
                id="e1",
                sql=sql,
                row_count=len(sample.rows),
                rows_preview=[[normalise_value(v) for v in r] for r in sample.rows],
                validator=ValidatorOut(ok=True, rules_checked=list(RULES)),
                ms=sample.ms,
            )
        ],
    )


def _followups(questions: list[str]) -> list[Followup]:
    return [Followup(label=q, question=q) for q in questions]


def respond(pre: Precheck, request_id: str, settings=None) -> AskResponse:
    if pre.kind == "about_data":
        return about_response(request_id, settings)
    cov = coverage(settings)
    if pre.kind == "out_of_range":
        return out_of_range_response(pre, cov, request_id)
    return partial_response(pre, cov, request_id)
