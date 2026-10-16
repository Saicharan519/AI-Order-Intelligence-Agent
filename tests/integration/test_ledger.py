"""The spend ledger in trace.requests (oi_trace) records calls and feeds the budget guard."""

import datetime as dt

import psycopg
import pytest

from orderintel.llm.budget import LedgerEntry, PostgresLedger
from orderintel.llm.pricing import Usage

pytestmark = pytest.mark.integration

MODEL = "test-ledger-model"  # never a real model, so real quotas are unaffected


def test_record_and_read_back():
    try:
        ledger = PostgresLedger()
        before_total, _ = ledger.totals()
    except psycopg.Error:
        pytest.skip("database not reachable")
    since = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)
    n_before = ledger.count_requests(MODEL, since)
    ledger.record(LedgerEntry("test:ledger", MODEL, "ok", Usage(10, 4, 6, 3), 0.0, 12, "q?"))
    assert ledger.count_requests(MODEL, since) == n_before + 1
    total, today = ledger.totals()
    assert total == pytest.approx(before_total)  # a $0 entry leaves spend unchanged
    assert today <= total
