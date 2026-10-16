"""Investigation playbooks (M7). Registry used by the Ask graph and by the test that every
playbook SQL step passes the validator (tests/unit/test_playbook_sql.py)."""

from __future__ import annotations

from orderintel.playbooks import late_delivery, low_reviews
from orderintel.playbooks.base import PlaybookParams, render

PLAYBOOKS = {
    late_delivery.NAME: late_delivery,
    low_reviews.NAME: low_reviews,
}


def iter_steps():
    """(playbook, step name, SQL rendered with sample parameters) for every step, with and
    without a state filter."""
    for name, module in PLAYBOOKS.items():
        for params in (
            PlaybookParams(period="2018-03"),
            PlaybookParams(period="2018-03", state="RJ"),
        ):
            for step in module.STEPS:
                if step.only_without_state and params.state:
                    continue
                label = f"{step.name}[{params.state or 'all'}]"
                yield name, label, render(step.sql, params.sql_values())
