"""The catalog's glossary parsing and static text (no database)."""

import re

from orderintel.catalog import EXAMPLES, GLOSSARY, LIMITS, VIEWS, parse_glossary


def test_parses_terms_and_strips_markup():
    text = (
        "| Term | Definition | Where implemented |\n"
        "|---|---|---|\n"
        "| Late | A delivered order whose **date** is after `estimated` | `orders.is_late` |\n"
        "Not a table line\n"
    )
    assert parse_glossary(text) == [
        {"term": "Late", "definition": "A delivered order whose date is after estimated"}
    ]


def test_reads_the_real_glossary():
    terms = {d["term"] for d in parse_glossary(GLOSSARY.read_text(encoding="utf-8"))}
    assert {"Late", "Late rate", "Revenue", "Customer", "Partial period"} <= terms


def test_static_text_contains_no_figures():
    """Numbers shown in the guide must come from queries, never from hand-written text."""
    text = " ".join([*VIEWS.values(), *LIMITS])
    assert not re.search(r"\d{2,}", text.replace("2016 to 2018", ""))


def test_every_topic_has_example_questions():
    assert set(EXAMPLES) == {"Sales", "Delivery", "Customers", "Sellers", "Reviews", "Products"}
    assert all(len(qs) >= 2 for qs in EXAMPLES.values())
