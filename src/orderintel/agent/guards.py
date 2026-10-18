"""Deterministic guards around the router: the question's topic, missing fields, follow-ups.

All three read only the question text (regular expressions), so they behave the same every
time and cost nothing.

* topic_of / guard_playbook: the router may pick a playbook whose topic differs from the
  question's ("why was revenue low?" sent to the late-delivery playbook, found in owner
  testing and in the M10 model comparison). The guard corrects the playbook when the topic
  is clear, and sends sales questions to the answer route, since no sales playbook exists.
* missing_fields: fields users often ask for that the data does not contain, each with the
  closest field that does exist. Used as a hint to the router and SQL writer, and shown in
  refusals and answers, so "product names" gets "no names; ids and categories instead".
* looks_like_followup: questions that refer to the previous answer ("these categories",
  "and in 2018?"); only those get the previous answer as context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SALES_RE = re.compile(
    r"\b(revenue|sales?|sold|sell(?:s|ing)?|gmv|turnover|income|earn\w*|money|order value|aov"
    r"|ticket|prices?|basket|spend\w*|purchases?|freight|payments?|order volume|number of orders"
    r"|orders? count|how many orders)\b",
    re.I,
)
DELIVERY_RE = re.compile(
    r"\b(late|lateness|deliver\w*|shipping|ship\w*|transit|carrier|logistic\w*|on[- ]time"
    r"|delay\w*|arriv\w*|dispatch\w*|handling)\b",
    re.I,
)
REVIEWS_RE = re.compile(
    r"\b(reviews?|rating\w*|scores?|stars?|satisf\w*|complain\w*|1-star|one-star|unhappy"
    r"|happy|feedback)\b",
    re.I,
)

PLAYBOOK_TOPIC = {"late_delivery_diagnosis": "delivery", "low_review_diagnosis": "reviews"}
TOPIC_PLAYBOOK = {v: k for k, v in PLAYBOOK_TOPIC.items()}


def topic_of(question: str) -> set[str]:
    topics = set()
    if SALES_RE.search(question):
        topics.add("sales")
    if DELIVERY_RE.search(question):
        topics.add("delivery")
    if REVIEWS_RE.search(question):
        topics.add("reviews")
    return topics


@dataclass
class PlaybookGuard:
    playbook: str | None  # the playbook to run, or None to answer with SQL instead
    note: str = ""  # shown to the user when the router's choice was changed


def guard_playbook(question: str, playbook: str) -> PlaybookGuard:
    """Keep the router's playbook when the question's topic allows it; otherwise correct it."""
    topics = topic_of(question)
    wanted = PLAYBOOK_TOPIC[playbook]
    if not topics or wanted in topics:
        return PlaybookGuard(playbook)  # "Why was March 2018 so bad?" has no topic words
    other = (topics & set(TOPIC_PLAYBOOK)) - {wanted}
    if other:
        right = TOPIC_PLAYBOOK[sorted(other)[0]]
        return PlaybookGuard(
            right, f"The question is about {sorted(other)[0]}, so that investigation was run."
        )
    return PlaybookGuard(
        None,
        "There is no investigation for sales yet, so this answer describes what the data "
        "shows for the period, not why it happened.",
    )


# Fields people ask for that the data does not contain: (pattern, missing, closest available).
MISSING_FIELDS = [
    (r"\bproducts?\s+(?:names?|titles?|descriptions?)\b|\bname of (?:the )?products?\b",
     "product names", "product id, category, and weight"),
    (r"\bsellers?\s+names?\b|\bname of (?:the )?sellers?\b|\bseller'?s name\b",
     "seller names", "seller id, city, and state"),
    (r"\bcustomers?\s+(?:names?|emails?|phones?|phone numbers?|addresses?|ages?|genders?)\b"
     r"|\bname of (?:the )?customers?\b",
     "customer names and contact details", "customer id, city, and state"),
    (r"\b(?:profits?|margins?|costs? of goods|cogs|net income)\b",
     "profit and costs", "revenue (item prices) and freight"),
    (r"\breview (?:text|comments?|messages?)\b|\bwhat (?:did )?customers (?:say|write)\b",
     "review text", "review scores and whether a review has a comment"),
    (r"\b(?:returns?|returned|refunds?|refunded)\b",
     "returns and refunds", "order status, such as canceled orders"),
    (r"\b(?:discounts?|coupons?|vouchers?|promo(?:tion)?s?)\b",
     "discounts and promotions", "payment types, including vouchers as a payment type"),
    (r"\b(?:stock|inventory|warehouse)\b", "stock and inventory", "items sold per product"),
    (r"\b(?:visits?|visitors|traffic|clicks?|page ?views?|conversion rate)\b",
     "website traffic", "orders and customers"),
]  # fmt: skip
_MISSING = [(re.compile(p, re.I), m, c) for p, m, c in MISSING_FIELDS]


def missing_fields(question: str) -> list[tuple[str, str]]:
    """(missing field, closest available) for each field the question asks for that the data
    does not contain."""
    return [(m, c) for rx, m, c in _MISSING if rx.search(question)]


def missing_field_notes(question: str) -> list[str]:
    return [
        f"The data has no {m}; the closest available is {c}." for m, c in missing_fields(question)
    ]


def missing_field_hint(question: str) -> str:
    """Appended to the question for the router and the SQL writer."""
    found = missing_fields(question)
    if not found:
        return ""
    parts = "; ".join(f"there are no {m}, use {c} instead" for m, c in found)
    return f"(Note from the data catalog: {parts}.)"


FOLLOWUP_RE = re.compile(
    r"\b(these|those|them|same|above|previous|instead|that one|each of them|the rest)\b"
    r"|^\s*(?:and|also|now|then|what about|how about|and what about|same for|but)\b"
    r"|\b(?:what|how) about\b",
    re.I,
)


def looks_like_followup(question: str) -> bool:
    return bool(FOLLOWUP_RE.search(question))
