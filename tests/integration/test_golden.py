"""M3: the golden set is well-formed, every reference runs, the pandas cross-check agrees,
the comparer rejects known-wrong answers, and the frozen test split is unchanged."""

import sys

import psycopg
import pytest

from orderintel.config import PROJECT_ROOT
from orderintel.db.connect import connect_eval
from orderintel.evaluation.compare import compare_results
from orderintel.evaluation.golden import TEST_HASH_FILE, load_golden, split_fingerprint

sys.path.insert(0, str(PROJECT_ROOT / "eval"))
import crosscheck  # noqa: E402
import run_eval  # noqa: E402

pytestmark = pytest.mark.integration

try:
    with connect_eval() as _c:
        _c.execute("SELECT 1 FROM raw.orders LIMIT 1")
except psycopg.Error:
    pytest.skip("database not reachable", allow_module_level=True)

ITEMS = load_golden()
BY_ID = {i.id: i for i in ITEMS}


def test_structure_matches_prd_section_11():
    assert run_eval.check_structure(ITEMS) == []


def test_test_split_is_frozen_and_unchanged():
    if not TEST_HASH_FILE.exists():
        pytest.skip("test split not frozen yet (awaiting owner review)")
    assert TEST_HASH_FILE.read_text(encoding="utf-8").split()[0] == split_fingerprint(ITEMS)


def test_attack_and_investigation_drafts_meet_minimum_sizes():
    import yaml

    golden = PROJECT_ROOT / "eval" / "golden"
    attacks = yaml.safe_load((golden / "attacks.yaml").read_text(encoding="utf-8"))
    cases = yaml.safe_load((golden / "investigation.yaml").read_text(encoding="utf-8"))
    assert len(attacks) >= 40
    assert len({a["id"] for a in attacks}) == len(attacks)
    assert len([c for c in cases if "fixture" not in c]) == 15
    assert len([c for c in cases if "fixture" in c]) == 2


@pytest.mark.realdata
@pytest.mark.parametrize("item", [i for i in ITEMS if i.answerable], ids=lambda i: i.id)
def test_every_reference_runs_and_is_non_trivial(item):
    with connect_eval(autocommit=True) as conn:
        for sql in item.references:
            _, rows, secs = run_eval.run_sql(conn, sql)
            assert rows and not run_eval.is_trivial(rows)
            assert secs < run_eval.MAX_REF_SECONDS


@pytest.fixture(scope="module")
def frames():
    return crosscheck.load_frames()


@pytest.mark.realdata
def test_pandas_crosscheck_agrees(frames):
    results = crosscheck.run(frames)
    assert len(results) >= 20
    assert [(i, r) for i, ok, r in results if not ok] == []


def _wrong_payments_instead_of_price(f):
    s = crosscheck.sales(f)
    s = s[
        (s.order_purchase_timestamp >= "2017-11-01") & (s.order_purchase_timestamp < "2017-12-01")
    ]
    p = f["order_payments"]
    return [(p[p.order_id.isin(s.order_id)].payment_value.sum(),)]


def _wrong_naive_card_join(f):
    p = f["order_payments"]
    s = crosscheck.in_year(crosscheck.sale_items(f), 2017)
    return [(s.merge(p[p.payment_type == "credit_card"][["order_id"]], on="order_id").price.sum(),)]


def _wrong_timestamp_late(f):
    d = crosscheck.delivered(f)
    return [(int((d.order_delivered_customer_date > d.order_estimated_delivery_date).sum()),)]


def _wrong_partial_months(f):
    o = crosscheck.in_year(f["orders"], 2018)
    return [(round(o.groupby(crosscheck.months(o)).size().mean(), 2),)]


@pytest.mark.realdata
@pytest.mark.parametrize(
    ("item_id", "wrong"),
    [
        ("trap_10", _wrong_payments_instead_of_price),
        ("trap_01", _wrong_naive_card_join),
        ("trap_03", _wrong_timestamp_late),
        ("trap_07", _wrong_partial_months),
    ],
)
def test_comparer_rejects_trap_mistakes(frames, item_id, wrong):
    with connect_eval() as conn:
        ref = conn.execute(BY_ID[item_id].reference_sql).fetchall()
    assert not compare_results(ref, wrong(frames)).match
