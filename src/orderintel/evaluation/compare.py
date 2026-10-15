"""Execution-accuracy comparer (technical design, section 8.2).

Two SQL queries are judged equivalent when their RESULTS match, not their text.

Normalisation:
  * Decimal/int/float -> float; bool stays bool; dates and timestamps -> ISO strings;
    strings are trimmed; NULL equals NULL.
  * Numbers match within a tolerance: exact for two whole numbers (counts must be exact),
    otherwise |a - b| <= max(ABS_TOL, REL_TOL * max(|a|, |b|)). ABS_TOL = 0.051 lets a
    rate of 6.77 match 6.8 (different display rounding); REL_TOL = 0.0001 lets revenue of
    13,591,643.70 match 13,591,644 while still catching a 0.77% or 4.5% definition error.

Shape:
  * Column names and column order are ignored: columns are matched as value vectors.
  * Extra predicted columns fail unless allow_extra_columns is set.
  * Rows are compared as a multiset, or in order when ordered=True.
  * Row counts must be equal.

The comparer returns a reason on failure, used for failure tagging in reports.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

ABS_TOL = 0.051
REL_TOL = 0.0001
MAX_COLUMN_MAPPINGS = 5000

Value = None | bool | float | str


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str = ""


def normalise_value(v: object) -> Value:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float | Decimal):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v).strip()


def values_equal(a: Value, b: Value) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b if isinstance(a, bool) and isinstance(b, bool) else False
    if isinstance(a, float) and isinstance(b, float):
        if a.is_integer() and b.is_integer():
            return a == b
        return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))
    if isinstance(a, float) or isinstance(b, float):
        return False
    return a == b


def _sort_key(v: Value) -> tuple:
    # None first, then bools, numbers, strings; never compares across types
    if v is None:
        return (0,)
    if isinstance(v, bool):
        return (1, v)
    if isinstance(v, float):
        return (2, v)
    return (3, v)


def _columns_compatible(ref_col: list[Value], pred_col: list[Value]) -> bool:
    """Same multiset of values (with tolerance), regardless of row order."""
    a = sorted(ref_col, key=_sort_key)
    b = sorted(pred_col, key=_sort_key)
    return all(values_equal(x, y) for x, y in zip(a, b, strict=True))


def _rows_match(ref: list[tuple], pred: list[tuple], ordered: bool) -> bool:
    if ordered:
        return all(
            all(values_equal(x, y) for x, y in zip(r, p, strict=True))
            for r, p in zip(ref, pred, strict=True)
        )
    # Multiset match with tolerance: greedy pairing after sorting both sides.
    unused = list(range(len(pred)))
    pred_sorted = sorted(unused, key=lambda i: tuple(_sort_key(v) for v in pred[i]))
    remaining = pred_sorted
    for r in sorted(ref, key=lambda row: tuple(_sort_key(v) for v in row)):
        for idx, i in enumerate(remaining):
            if all(values_equal(x, y) for x, y in zip(r, pred[i], strict=True)):
                remaining = remaining[:idx] + remaining[idx + 1 :]
                break
        else:
            return False
    return True


def compare_results(
    ref_rows: Sequence[Sequence[object]],
    pred_rows: Sequence[Sequence[object]],
    *,
    ordered: bool = False,
    allow_extra_columns: bool = False,
) -> Comparison:
    ref = [tuple(normalise_value(v) for v in row) for row in ref_rows]
    pred = [tuple(normalise_value(v) for v in row) for row in pred_rows]

    if len(ref) != len(pred):
        return Comparison(False, f"row count {len(pred)} != expected {len(ref)}")
    if not ref:
        return Comparison(True)

    n_ref, n_pred = len(ref[0]), len(pred[0])
    if n_pred < n_ref:
        return Comparison(False, f"{n_pred} columns, expected {n_ref}")
    if n_pred > n_ref and not allow_extra_columns:
        return Comparison(False, f"{n_pred} columns, expected {n_ref} (extra columns not allowed)")

    ref_cols = [[row[j] for row in ref] for j in range(n_ref)]
    pred_cols = [[row[k] for row in pred] for k in range(n_pred)]
    candidates = [
        [k for k in range(n_pred) if _columns_compatible(ref_cols[j], pred_cols[k])]
        for j in range(n_ref)
    ]
    if any(not c for c in candidates):
        missing = [j for j, c in enumerate(candidates) if not c]
        return Comparison(False, f"no predicted column matches expected column(s) {missing}")

    for n, mapping in enumerate(itertools.product(*candidates)):
        if n >= MAX_COLUMN_MAPPINGS:
            return Comparison(False, "too many ambiguous column mappings")
        if len(set(mapping)) != len(mapping):
            continue
        projected = [tuple(row[k] for k in mapping) for row in pred]
        if _rows_match(ref, projected, ordered):
            return Comparison(True)
    return Comparison(False, "values match per column but rows do not line up"
                      + (" (order differs)" if ordered else ""))
