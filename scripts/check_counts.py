"""Profile the raw tables and reproduce the PRD's dataset figures with our own SQL.

Two kinds of check:
  * required: row and null counts the loader contract depends on (IMPLEMENTATION_PLAN M1).
    Any mismatch makes the script exit with status 1.
  * prd: figures quoted in PRD sections 5.2 and 5.3. A mismatch is reported (not fatal)
    so the PRD can be corrected; these become regression tests once confirmed.

All queries run on raw.* (no views exist yet), so they double as independent references
for checking the analytics views in M2.

Usage:
    python scripts/check_counts.py [--write docs/data_profile.md]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from orderintel.db.connect import connect_owner

# Delivered = status delivered AND a customer delivery timestamp exists (PRD section 6).
DELIVERED = """
    order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
"""
LATE_BY_DATE = "order_delivered_customer_date::date > order_estimated_delivery_date::date"
LATE_BY_TS = "order_delivered_customer_date > order_estimated_delivery_date"


@dataclass
class Check:
    name: str
    query: str
    expected: object
    kind: str = "prd"  # "required" or "prd"
    tolerance: float = 0.0  # relative tolerance for rounded PRD figures


def null_check(table: str, column: str, expected: int) -> Check:
    return Check(
        f"nulls: raw.{table}.{column}",
        f"SELECT count(*) FROM raw.{table} WHERE {column} IS NULL",  # noqa: S608
        expected,
        "required",
    )


CHECKS: list[Check] = [
    # --- required (loader contract) ---
    null_check("orders", "order_approved_at", 160),
    null_check("orders", "order_delivered_carrier_date", 1_783),
    null_check("orders", "order_delivered_customer_date", 2_965),
    null_check("products", "product_category_name", 610),
    null_check("order_reviews", "review_comment_message", 58_247),
    Check(
        "estimated delivery date is always midnight (rows not at midnight)",
        "SELECT count(*) FROM raw.orders "
        "WHERE order_estimated_delivery_date <> order_estimated_delivery_date::date",
        0,
        "required",
    ),
    # --- PRD 5.2 data window ---
    Check("first purchase date", "SELECT min(order_purchase_timestamp)::date::text FROM raw.orders",
          "2016-09-04"),
    Check("last purchase date", "SELECT max(order_purchase_timestamp)::date::text FROM raw.orders",
          "2018-10-17"),
    Check(
        "months with < 500 orders (month:count)",
        """SELECT string_agg(m || ':' || n, ', ' ORDER BY m) FROM (
             SELECT to_char(order_purchase_timestamp, 'YYYY-MM') m, count(*) n
             FROM raw.orders GROUP BY 1 HAVING count(*) < 500) s""",
        "2016-09:4, 2016-10:324, 2016-12:1, 2018-09:16, 2018-10:4",
    ),
    # --- PRD 5.3: undelivered orders and the definition of late ---
    Check("orders not in delivered status",
          "SELECT count(*) FROM raw.orders WHERE order_status <> 'delivered'", 2_963),
    Check("'delivered' orders without a delivery date",
          "SELECT count(*) FROM raw.orders WHERE order_status = 'delivered' "
          "AND order_delivered_customer_date IS NULL", 8),
    Check("non-delivered orders with a delivery date",
          "SELECT count(*) FROM raw.orders WHERE order_status <> 'delivered' "
          "AND order_delivered_customer_date IS NOT NULL", 6),
    Check("delivered orders (status delivered + date)",
          f"SELECT count(*) FROM raw.orders WHERE {DELIVERED}", 96_470),  # noqa: S608
    Check("late by DATE comparison",
          f"SELECT count(*) FROM raw.orders WHERE {DELIVERED} AND {LATE_BY_DATE}", 6_534),  # noqa: S608
    Check("late by TIMESTAMP comparison (not used)",
          f"SELECT count(*) FROM raw.orders WHERE {DELIVERED} AND {LATE_BY_TS}", 7_826),  # noqa: S608
    Check("same-day deliveries marked late only by timestamp",
          f"SELECT count(*) FROM raw.orders WHERE {DELIVERED} AND {LATE_BY_TS} "  # noqa: S608
          f"AND NOT ({LATE_BY_DATE})", 1_292),
    Check("late rate by date (%)",
          f"SELECT round(100.0 * count(*) FILTER (WHERE {LATE_BY_DATE}) / count(*), 2) "  # noqa: S608
          f"FROM raw.orders WHERE {DELIVERED}", 6.77, tolerance=0.001),
    Check("late rate by timestamp (%)",
          f"SELECT round(100.0 * count(*) FILTER (WHERE {LATE_BY_TS}) / count(*), 2) "  # noqa: S608
          f"FROM raw.orders WHERE {DELIVERED}", 8.11, tolerance=0.001),
    # --- customer identity ---
    Check("distinct customer_id", "SELECT count(DISTINCT customer_id) FROM raw.customers", 99_441),
    Check("distinct customer_unique_id (people)",
          "SELECT count(DISTINCT customer_unique_id) FROM raw.customers", 96_096),
    Check(
        "people with more than one order",
        """SELECT count(*) FROM (SELECT c.customer_unique_id FROM raw.orders o
             JOIN raw.customers c USING (customer_id)
             GROUP BY 1 HAVING count(DISTINCT o.order_id) > 1) s""",
        2_997,
    ),
    # --- payment fan-out ---
    Check("orders with more than one payment row",
          "SELECT count(*) FROM (SELECT order_id FROM raw.order_payments "
          "GROUP BY 1 HAVING count(*) > 1) s", 2_961),
    Check("item revenue, sum(price), all orders",
          "SELECT sum(price) FROM raw.order_items", 13_591_644, tolerance=0.0001),
    Check("item revenue after naive join to payments (inflated)",
          "SELECT sum(i.price) FROM raw.order_items i JOIN raw.order_payments p USING (order_id)",
          14_209_115, tolerance=0.0001),
    Check(
        "fan-out inflation (%)",
        """SELECT round(100.0 * (
             (SELECT sum(i.price) FROM raw.order_items i JOIN raw.order_payments p USING (order_id))
             / (SELECT sum(price) FROM raw.order_items) - 1), 2)""",
        4.54, tolerance=0.001,
    ),
    # --- duplicate reviews ---
    Check("review rows minus distinct review_id",
          "SELECT count(*) - count(DISTINCT review_id) FROM raw.order_reviews", 814),
    Check("distinct reviewed orders",
          "SELECT count(DISTINCT order_id) FROM raw.order_reviews", 98_673),
    Check("orders with more than one review",
          "SELECT count(*) FROM (SELECT order_id FROM raw.order_reviews "
          "GROUP BY 1 HAVING count(*) > 1) s", 547),
    Check(
        "reviews created before the delivery date (% of reviews of delivered orders)",
        f"""SELECT round(100.0 * count(*) FILTER (
               WHERE r.review_creation_date::date < o.order_delivered_customer_date::date)
               / count(*), 1)
            FROM raw.order_reviews r JOIN raw.orders o USING (order_id)
            WHERE {DELIVERED}""",  # noqa: S608
        5.0, tolerance=0.2,
    ),
    # --- categories ---
    Check("products with no category",
          "SELECT count(*) FROM raw.products WHERE product_category_name IS NULL", 610),
    Check(
        "categories with no English translation",
        """SELECT count(DISTINCT p.product_category_name) FROM raw.products p
             LEFT JOIN raw.product_category_name_translation t USING (product_category_name)
             WHERE p.product_category_name IS NOT NULL
               AND t.product_category_name IS NULL""",
        2,
    ),
    # --- sellers ---
    Check("orders with more than one seller",
          "SELECT count(*) FROM (SELECT order_id FROM raw.order_items "
          "GROUP BY 1 HAVING count(DISTINCT seller_id) > 1) s", 1_278),
    Check("median orders per seller",
          """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n) FROM (
               SELECT seller_id, count(DISTINCT order_id) n FROM raw.order_items GROUP BY 1) s""",
          6),
    Check("sellers with fewer than 5 orders",
          "SELECT count(*) FROM (SELECT seller_id FROM raw.order_items "
          "GROUP BY 1 HAVING count(DISTINCT order_id) < 5) s", 1_301),
    Check("sellers with at least 30 orders",
          "SELECT count(*) FROM (SELECT seller_id FROM raw.order_items "
          "GROUP BY 1 HAVING count(DISTINCT order_id) >= 30) s", 634),
    Check(
        "revenue share of sellers with >= 30 orders (%)",
        """WITH s AS (SELECT seller_id, count(DISTINCT order_id) n, sum(price) rev
                      FROM raw.order_items GROUP BY 1)
           SELECT round(100.0 * sum(rev) FILTER (WHERE n >= 30) / sum(rev), 1) FROM s""",
        76.8, tolerance=0.001,
    ),
    Check(
        "sellers with a 100% late rate and <= 3 delivered orders",
        f"""SELECT count(*) FROM (
              SELECT i.seller_id,
                     count(DISTINCT o.order_id) n,
                     count(DISTINCT o.order_id) FILTER (WHERE {LATE_BY_DATE}) late
              FROM raw.order_items i JOIN raw.orders o USING (order_id)
              WHERE {DELIVERED}
              GROUP BY 1) s
            WHERE n <= 3 AND late = n""",  # noqa: S608
        51,  # PRD v1.0 said 57, which is the timestamp-based count; corrected in PRD v1.2
    ),
    # --- PRD 6 / M2: revenue definition ---
    Check(
        "2017 item revenue, canceled/unavailable excluded",
        """SELECT sum(i.price) FROM raw.order_items i JOIN raw.orders o USING (order_id)
           WHERE o.order_purchase_timestamp >= '2017-01-01'
             AND o.order_purchase_timestamp <  '2018-01-01'
             AND o.order_status NOT IN ('canceled', 'unavailable')""",
        6_108_492, tolerance=0.0001,
    ),
    Check(
        "2017 orders with items, canceled/unavailable excluded",
        """SELECT count(DISTINCT o.order_id)
           FROM raw.order_items i JOIN raw.orders o USING (order_id)
           WHERE o.order_purchase_timestamp >= '2017-01-01'
             AND o.order_purchase_timestamp <  '2018-01-01'
             AND o.order_status NOT IN ('canceled', 'unavailable')""",
        44_375,
    ),
    Check(
        "2017 revenue change if canceled/unavailable were included (%)",
        """WITH r AS (SELECT sum(i.price) total,
                        sum(i.price) FILTER (
                          WHERE o.order_status NOT IN ('canceled','unavailable')) sale
                      FROM raw.order_items i JOIN raw.orders o USING (order_id)
                      WHERE o.order_purchase_timestamp >= '2017-01-01'
                        AND o.order_purchase_timestamp <  '2018-01-01')
           SELECT round(100.0 * (total / sale - 1), 2) FROM r""",
        0.77, tolerance=0.001,
    ),
    # --- relationships (raw tables have no foreign keys; orphans are measured here) ---
    Check("orphans: order_items without an order",
          "SELECT count(*) FROM raw.order_items i "
          "WHERE NOT EXISTS (SELECT 1 FROM raw.orders o WHERE o.order_id = i.order_id)", 0),
    Check("orphans: orders without a customer",
          "SELECT count(*) FROM raw.orders o WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.customers c WHERE c.customer_id = o.customer_id)", 0),
    Check("orphans: payments without an order",
          "SELECT count(*) FROM raw.order_payments p WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.orders o WHERE o.order_id = p.order_id)", 0),
    Check("orphans: reviews without an order",
          "SELECT count(*) FROM raw.order_reviews r WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.orders o WHERE o.order_id = r.order_id)", 0),
    Check("orphans: items without a product",
          "SELECT count(*) FROM raw.order_items i WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.products p WHERE p.product_id = i.product_id)", 0),
    Check("orphans: items without a seller",
          "SELECT count(*) FROM raw.order_items i WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.sellers s WHERE s.seller_id = i.seller_id)", 0),
    Check("orders with no items (informational)",
          "SELECT count(*) FROM raw.orders o WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.order_items i WHERE i.order_id = o.order_id)", None),
    Check("orders with no payment row (informational)",
          "SELECT count(*) FROM raw.orders o WHERE NOT EXISTS "
          "(SELECT 1 FROM raw.order_payments p WHERE p.order_id = o.order_id)", None),
]


def normalise(value: object) -> object:
    """Decimal and float become int when whole, else float, so comparisons are uniform."""
    if isinstance(value, Decimal | float):
        f = float(value)
        return int(f) if f.is_integer() else f
    return value


def matches(actual: object, check: Check) -> bool | None:
    if check.expected is None:
        return None
    if check.tolerance and isinstance(actual, int | float):
        return abs(actual - check.expected) <= check.tolerance * abs(check.expected)  # type: ignore[operator]
    return actual == check.expected


def run() -> list[tuple[Check, object, bool | None]]:
    results = []
    with connect_owner() as conn:
        conn.read_only = True
        for c in CHECKS:
            actual = normalise(conn.execute(c.query).fetchone()[0])
            results.append((c, actual, matches(actual, c)))
    return results


def fmt(v: object) -> str:
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "-" if v is None else str(v)


def to_markdown(results: list[tuple[Check, object, bool | None]]) -> str:
    lines = [
        "| Check | Kind | Expected | Actual | Status |",
        "|---|---|---|---|---|",
    ]
    for c, actual, ok in results:
        status = "info" if ok is None else ("match" if ok else "**DIFFERS**")
        exp = fmt(c.expected) + (f" (+/-{c.tolerance:.2%})" if c.tolerance else "")
        lines.append(f"| {c.name} | {c.kind} | {exp} | {fmt(actual)} | {status} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile raw.* and check PRD figures")
    parser.add_argument("--write", type=Path, help="write the results table to this markdown file")
    args = parser.parse_args(argv)

    results = run()
    table = to_markdown(results)
    print(table)
    if args.write:
        args.write.write_text(
            "# Data profile (generated by scripts/check_counts.py)\n\n"
            "Do not edit by hand; re-run the script.\n\n" + table + "\n",
            encoding="utf-8",
            newline="\n",  # LF on every OS, matching .gitattributes
        )

    failed_required = [c.name for c, _, ok in results if c.kind == "required" and ok is False]
    differs = [c.name for c, _, ok in results if c.kind == "prd" and ok is False]
    print(
        f"\nrequired checks failed: {len(failed_required)}; "
        f"PRD figures differing: {len(differs)}"
    )
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
