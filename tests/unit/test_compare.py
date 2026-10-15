import datetime as dt
from decimal import Decimal

from orderintel.evaluation.compare import compare_results, normalise_value, values_equal


def ok(ref, pred, **kw):
    return compare_results(ref, pred, **kw).match


# --- normalisation ---
def test_normalise_types():
    assert normalise_value(Decimal("6.77")) == 6.77
    assert normalise_value(7) == 7.0
    assert normalise_value(dt.date(2018, 3, 1)) == "2018-03-01"
    assert normalise_value(dt.datetime(2017, 10, 10, 21, 25, 13)) == "2017-10-10 21:25:13"
    assert normalise_value("  SP ") == "SP"
    assert normalise_value(None) is None
    assert normalise_value(True) is True


# --- numeric tolerance ---
def test_counts_must_be_exact():
    assert not values_equal(4496.0, 4495.0)
    assert values_equal(4496.0, 4496.0)


def test_display_rounding_of_rates_is_accepted():
    assert values_equal(6.77, 6.8)
    assert values_equal(4.09, 4.0865)


def test_definition_errors_are_caught():
    assert not values_equal(6.77, 8.11)  # date vs timestamp definition of late
    assert not values_equal(14.13, 13.76)  # late over delivered vs over all orders


def test_large_values_use_relative_tolerance():
    assert values_equal(13591643.70, 13591644.0)
    assert not values_equal(13591643.70, 14209115.34)  # 4.5% payment fan-out
    assert not values_equal(6108492.27, 6155654.0)  # 0.77% canceled inclusion


def test_bool_never_equals_number():
    assert not values_equal(True, 1.0)


def test_null_equals_null_only():
    assert values_equal(None, None)
    assert not values_equal(None, 0.0)


# --- shape ---
def test_column_names_and_order_ignored():
    ref = [("SP", Decimal("10.5"))]
    assert ok(ref, [(10.5, "SP")])


def test_extra_columns_fail_unless_allowed():
    ref = [("SP", 10)]
    pred = [("SP", 10, 99)]
    assert not ok(ref, pred)
    assert ok(ref, pred, allow_extra_columns=True)


def test_missing_column_fails():
    assert not ok([("SP", 10)], [("SP",)])


def test_row_count_must_match():
    r = compare_results([(1,), (2,)], [(1,)])
    assert not r.match and "row count" in r.reason


def test_unordered_is_multiset():
    ref = [("a", 1), ("b", 2), ("b", 2)]
    assert ok(ref, [("b", 2), ("a", 1), ("b", 2)])
    assert not ok(ref, [("a", 1), ("a", 1), ("b", 2)])


def test_ordered_requires_order():
    ref = [("bed_bath_table", 497971), ("watches_gifts", 486519)]
    swapped = list(reversed(ref))
    assert ok(ref, swapped)  # unordered
    assert not ok(ref, swapped, ordered=True)


def test_columns_must_line_up_row_by_row():
    # each column has the same values, but pairing differs: SP->2, RJ->1
    ref = [("SP", 1), ("RJ", 2)]
    pred = [("SP", 2), ("RJ", 1)]
    r = compare_results(ref, pred)
    assert not r.match and "line up" in r.reason


def test_ambiguous_equal_columns_resolved():
    # two numeric columns with the same values in different positions
    ref = [(1, 1, "x"), (2, 2, "y")]
    assert ok(ref, [("x", 1, 1), ("y", 2, 2)])


def test_empty_results_match():
    assert ok([], [])


def test_dates_vs_strings():
    assert ok([(dt.date(2018, 3, 1), 7003)], [("2018-03-01", 7003)])
