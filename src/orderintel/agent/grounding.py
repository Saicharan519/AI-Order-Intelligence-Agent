"""Number grounding (FR-07, SC-06; technical design 8.5) and causal-language lint.

Grounding: every number in the model's prose must be traceable to the evidence:
  * a numeric cell, at its own or any coarser precision (497971.04 -> 497,971 -> R$498k);
  * a whitelisted derivation between cells: share of a column total, difference, ratio,
    percentage change (pairs within a column or within a row, bounded in size);
  * a fraction expressed as a percentage, or a percentage as a fraction;
  * a number in the question or the scope (years, sample size, period bounds);
  * a small integer (0-12), which is mostly ordinal or count wording ("top 5").
A prose number "x" displayed with d decimals and multiplier m (k, M) matches a value v
when |v - x*m| <= half a unit of the displayed precision. Unmatched numbers are reported
as untraced. Known limit: other derived statistics produce false positives.

Lint: Ask answers describe associations; causal wording is flagged.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from dataclasses import dataclass, field

from orderintel.evaluation.compare import normalise_value

MAX_DERIVATION_VALUES = 40
SMALL_INTEGERS = set(range(13))

DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b"),
    re.compile(r"\b\d{4}-\d{2}\b"),
]
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<cur>R\$\s?)?(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"\s?(?P<suf>%|k\b|K\b|M\b|mn\b|million\b|thousand\b|bn\b)?",
)
MULTIPLIERS = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9}

CAUSAL_PATTERNS = [
    r"\bbecause\b",
    r"\bcaused?\b",
    r"\bcausing\b",
    r"\bdue to\b",
    r"\bled to\b",
    r"\bleads? to\b",
    r"\bresult(?:ed|s)? in\b",
    r"\bdrove\b",
    r"\bdriven by\b",
    r"\bdrives?\b",
    r"\bas a result\b",
    r"\bowing to\b",
    r"\bthanks to\b",
]
CAUSAL_RE = re.compile("|".join(CAUSAL_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class ProseNumber:
    text: str
    value: float  # value with multiplier applied, in the prose's own unit
    half_unit: float  # half of the displayed precision, multiplier applied
    percent: bool


@dataclass
class GroundingResult:
    numbers_checked: int = 0
    untraced: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.untraced


def extract_numbers(text: str) -> list[ProseNumber]:
    for p in DATE_PATTERNS:
        text = p.sub(" ", text)
    found = []
    for m in NUMBER_RE.finditer(text):
        raw = m.group("num")
        digits = raw.replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        suffix = m.group("suf") or ""
        mult = MULTIPLIERS.get(suffix, 1.0)
        value = float(digits) * mult
        precision = 10 ** (-decimals)
        integer = digits.lstrip("-").split(".")[0]
        if decimals == 0 and mult == 1.0 and integer.strip("0"):
            # "4,500" is a rounding of 4,496 to the hundreds: trailing zeros set the precision
            precision = 10 ** (len(integer) - len(integer.rstrip("0")))
        found.append(ProseNumber(m.group(0).strip(), value, 0.5 * precision * mult, suffix == "%"))
    return found


def _numbers_from(values) -> list[float]:
    out = []
    for v in values:
        n = normalise_value(v)
        if isinstance(n, float):
            out.append(n)
        elif isinstance(n, str) and re.fullmatch(r"-?\d+(\.\d+)?", n):
            out.append(float(n))
    return out


def allowed_values(rows: list[tuple], context_texts: list[str]) -> set[float]:
    allowed: set[float] = set()
    columns = list(zip(*rows, strict=True)) if rows else []
    cells = _numbers_from(v for r in rows for v in r)
    allowed.update(cells)
    allowed.update(c * 100 for c in cells)  # fraction shown as a percentage
    allowed.update(c / 100 for c in cells)
    allowed.add(float(len(rows)))
    for col in columns:
        nums = _numbers_from(col)[:MAX_DERIVATION_VALUES]
        total = sum(nums)
        if nums:
            allowed.add(total)
            if total:
                allowed.update(100 * x / total for x in nums)  # share of total
        for a, b in itertools.permutations(nums, 2):
            allowed.add(a - b)
            if b:
                allowed.add(a / b)
                allowed.add(100 * (a / b - 1))  # percentage change
    for row in rows:
        nums = _numbers_from(row)
        for a, b in itertools.permutations(nums, 2):
            allowed.add(a - b)
            if b:
                allowed.add(a / b)
                allowed.add(100 * a / b)
    for text in context_texts:
        for n in extract_numbers(text):
            allowed.add(n.value)
        for y in re.findall(r"\b(20\d{2})\b", text):
            allowed.add(float(y))
    return allowed


def is_traced(n: ProseNumber, allowed: set[float]) -> bool:
    v = abs(n.value)
    if n.half_unit >= 0.5 and v in SMALL_INTEGERS:
        return True
    if 2016 <= v <= 2018 and n.half_unit == 0.5:
        return True  # years of the data window
    return any(abs(abs(a) - v) <= n.half_unit * (1 + 1e-9) + 1e-9 for a in allowed)


def check_grounding(prose: str, rows: list[tuple], context_texts: list[str]) -> GroundingResult:
    numbers = extract_numbers(prose)
    allowed = allowed_values(rows, context_texts)
    untraced = list(dict.fromkeys(n.text for n in numbers if not is_traced(n, allowed)))
    return GroundingResult(len(numbers), untraced)


def causal_findings(prose: str) -> list[str]:
    return sorted({m.group(0).lower() for m in CAUSAL_RE.finditer(prose)})


def scope_texts(question: str, scope) -> list[str]:
    parts = [
        question,
        scope.period_start,
        scope.period_end,
        str(scope.n),
        *scope.partial_period_warnings,
        *scope.assumptions,
    ]
    return [p for p in parts if p]


def today() -> dt.date:
    return dt.date(2018, 8, 31)  # the data's "today" (glossary)
