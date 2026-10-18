"""Data catalog for the "Explore the data" guide (GET /v1/catalog).

Answers "what is in this dataset and what can I ask?" without a model call. Every number
comes from fixed, read-only queries run as oi_agent over the same analytics views the agent
queries, so the guide always matches the loaded data (the real load or the synthetic CI
fixture). Definitions are parsed from glossary/glossary.md, the same file the model is
shown, so the guide and the agent share one source. The text below (descriptions, example
questions, limits) contains no figures.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from orderintel.agent.guards import MISSING_FIELDS
from orderintel.config import Settings, get_settings
from orderintel.db.connect import connect_agent
from orderintel.guard.allowlists import load_allowlist

GLOSSARY = Path(__file__).resolve().parents[2] / "glossary" / "glossary.md"
CACHE_SECONDS = 600

VIEWS: dict[str, str] = {
    "orders": "One row per order: customer, status, purchase and delivery dates, lateness, "
    "delivery stages, revenue, freight, payment total and review score.",
    "order_items": "One row per item in an order: product, category, seller, price and freight.",
    "payments": "One row per order: payment total, number of payments, installments and "
    "payment types.",
    "reviews": "One row per order: the latest review score and whether it has a comment "
    "(the comment text itself is not available).",
    "sellers": "One row per seller: seller id, city and state (no seller names).",
    "data_coverage": "One row per month: number of orders, whether the month is partial, and "
    "whether it is inside the analysis window.",
}

# The guide's overview, in sections. No figures here: the counts and the timeline next to
# it come from the data (a unit test enforces this).
OVERVIEW: list[dict] = [
    {
        "title": "What Olist is",
        "text": "Olist is a Brazilian e-commerce company that lets small and medium-sized shops "
        "sell on large online marketplaces under a single contract. A customer buys on a "
        "marketplace, Olist passes the order to the shop that sells the product (the seller), "
        "the seller packs it and hands it to a carrier, and the carrier delivers it to the "
        "customer anywhere in Brazil. This dataset is a real, anonymised extract of those "
        "orders, published by Olist for research and learning.",
    },
    {
        "title": "The life of one order",
        "text": "Each order belongs to one customer and has one or more items. Every item is one "
        "product from one seller, with its own price and freight charge. The order records "
        "when it was bought, when the payment was approved, when the seller handed it to the "
        "carrier, when it reached the customer, and the delivery date promised at purchase, "
        "so the data shows how long each stage took and whether the promise was kept. After "
        "delivery the customer can review the order with a score from one to five stars "
        "(the review text itself is not in the data).",
        "steps": [
            "Customer buys",
            "Payment approved",
            "Seller hands to carrier",
            "Delivered",
            "Customer reviews",
        ],
    },
    {
        "title": "What you can learn from it",
        "text": "Sales: revenue and orders by month, category, state, seller and payment type, "
        "and the average order value. Delivery: how often orders arrive late, how long seller "
        "handling and carrier transit take, and where late orders concentrate. Customers: "
        "where they live and how many come back. Reviews: how scores move, and how they "
        "differ between late and on-time orders. For a bad month, an investigation compares "
        "it with the other months and shows where the change happened.",
    },
    {
        "title": "Things to know before you ask",
        "text": "Customers and sellers appear only as ids with their city and state: there are "
        "no names. Money is in Brazilian reais (R$); revenue counts item prices of orders that "
        "were not canceled or unavailable, and freight is reported separately. The data is "
        "thin in its first and last months (see the timeline), so trends use the steady "
        'months in between, and "today" means the end of the data. Payments can be by '
        "credit card (often in installments), boleto (a Brazilian bank slip), voucher or "
        "debit card.",
    },
    {
        "title": "How the agent answers",
        "text": "Each question becomes one read-only SQL query over the six tables below, or a "
        "fixed set of queries for an investigation. The query is checked before it runs, the "
        "result is computed by the database, and every number in the written answer is traced "
        "back to that result. The Evidence tab of each answer shows the exact SQL. The data "
        "shows what happened and where; it cannot show why.",
    },
]

EXAMPLES: dict[str, list[str]] = {
    "Sales": [
        "Top 5 categories by revenue in 2017",
        "What was the monthly revenue in 2018?",
        "What is the average order value by payment type?",
    ],
    "Delivery": [
        "How is the late-delivery rate trending?",
        "Which states have the highest late-delivery rate?",
        "Why was March 2018 so bad for deliveries?",
    ],
    "Customers": [
        "How many customers placed more than one order?",
        "Which 5 states have the most customers?",
    ],
    "Sellers": [
        "Which 5 sellers had the most orders in 2018?",
        "Which seller states have the highest average review score?",
    ],
    "Reviews": [
        "How does the review score differ for late and on-time orders?",
        "What share of reviews are 1-star by month?",
    ],
    "Products": [
        "Which categories have the highest freight cost per item?",
        "How many distinct products were sold in 2017?",
    ],
}

LIMITS: list[str] = [
    "No names: sellers and customers are identified by ids, city and state only.",
    "No profit or costs: revenue is item prices; freight is reported separately.",
    "No review text: only scores and whether a comment exists.",
    "No forecasts or predictions: the data describes 2016 to 2018 only.",
    "No causes: the data shows where and when something happened, not why.",
    "No changes: the agent can only read the data, never modify it.",
]


def parse_glossary(text: str) -> list[dict[str, str]]:
    """(term, definition) from the glossary's markdown tables, markup removed."""
    out = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not line.lstrip().startswith("|"):
            continue
        term, definition = cells[0], cells[1]
        if term in ("Term", "") or set(term) <= {"-", ":", " "}:
            continue
        clean = lambda s: re.sub(r"[*`]", "", s).strip()  # noqa: E731
        out.append({"term": clean(term), "definition": clean(definition)})
    return out


