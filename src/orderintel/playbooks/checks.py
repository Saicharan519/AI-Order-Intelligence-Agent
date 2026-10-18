"""Consistency checks on playbook findings.

The grounding check proves that every number in a narration comes from the findings; it
cannot tell when two findings contradict each other. These checks can. They found nothing
new on the real data after the window fix, and they exist because a September 2016
investigation once reported "0 delivered orders" next to "1 seller with late orders" (two
steps ignored the analysis window). A failed check is shown to the user as a warning and the
verdict is not trusted.
"""

from __future__ import annotations

PERCENT_SUFFIXES = ("_rate", "_share", "share_late", "share_on_time")


def _percent_fields(f: dict) -> list[tuple[str, float]]:
    out = []
    for key, value in f.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            if key.endswith(PERCENT_SUFFIXES) or key.startswith("one_star_share"):
                out.append((key, value))
    return out


def inconsistencies(f: dict) -> list[str]:
    """Contradictions inside one playbook's findings, in words (empty when consistent)."""
    problems = []
    for key, value in _percent_fields(f):
        if not 0 <= value <= 100:
            problems.append(f"{key} is {value}, outside 0 to 100")
    for name, share in (f.get("one_star_from") or {}).items():
        if not 0 <= share <= 100:
            problems.append(f"one_star_from[{name}] is {share}, outside 0 to 100")

    if "delivered_orders" in f:  # late-delivery playbook
        delivered, late = f["delivered_orders"] or 0, f.get("late_orders") or 0
        if late > delivered:
            problems.append(f"late orders ({late}) exceed delivered orders ({delivered})")
        sellers = f.get("sellers_with_late_orders")
        if sellers is not None and late == 0 and sellers > 0:
            problems.append(f"{sellers} seller(s) with late orders, but 0 late orders")
        if sellers is not None and sellers > late:
            problems.append(f"more sellers with late orders ({sellers}) than late orders ({late})")
        for group in ("top_states", "top_sellers", "top_categories"):
            for g in f.get(group) or []:
                if g.get("n") is not None and g["n"] > delivered:
                    problems.append(
                        f"{group} {g['name']} has {g['n']} orders, more than the period"
                    )
        reviewed = (f.get("review_n_late") or 0) + (f.get("review_n_on_time") or 0)
        if reviewed > delivered:
            problems.append(f"{reviewed} reviewed orders, more than {delivered} delivered")
        if f.get("verdict") != "insufficient_data" and delivered == 0:
            problems.append("a verdict was given for a period with no delivered orders")

    if "reviews" in f:  # low-review playbook
        n = f["reviews"] or 0
        for group in ("worst_categories", "worst_sellers"):
            for g in f.get(group) or []:
                if g.get("n") is not None and g["n"] > n:
                    problems.append(f"{group} {g['name']} has {g['n']} reviews, more than {n}")
        if f.get("verdict") != "insufficient_data" and n == 0:
            problems.append("a verdict was given for a period with no reviews")
    return problems
