from decimal import Decimal

from scripts.check_counts import Check, matches, normalise


def test_normalise_decimal_and_float():
    # regression: PostgreSQL returns numeric as Decimal, which was compared exactly
    assert normalise(Decimal("6.77")) == 6.77
    assert normalise(Decimal("13591644")) == 13591644
    assert isinstance(normalise(Decimal("6")), int)
    assert normalise("2016-09-04") == "2016-09-04"


def test_tolerance_applies_to_rounded_figures():
    c = Check("x", "", 13_591_644, tolerance=0.0001)
    assert matches(normalise(Decimal("13591643.70")), c)
    assert not matches(normalise(Decimal("14209115.34")), c)


def test_exact_and_informational():
    assert matches(51, Check("x", "", 51)) is True
    assert matches(57, Check("x", "", 51)) is False
    assert matches(775, Check("x", "", None)) is None
