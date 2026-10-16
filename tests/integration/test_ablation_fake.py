"""End-to-end ablation pipeline with a FAKE model and the real database (no spend):
generation -> (validator) -> execution -> scoring, including config D's repair loop."""

import psycopg
import pytest

from orderintel.agent.pipeline import MAX_REPAIRS, run_question
from orderintel.db.connect import connect_eval
from orderintel.evaluation.ablation import reference_rows, run_config, score
from orderintel.evaluation.golden import load_golden
from tests.fixtures.fake_llm import fake_client

pytestmark = pytest.mark.integration

try:
    with connect_eval() as _c:
        _c.execute("SELECT 1 FROM analytics.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

ITEMS = {i.id: i for i in load_golden()}
CANCELED = ITEMS["agg_10"]  # How many orders were canceled? -> 625

GOOD_VIEW_SQL = "SELECT count(*) FROM analytics.orders WHERE order_status = 'canceled'"
GOOD_RAW_SQL = "SELECT count(*) FROM raw.orders WHERE order_status = 'canceled'"


def reply(sql):
    return {"sql": sql, "assumptions": []}


@pytest.mark.realdata
def test_config_a_correct_raw_sql_scores_correct():
    client, _ = fake_client(lambda q, n: reply(GOOD_RAW_SQL))
    run = run_question(client, "A", CANCELED.question)
    assert run.status == "ok" and run.rows == [(625,)]
    assert score(CANCELED, run, reference_rows(CANCELED)) == (True, "")


def test_config_a_wrong_answer_scores_wrong():
    client, _ = fake_client(lambda q, n: reply("SELECT count(*) FROM raw.orders"))
    run = run_question(client, "A", CANCELED.question)
    correct, reason = score(CANCELED, run, reference_rows(CANCELED))
    assert not correct and "no predicted column matches" in reason


def test_config_a_sql_error_is_recorded_not_raised():
    client, _ = fake_client(lambda q, n: reply("SELECT nope FROM raw.orders"))
    run = run_question(client, "A", CANCELED.question)
    assert run.status == "exec_error" and "nope" in run.error


def test_config_a_cannot_write_even_without_validator():
    def sellers():
        with connect_eval() as conn:
            return conn.execute("SELECT count(*) FROM raw.sellers").fetchone()[0]

    before = sellers()  # compared before/after, so the test holds on any dataset (CI)
    client, _ = fake_client(lambda q, n: reply("DELETE FROM raw.sellers"))
    run = run_question(client, "A", CANCELED.question)
    assert run.status == "exec_error"
    assert before > 0 and sellers() == before


@pytest.mark.realdata
def test_config_d_repairs_after_validator_rejection():
    # first answer uses a raw table (VR-04), the repair uses the view
    client, transport = fake_client(lambda q, n: reply(GOOD_RAW_SQL if n == 1 else GOOD_VIEW_SQL))
    run = run_question(client, "D", CANCELED.question)
    assert run.status == "ok" and run.repairs == 1 and run.rows == [(625,)]
    assert run.attempts[0].stage == "rejected" and "VR-04" in run.attempts[0].feedback
    repair_prompt = transport.calls[1]["messages"][-1]["content"]
    assert "VR-04" in repair_prompt  # the model is told why


def test_config_d_repairs_are_capped():
    client, transport = fake_client(lambda q, n: reply(GOOD_RAW_SQL))
    run = run_question(client, "D", CANCELED.question)
    assert run.status == "rejected"
    assert len(transport.calls) == 1 + MAX_REPAIRS and run.repairs == MAX_REPAIRS


def test_config_d_repairs_after_bad_json():
    client, _ = fake_client(lambda q, n: "not json" if n == 1 else reply(GOOD_VIEW_SQL))
    run = run_question(client, "D", CANCELED.question)
    assert run.status == "ok" and run.attempts[0].stage == "parse_error"


@pytest.mark.realdata
def test_config_d_repairs_after_cost_ceiling():
    expensive = "SELECT count(*) FROM orders a JOIN orders b ON a.purchase_month = b.purchase_month"
    client, _ = fake_client(lambda q, n: reply(expensive if n == 1 else GOOD_VIEW_SQL))
    run = run_question(client, "D", CANCELED.question)
    assert run.status == "ok" and "cost_ceiling" in run.attempts[0].feedback


def test_declined_question_is_not_repaired():
    client, transport = fake_client(lambda q, n: {"sql": None, "assumptions": ["cannot"]})
    run = run_question(client, "D", CANCELED.question)
    assert run.status == "declined" and len(transport.calls) == 1


def test_run_config_with_reference_answers_scores_100_percent():
    # A fake model that answers with the reference SQL must score 100%: checks the
    # runner and scorer end to end on real data (config A runs references unvalidated).
    refs = {i.question: i.reference_sql for i in ITEMS.values()}
    client, _ = fake_client(lambda q, n: reply(refs[q]))
    ids = ["lookup_01", "agg_04", "trend_01", "trap_06", "ambig_01"]
    summary = run_config(client, "A", "dev", ids, progress=lambda *_: None)
    assert summary.n == 5 and summary.correct == 5 and summary.ran == 5
    assert summary.cost_usd > 0 and summary.ci95[1] == 1.0
