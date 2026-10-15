"""Deterministic safety suite (no LLM): every SQL attack in eval/golden/attacks.yaml goes
through the validator and, if it passes, the executor. An attack SUCCEEDS (test failure)
if it executes with a write, reads outside the views, exceeds the row cap, or runs past
the timeout. Each case must also be stopped by the layer named in expected_block."""

from pathlib import Path

import psycopg
import pytest
import yaml

from orderintel.db.connect import connect_agent
from orderintel.db.executor import DEFAULT_TIMEOUT_S, ExecutionError, execute
from orderintel.guard.validator import ROW_CAP, validate

ATTACKS = yaml.safe_load(
    (Path(__file__).parents[2] / "eval" / "golden" / "attacks.yaml").read_text(encoding="utf-8")
)
SQL_ATTACKS = [a for a in ATTACKS if a["kind"] == "sql"]


def _db_available() -> bool:
    try:
        with connect_agent() as c:
            c.execute("SELECT 1 FROM analytics.sellers LIMIT 1")
        return True
    except psycopg.Error:
        return False


def outcome(sql: str) -> tuple[str, str]:
    """Return (layer that stopped it, detail). 'none' means it ran to completion."""
    r = validate(sql)
    if not r.ok:
        return "validator", r.feedback()
    if not _db_available():
        pytest.skip("database not reachable")
    try:
        res = execute(r.validated)
    except ExecutionError as e:
        return "executor", e.code
    assert res.row_count <= ROW_CAP
    assert res.ms < (DEFAULT_TIMEOUT_S + 3) * 1000
    return ("executor", "row cap") if res.truncated else ("none", f"{res.row_count} rows")


@pytest.mark.parametrize("attack", SQL_ATTACKS, ids=lambda a: a["id"])
def test_sql_attack_is_stopped_by_expected_layer(attack):
    layer, detail = outcome(attack["input"])
    assert layer != "none", f"{attack['id']} ran unrestricted: {detail}"
    assert layer == attack["expected_block"], f"{attack['id']}: stopped by {layer} ({detail})"


def test_suite_size():
    assert len(SQL_ATTACKS) >= 28
    assert len(ATTACKS) >= 40
