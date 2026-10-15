"""T-4.6 scaffold: every playbook SQL step must pass the same validator as model output.
Playbooks arrive in M7; until then this test is skipped."""

import importlib

import pytest

from orderintel.guard.validator import validate


def playbook_steps():
    try:
        playbooks = importlib.import_module("orderintel.playbooks")
    except ModuleNotFoundError:
        return []
    return list(playbooks.iter_steps())  # [(playbook, step_name, sql_with_sample_params)]


STEPS = playbook_steps()


@pytest.mark.skipif(not STEPS, reason="no playbooks yet (M7)")
@pytest.mark.parametrize("step", STEPS, ids=lambda s: f"{s[0]}.{s[1]}")
def test_playbook_step_passes_validator(step):
    _, _, sql = step
    r = validate(sql)
    assert r.ok, r.feedback()
