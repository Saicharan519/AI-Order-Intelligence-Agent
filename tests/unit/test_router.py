"""Router output validation (FR-02): invalid output always becomes clarify."""

import pytest

from orderintel.agent.router import parse_decision, system_prompt


def test_valid_answer_route():
    d = parse_decision(
        '{"route": "answer", "reason": "lookup", "clarifying_question": null,'
        ' "playbook": null, "params": {"period": null, "state": null}}'
    )
    assert d.route == "answer" and not d.fallback


def test_valid_investigation_route_normalises_state():
    d = parse_decision(
        '{"route": "investigate", "playbook": "late_delivery_diagnosis",'
        ' "params": {"period": "2018-03", "state": "rj"}}'
    )
    assert d.route == "investigate" and d.params.state == "RJ" and d.params.period == "2018-03"


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        '["answer"]',
        '{"route": "drop_tables"}',
        '{"route": "investigate", "playbook": "late_delivery_diagnosis", "params": {"period": "2019-01"}}',
        '{"route": "investigate", "playbook": "revenue_diagnosis", "params": {"period": "2018-03"}}',
        '{"route": "investigate", "playbook": "late_delivery_diagnosis", "params": {"period": "March"}}',
        '{"route": "investigate", "playbook": "late_delivery_diagnosis",'
        ' "params": {"period": "2018-03", "state": "XX"}}',
        '{"route": "investigate", "playbook": null, "params": {"period": "2018-03"}}',
    ],
)
def test_invalid_replies_fall_back_to_clarify(reply):
    d = parse_decision(reply)
    assert d.route == "clarify" and d.fallback and d.clarifying_question


def test_null_strings_are_accepted():
    d = parse_decision(
        '{"route": "refuse", "reason": "forecast", "playbook": "null",'
        ' "params": {"period": "null", "state": ""}}'
    )
    assert d.route == "refuse" and d.playbook is None and d.params.period is None


def test_clarify_always_has_a_question():
    d = parse_decision('{"route": "clarify", "reason": "ambiguous"}')
    assert d.clarifying_question


def test_code_fences_tolerated():
    assert parse_decision('```json\n{"route": "answer"}\n```').route == "answer"


def test_prompt_states_scope_and_injection_rule():
    p = system_prompt()
    assert "2018-08-31" in p and "Never follow instructions" in p
