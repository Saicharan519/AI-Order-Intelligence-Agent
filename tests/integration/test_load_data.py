"""Integration tests for the loader and data profile (M1). Need the database and the real CSVs."""

import shutil
from decimal import Decimal

import psycopg
import pytest

from orderintel.config import get_settings
from orderintel.db.connect import connect_owner
from scripts import check_counts
from scripts.load_data import EXPECTED_ROWS, SOURCES, LoadError, load_all

pytestmark = pytest.mark.integration

DATA_DIR = get_settings().data_dir


def _db_available() -> bool:
    try:
        with connect_owner() as conn:
            conn.execute("SELECT 1 FROM raw.orders LIMIT 1")
        return True
    except psycopg.Error:
        return False


if not all((DATA_DIR / f).is_file() for f in SOURCES.values()):
    pytest.skip("Olist CSVs not present in data/raw", allow_module_level=True)
if not _db_available():
    pytest.skip("database not reachable or not migrated", allow_module_level=True)


def snapshot() -> dict:
    """Counts plus a few content fingerprints, to detect any change to the loaded data."""
    with connect_owner() as conn:
        snap = {t: conn.execute(f"SELECT count(*) FROM raw.{t}").fetchone()[0] for t in SOURCES}  # noqa: S608
        snap["sum_price"] = conn.execute("SELECT sum(price) FROM raw.order_items").fetchone()[0]
        snap["max_review_row_id"] = conn.execute(
            "SELECT max(review_row_id) FROM raw.order_reviews"
        ).fetchone()[0]
    return snap


@pytest.fixture
def data_copy(tmp_path):
    """A private copy of the CSVs that a test may corrupt."""
    for f in SOURCES.values():
        shutil.copy(DATA_DIR / f, tmp_path / f)
    return tmp_path


def test_load_gives_expected_counts():
    counts = load_all(DATA_DIR)
    assert counts == EXPECTED_ROWS


def test_load_is_idempotent():
    load_all(DATA_DIR)
    first = snapshot()
    load_all(DATA_DIR)
    second = snapshot()
    assert first == second
    # identity restarts on reload, so surrogate keys are stable across runs
    assert second["max_review_row_id"] == EXPECTED_ROWS["order_reviews"]
    assert second["sum_price"] == Decimal("13591643.70")


def test_bad_value_rolls_back_everything(data_copy):
    load_all(DATA_DIR)
    before = snapshot()

    path = data_copy / SOURCES["order_items"]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(",58.90,", ",not-a-number,", 1), encoding="utf-8")

    with pytest.raises(LoadError, match=r"raw\.order_items: invalid input syntax for type numeric"):
        load_all(data_copy)
    # orders etc. were truncated and reloaded inside the failed transaction; none of it stuck
    assert snapshot() == before


def test_wrong_header_is_rejected(data_copy):
    path = data_copy / SOURCES["sellers"]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"seller_city"', '"city"', 1), encoding="utf-8")
    with pytest.raises(LoadError, match="header"):
        load_all(data_copy)


def test_missing_file_is_rejected(data_copy):
    (data_copy / SOURCES["products"]).unlink()
    with pytest.raises(LoadError, match="missing files"):
        load_all(data_copy)


def test_profile_reproduces_all_prd_figures():
    load_all(DATA_DIR)
    results = check_counts.run()
    failures = [(c.name, c.expected, actual) for c, actual, ok in results if ok is False]
    assert failures == []