def _facts(settings: Settings) -> dict:
    with connect_agent(settings) as conn:
        orders, delivered, customers, states = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_delivered), "
            "count(DISTINCT customer_unique_id), count(DISTINCT customer_state) "
            "FROM analytics.orders"
        ).fetchone()
        sellers = conn.execute("SELECT count(*) FROM analytics.sellers").fetchone()[0]
        products, categories = conn.execute(
            "SELECT count(DISTINCT product_id), count(DISTINCT category) FROM analytics.order_items"
        ).fetchone()
        months = conn.execute(
            "SELECT month, orders_count, is_partial, in_analysis_window "
            "FROM analytics.data_coverage ORDER BY month"
        ).fetchall()
        columns = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'analytics' ORDER BY table_name, ordinal_position"
        ).fetchall()
    window = [m for m in months if m[3]]
    return {
        "orders": orders,
        "delivered_orders": delivered,
        "customers": customers,
        "customer_states": states,
        "sellers": sellers,
        "products": products,
        "categories": categories,
        "first_month": months[0][0].isoformat()[:7] if months else None,
        "last_month": months[-1][0].isoformat()[:7] if months else None,
        "analysis_window": (
            {"start": window[0][0].isoformat()[:7], "end": window[-1][0].isoformat()[:7]}
            if window
            else None
        ),
        "partial_months": [{"month": m[0].isoformat()[:7], "orders": m[1]} for m in months if m[2]],
        # Every month, for the guide's timeline: where the data is thin and which months
        # trends use.
        "months": [
            {"month": m[0].isoformat()[:7], "orders": m[1], "partial": m[2], "in_window": m[3]}
            for m in months
        ],
        "_columns": columns,
    }


def build_catalog(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    facts = _facts(s)
    by_view: dict[str, list[str]] = {}
    for table, column in facts.pop("_columns"):
        by_view.setdefault(table, []).append(column)
    # Column descriptions are the database comments the SQL writer is shown (allowlist.json).
    comments = {
        view: {c: (meta.get("comment") or "") for c, meta in spec["columns"].items()}
        for view, spec in load_allowlist()["views"].items()
    }
    return {
        "dataset": {
            "name": "Olist Brazilian e-commerce orders",
            "description": "Orders placed on Olist, a Brazilian online marketplace that connects "
            "small sellers to customers. Each order has its items, payments, delivery dates "
            "and customer review score.",
            "source": "Public Olist dataset (Kaggle, CC BY-NC-SA 4.0)",
            "overview": OVERVIEW,
        },
        "facts": facts,
        "views": [
            {
                "name": v,
                "description": VIEWS.get(v, ""),
                "columns": cols,
                "column_notes": {c: comments.get(v, {}).get(c, "") for c in cols},
            }
            for v, cols in by_view.items()
            if v in VIEWS
        ],
        "definitions": parse_glossary(GLOSSARY.read_text(encoding="utf-8")),
        "examples": [{"topic": t, "questions": qs} for t, qs in EXAMPLES.items()],
        "limits": LIMITS,
        # Fields people ask for that do not exist, with the closest one that does: the same
        # list the agent uses to explain such questions (agent/guards.py).
        "missing_fields": [{"field": m, "closest": c} for _, m, c in MISSING_FIELDS],
    }


class CatalogCache:
    """The catalog changes only when the data is reloaded, so it is cached for a while."""

    def __init__(self, settings: Settings | None = None, ttl: float = CACHE_SECONDS) -> None:
        self._settings, self._ttl = settings, ttl
        self._value: dict | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self._value is None or time.monotonic() - self._at > self._ttl:
                self._value = build_catalog(self._settings)
                self._at = time.monotonic()
            return self._value
