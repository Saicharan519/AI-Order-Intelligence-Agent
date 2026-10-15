import pytest
from pydantic import ValidationError

from orderintel.evaluation.golden import GoldenItem, load_golden, split_fingerprint


def test_any_edit_to_a_test_item_changes_the_fingerprint():
    items = load_golden()
    original = split_fingerprint(items)
    test_item = next(i for i in items if i.split == "test")
    edited = [
        i.model_copy(update={"question": i.question + " "}) if i is test_item else i for i in items
    ]
    assert split_fingerprint(edited) != original


def test_editing_a_dev_item_does_not_change_the_fingerprint():
    items = load_golden()
    dev_item = next(i for i in items if i.split == "dev")
    edited = [i.model_copy(update={"notes": "x"}) if i is dev_item else i for i in items]
    assert split_fingerprint(edited) == split_fingerprint(items)


def test_answerable_item_requires_sql():
    with pytest.raises(ValidationError):
        GoldenItem(id="x", split="dev", category="aggregate", question="q", expected_route="answer")


def test_out_of_scope_item_must_refuse_without_sql():
    with pytest.raises(ValidationError):
        GoldenItem(id="x", split="dev", category="out_of_scope", question="q",
                   reference_sql="SELECT 1", expected_route="refuse")
    with pytest.raises(ValidationError):
        GoldenItem(id="x", split="dev", category="out_of_scope", question="q",
                   expected_route="answer")


def test_route_string_becomes_list():
    item = GoldenItem(id="x", split="dev", category="lookup", question="q",
                      reference_sql="SELECT 1", expected_route="answer")
    assert item.expected_route == ["answer"]
