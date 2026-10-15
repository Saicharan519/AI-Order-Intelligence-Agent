"""T-4.1: the committed allow-list matches what oi_agent can actually read."""

import json

import psycopg
import pytest

from orderintel.guard.allowlists import ALLOWLIST_FILE
from scripts.gen_allowlists import introspect

pytestmark = pytest.mark.integration


def test_allowlist_matches_database():
    try:
        live = introspect()
    except psycopg.Error:
        pytest.skip("database not reachable")
    committed = json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))
    assert committed == live, "run scripts/gen_allowlists.py after changing the views"
