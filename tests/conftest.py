"""Test-session setup.

Tests marked `realdata` check figures of the real Olist dataset (PRD examples, golden
references, "625 canceled orders"). The dataset is not redistributed, so CI runs against
the synthetic fixture (scripts/build_mini_db.py --db orderintel_ci): there, these tests are
skipped with a stated reason, and every other test still runs.
"""

import psycopg
import pytest

REAL_ORDERS = 99_441  # rows in olist_orders_dataset.csv


def _real_data_loaded() -> bool | None:
    """True or False, or None when the database is not reachable (tests skip themselves)."""
    from orderintel.db.connect import connect_eval

    try:
        with connect_eval() as conn:
            return conn.execute("SELECT count(*) FROM raw.orders").fetchone()[0] == REAL_ORDERS
    except psycopg.Error:
        return None


def pytest_collection_modifyitems(config, items):
    marked = [i for i in items if "realdata" in i.keywords]
    if not marked or _real_data_loaded() is not False:
        return
    skip = pytest.mark.skip(
        reason="needs the real Olist data (not redistributed; CI uses the synthetic fixture)"
    )
    for item in marked:
        item.add_marker(skip)
