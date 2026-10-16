"""Scope statement for every answer (FR-08, FR-14) and output component choice (FR-09).

Both are computed by code from the validated SQL and the result rows, never by the model:
  * period: from the date literals the SQL compares against (exclusive upper bounds are
    turned into inclusive end dates); the whole data window when the SQL has none;
  * definitions applied: glossary terms whose implementing columns the SQL uses;
  * partial-period warnings: months in the period that analytics.data_coverage flags;
  * component: answer card, line chart, table (+ bar chart for 8 groups or fewer).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from functools import lru_cache

import sqlglot
from sqlglot import exp

DATA_START, DATA_END = dt.date(2016, 9, 4), dt.date(2018, 10, 17)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# column -> glossary term shown in the scope panel
DEFINITIONS: dict[str, str] = {
    "is_late": "Late: delivered date after the estimated date (dates, not timestamps)",
    "days_late": "Late: delivered date after the estimated date (dates, not timestamps)",
    "is_delivered": "Delivered order: status delivered and a delivery timestamp exists",
    "is_sale": "Sale: status is not canceled or unavailable",
    "price": "Revenue: item prices of sales, excluding freight",
    "items_revenue": "Revenue: item prices of sales, excluding freight",
    "freight_value": "Freight: reported separately, never part of revenue",
    "freight_total": "Freight: reported separately, never part of revenue",
    "customer_unique_id": "Customer: a person (customer_unique_id), not an order",
    "review_score": "Review score: latest answered review per order",
    "seller_count": "Multi-seller order: more than one seller in the order",
    "payment_total": "Payments: one row per order (no fan-out)",
    "payment_types": "Payments: one row per order (no fan-out)",
    "primary_payment_type": "Primary payment type: type of the largest payment row",
    "category": "Category: English name; unknown if missing",
    "purchase_month": "Order month: month of the purchase timestamp",
    "seller_handling_days": "Seller handling days: carrier hand-off minus purchase",
    "carrier_transit_days": "Carrier transit days: delivery minus carrier hand-off",
}


@dataclass
class Scope:
    period_start: str
    period_end: str
    period_source: str  # sql | default
    definitions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    partial_period_warnings: list[str] = field(default_factory=list)
    n: int = 0
    truncated: bool = False


def _as_date(node: exp.Expression) -> dt.date | None:
    text = None
    if isinstance(node, exp.Literal) and node.is_string:
        text = node.this
    elif isinstance(node, exp.Cast) and isinstance(node.this, exp.Literal):
        text = node.this.this
    if text and DATE_RE.match(text):
        try:
            return dt.date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def extract_period(sql: str) -> tuple[dt.date, dt.date, str]:
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return DATA_START, DATA_END, "default"
    starts, ends = [], []
    for node in tree.find_all(exp.GTE, exp.GT, exp.LT, exp.LTE, exp.EQ):
        d = _as_date(node.expression) or _as_date(node.this)
        if d is None:
            continue
        literal_on_right = _as_date(node.expression) is not None
        kind = type(node)
        if kind is exp.EQ:
            starts.append(d)
            ends.append(d)
        elif (kind in (exp.GTE, exp.GT)) == literal_on_right:
            starts.append(d)
        else:
            ends.append(d - dt.timedelta(days=1) if kind in (exp.LT, exp.GT) else d)
    for b in tree.find_all(exp.Between):
        low, high = _as_date(b.args.get("low")), _as_date(b.args.get("high"))
        if low:
            starts.append(low)
        if high:
            ends.append(high)
    for e in tree.find_all(exp.EQ):  # extract(year FROM x) = 2017
        if isinstance(e.this, exp.Extract) and isinstance(e.expression, exp.Literal):
            unit = e.this.this.name.lower() if e.this.this else ""
            if unit == "year" and e.expression.this.isdigit():
                y = int(e.expression.this)
                starts.append(dt.date(y, 1, 1))
                ends.append(dt.date(y, 12, 31))
    if not starts and not ends:
        return DATA_START, DATA_END, "default"
    start = max(min(starts) if starts else DATA_START, DATA_START)
    end = min(max(ends) if ends else DATA_END, DATA_END)
    return start, end, "sql"


def columns_used(sql: str) -> set[str]:
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return set()
    return {c.name.lower() for c in tree.find_all(exp.Column)}


@lru_cache
def partial_months() -> tuple[tuple[dt.date, int], ...]:
    from orderintel.db.connect import connect_agent

    with connect_agent() as conn:
        rows = conn.execute(
            "SELECT month, orders_count FROM analytics.data_coverage WHERE is_partial ORDER BY 1"
        ).fetchall()
    return tuple(rows)


def build_scope(
    sql: str,
    assumptions: list[str],
    n: int,
    truncated: bool,
    partial: tuple[tuple[dt.date, int], ...] | None = None,
) -> Scope:
    start, end, source = extract_period(sql)
    used = columns_used(sql)
    definitions = list(dict.fromkeys(DEFINITIONS[c] for c in sorted(used) if c in DEFINITIONS))
    months = partial if partial is not None else partial_months()
    warnings = [
        f"{m:%Y-%m} is a partial month ({count} orders)"
        for m, count in months
        if dt.date(start.year, start.month, 1) <= m <= end
    ]
    return Scope(
        start.isoformat(),
        end.isoformat(),
        source,
        definitions,
        list(assumptions),
        warnings,
        n,
        truncated,
    )


# ---------------- output component (PRD section 8.1) ----------------
def _is_number(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) or type(v).__name__ == "Decimal"


def _is_date(v) -> bool:
    return isinstance(v, dt.date) or (isinstance(v, str) and bool(DATE_RE.match(v)))


RATE_COLUMN_RE = re.compile(r"rate|pct|percent|share", re.I)


def choose_components(columns: list[str], rows: list[tuple]) -> list[dict]:
    if not rows:
        return [{"type": "text", "variant": "empty", "text": "No rows matched the filters."}]
    if len(rows) == 1:
        return [
            {"type": "text", "variant": "answer_card", "columns": columns, "row": list(rows[0])}
        ]
    first = [r[0] for r in rows]
    numeric_cols = [
        i for i in range(1, len(columns)) if all(_is_number(r[i]) or r[i] is None for r in rows)
    ]
    table = {"type": "table", "columns": columns, "rows": [list(r) for r in rows]}
    if all(_is_date(v) for v in first) and numeric_cols:
        # Rates and counts have different scales: when both are present, the line chart shows
        # the rates only (the counts stay in the table). Found in the M9 end-to-end check.
        rates = [i for i in numeric_cols if RATE_COLUMN_RE.search(columns[i])]
        return [
            {
                "type": "chart",
                "kind": "line",
                "x": columns[0],
                "y": [columns[i] for i in (rates or numeric_cols)],
            },
            table,
        ]
    if numeric_cols and len(rows) <= 8:
        return [
            table,
            {"type": "chart", "kind": "bar", "x": columns[0], "y": [columns[numeric_cols[0]]]},
        ]
    return [table]
