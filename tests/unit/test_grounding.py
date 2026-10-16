"""Number grounding and causal lint (FR-07, technical design 8.5)."""

import datetime as dt
from decimal import Decimal as D

import pytest

from orderintel.agent.grounding import causal_findings, check_grounding, extract_numbers

TOP3 = [
    ("bed_bath_table", D("497971.04"), 4496),
    ("watches_gifts", D("486519.30"), 2114),
    ("health_beauty", D("481143.10"), 3382),
]


def untraced(prose, rows=TOP3, ctx=()):
    return check_grounding(prose, rows, list(ctx)).untraced


@pytest.mark.parametrize(
    "prose",
    [
        "bed_bath_table led with 497,971.04.",
        "bed_bath_table led with 497,971.",
        "bed_bath_table led with R$498k.",
        "bed_bath_table led with R$0.5M.",
        "It had 4,496 orders, about 4,500.",
        "The top three are within 3.5% of each other.",  # (497971/481143 - 1) * 100
        "Together they had 9,992 orders.",  # column total
        "bed_bath_table earned 11,451.74 more than watches_gifts.",  # difference
        "It was the top 1 of 3 categories in 2017.",  # small integers, year
    ],
)
def test_traceable_numbers(prose):
    assert untraced(prose) == []


@pytest.mark.parametrize(
    ("prose", "bad"),
    [
        ("bed_bath_table led with R$512k.", ["R$512k"]),
        ("Its share was 12.7%.", ["12.7%"]),
        ("It had 4,620 orders.", ["4,620"]),
        ("Revenue grew 23.4% versus 2016.", ["23.4%"]),
    ],
)
def test_fabricated_numbers_are_flagged(prose, bad):
    assert untraced(prose) == bad


def test_fraction_shown_as_percentage():
    assert untraced("The late rate was 6.8%.", rows=[(D("0.0677"),)]) == []


def test_rounding_respects_displayed_precision():
    rows = [(D("18.96"),)]
    assert untraced("19.0% were late.", rows) == []
    assert untraced("19% were late.", rows) == []
    assert untraced("18.5% were late.", rows) == ["18.5%"]


def test_numbers_in_question_and_scope_are_allowed():
    assert (
        untraced(
            "Orders in 2017 with at least 30 orders per seller.",
            rows=[(1,)],
            ctx=["sellers with at least 30 orders"],
        )
        == []
    )


def test_dates_are_not_treated_as_numbers():
    rows = [(dt.date(2018, 3, 1), D("18.96"))]
    assert untraced("On 2018-03-01 (month 2018-03) the rate was 18.96%.", rows) == []


def test_extract_numbers_reads_currency_and_suffixes():
    nums = {n.text: n.value for n in extract_numbers("R$6.11M, 498k, 12%, 1,328")}
    assert nums == {"R$6.11M": 6.11e6, "498k": 498e3, "12%": 12.0, "1,328": 1328.0}


def test_identifiers_are_not_numbers():
    # regression (M6 eval, trap_14): digits at the start of a hex seller id were flagged
    prose = "Seller 4869f7a5dfa277a7dca6462dcf3b52b2 leads; 53243585a1d6dc2643021fd1853d8905 is second."
    assert untraced(prose) == []
    assert untraced("Order e481f51cbdc54678b7cc49136f2d6af7 was delivered.") == []


def test_number_glued_to_letters_is_ignored_but_suffixes_work():
    assert [n.text for n in extract_numbers("12abc 498k 12%")] == ["498k", "12%"]


def test_methodological_because_is_not_causal():
    # regression (M6 eval, ambig_05)
    assert causal_findings("Months outside the window were excluded because data is sparse.") == []
    assert causal_findings("Scores fell because deliveries were late.") == ["because"]


def test_causal_lint():
    assert causal_findings(
        "Late deliveries drove low scores because carriers slowed, due to demand."
    ) == ["because", "drove", "due to"]
    assert causal_findings("Late orders are associated with lower scores.") == []
