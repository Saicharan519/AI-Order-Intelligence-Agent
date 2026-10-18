"""Business rules checked in code on validated SQL, before it runs.

The validator (guard/validator.py) decides whether SQL is SAFE to run. These rules decide
whether it follows the glossary's definitions. A violation is sent back to the SQL writer
through the repair loop, like a validator rejection; if the last repair still violates a
rule, the query runs and the answer carries a warning instead of being withheld.

Revenue rule: revenue counts sales only (orders whose status is not canceled or
unavailable). Every SUM or AVG over `items_revenue` or `price` must itself be limited to
sales: by a FILTER on the aggregate, a condition inside it (CASE WHEN is_sale ...), the
WHERE or JOIN conditions of its own SELECT, or a CTE or subquery it reads from that is
limited to sales. `order_status` counts as an explicit choice, for questions about canceled
or unavailable orders on purpose. Found by owner testing: the SQL writer summed
`items_revenue` over all orders while using is_sale only to count sale orders, so March
2018 revenue came out R$983,213 instead of R$981,051. The rule is checked per aggregate,
because a whole-query check was fooled by exactly that query.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

REVENUE_COLUMNS = frozenset({"items_revenue", "price"})
SALE_COLUMNS = frozenset({"is_sale", "order_status"})

REVENUE_FEEDBACK = (
    "Revenue counts sales only (glossary): {agg} is not limited to sales. Add is_sale to that "
    "aggregate (for example SUM(items_revenue) FILTER (WHERE is_sale), or WHERE is_sale in its "
    "SELECT). If the question is about canceled or unavailable orders on purpose, filter "
    "order_status explicitly instead."
)


def _mentions_sale(node: exp.Expression | None) -> bool:
    return node is not None and any(
        c.name.lower() in SALE_COLUMNS for c in node.find_all(exp.Column)
    )


def _select_limited_to_sales(select: exp.Select, ctes: dict[str, exp.Expression]) -> bool:
    """WHERE, JOIN conditions, or a source (CTE or subquery) already limited to sales."""
    if _mentions_sale(select.args.get("where")):
        return True
    for join in select.args.get("joins") or []:
        if _mentions_sale(join.args.get("on")):
            return True
    sources = []
    from_ = select.args.get("from_") or select.args.get("from")  # renamed in sqlglot 30
    if from_ is not None:
        sources.append(from_.this)
    sources += [j.this for j in select.args.get("joins") or []]
    for src in sources:
        inner = None
        if isinstance(src, exp.Subquery):
            inner = src.this
        elif isinstance(src, exp.Table) and src.name.lower() in ctes:
            inner = ctes[src.name.lower()]
        if isinstance(inner, exp.Select) and _select_limited_to_sales(inner, ctes):
            return True
    return False


def revenue_violations(sql: str) -> list[str]:
    """Feedback for each revenue aggregate that is not limited to sales (empty when none)."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return []  # the validator has already accepted it; never block on our own parser
    ctes = {cte.alias.lower(): cte.this for cte in tree.find_all(exp.CTE)}
    problems = []
    for agg in tree.find_all(exp.Sum, exp.Avg):
        if not {c.name.lower() for c in agg.find_all(exp.Column)} & REVENUE_COLUMNS:
            continue
        if _mentions_sale(agg):  # CASE WHEN is_sale THEN ... inside the aggregate
            continue
        if isinstance(agg.parent, exp.Filter) and _mentions_sale(agg.parent.expression):
            continue
        select = agg.find_ancestor(exp.Select)
        if select is not None and _select_limited_to_sales(select, ctes):
            continue
        problems.append(REVENUE_FEEDBACK.format(agg=agg.sql(dialect="postgres")))
    return list(dict.fromkeys(problems))


def violations(sql: str) -> list[str]:
    return revenue_violations(sql)
