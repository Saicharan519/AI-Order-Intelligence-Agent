"""SQL-generation prompts: what each ablation configuration may and may not see."""

import pytest

from orderintel.agent.sqlgen import build_messages, parse_reply, repair_messages, system_prompt
from orderintel.evaluation.golden import load_golden


def test_config_a_sees_raw_ddl_only_without_trap_hints():
    s = system_prompt("A")
    assert "CREATE TABLE raw.orders" in s
    assert "analytics" not in s and "glossary" not in s.lower()
    assert "NOT unique" not in s and "midnight" not in s  # DDL comments stripped


def test_config_b_adds_definitions_without_view_references():
    s = system_prompt("B")
    assert "CREATE TABLE raw.orders" in s and "Late" in s
    assert "analytics" not in s and "Where implemented" not in s


def test_config_c_sees_views_and_full_glossary_not_raw():
    s = system_prompt("C")
    assert "analytics.orders" in s and "Where implemented" in s
    assert "CREATE TABLE raw" not in s


def test_d_uses_the_same_prompt_as_c():
    assert system_prompt("D") == system_prompt("C")


@pytest.mark.parametrize("config", ["A", "B", "C", "D"])
def test_shared_rules_and_anchor_date(config):
    s = system_prompt(config)
    assert "2018-08-31" in s and '"sql"' in s


def test_static_prefix_is_identical_across_questions():
    a = build_messages("C", "How many orders?")
    b = build_messages("C", "Revenue in 2017?")
    assert a[0] == b[0] and a[1] != b[1]


def test_no_test_split_question_appears_in_any_prompt():
    tests = [i.question for i in load_golden() if i.split == "test"]
    for config in "ABCD":
        s = system_prompt(config)
        assert not [q for q in tests if q in s]


@pytest.mark.parametrize(
    ("reply", "sql", "error"),
    [
        ('{"sql": "SELECT 1", "assumptions": ["a"]}', "SELECT 1", None),
        ('```json\n{"sql": "SELECT 2"}\n```', "SELECT 2", None),
        ('{"sql": null, "assumptions": ["cannot forecast"]}', None, None),
        ("not json", None, "reply is not valid JSON"),
        ('["SELECT 1"]', None, "reply is not a JSON object"),
        ('{"sql": 5}', None, "'sql' must be a string or null"),
    ],
)
def test_parse_reply(reply, sql, error):
    got_sql, _, got_error = parse_reply(reply)
    assert got_sql == sql
    assert (got_error or "").startswith(error or "")


def test_repair_messages_append_reply_and_feedback():
    msgs = build_messages("D", "q")
    out = repair_messages(msgs, '{"sql": "SELECT * FROM raw.orders"}', "VR-04: relation raw.orders")
    assert out[:2] == msgs
    assert out[2]["role"] == "assistant" and "VR-04" in out[3]["content"]
