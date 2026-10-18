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
