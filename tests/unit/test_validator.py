"""Validator rules VR-01 to VR-09 (SC-03): positive and negative cases for every rule.
No database needed: the allow-list comes from the committed allowlist.json."""

import pytest
import sqlglot

from orderintel.guard.allowlists import ALLOWED_FUNCTIONS
from orderintel.guard.validator import (
    MAX_SQL_LENGTH,
    ROW_CAP,
    ValidatedSQL,
    _postgres_second_opinion,
    validate,
)
from tests.fixtures.view_queries import VIEW_QUERIES


def rules(sql: str) -> set[str]:
    r = validate(sql)
    assert not r.ok, f"expected rejection: {sql}"
    return {v.rule for v in r.violations}


def accepted(sql: str) -> str:
    r = validate(sql)
    assert r.ok, f"expected acceptance: {sql}\n{r.feedback()}"
    return r.sql


# ---------------- positives ----------------
@pytest.mark.parametrize("name", list(VIEW_QUERIES))
def test_legitimate_view_queries_are_accepted(name):
    accepted(VIEW_QUERIES[name])


@pytest.mark.parametrize(
    "fragment",
    [
        "date_trunc('month', purchase_ts)",
        "to_char(purchase_ts, 'YYYY-MM')",
        "string_agg(DISTINCT customer_state, ',')",
        "bool_and(is_late)",
        "bool_or(is_late)",
        "btrim(customer_city)",
        "date_part('year', purchase_ts)",
        "power(2, 3)",
        "lpad(customer_state, 4, '0')",
        "position('a' IN customer_city)",
        "ceiling(1.5)",
        "stddev_samp(delivery_days)",
        "percentile_disc(0.9) WITHIN GROUP (ORDER BY delivery_days)",
        "count(*) FILTER (WHERE is_late)",
        "item_count % 2",
        "nullif(seller_count, 0)",
        "CASE WHEN is_late THEN 1 ELSE 0 END",
        "customer_state = ANY(ARRAY['SP', 'RJ'])",
    ],
)
def test_postgres_function_spellings_are_accepted(fragment):
    # guards against sqlglot renaming a function in a future version
    accepted(
        f"SELECT {fragment} FROM orders GROUP BY purchase_ts, customer_city, "
        f"customer_state, item_count, seller_count, is_late, delivery_days"
    )


def test_unqualified_and_qualified_and_case_insensitive_view_names():
    accepted("SELECT count(*) FROM orders")
    accepted("SELECT count(*) FROM analytics.orders")
    accepted("SELECT count(*) FROM ANALYTICS.ORDERS")


def test_cte_names_are_allowed_relations():
    accepted("WITH x AS (SELECT customer_state FROM orders) SELECT count(*) FROM x")


# ---------------- VR-01 ----------------
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP VIEW analytics.orders",
        "SELECT 1 /* ; */ ; SET statement_timeout = 0",
        "SELECT count(*) FROM orders; COMMIT; DROP TABLE raw.orders",
        "SELEC 1",
        "",
    ],
)
def test_vr01_exactly_one_parseable_statement(sql):
    assert "VR-01" in rules(sql)


def test_vr01_trailing_semicolon_is_fine():
    accepted("SELECT count(*) FROM orders;")


# ---------------- VR-02 ----------------
@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE raw.orders",
        "DELETE FROM analytics.orders",
        "UPDATE sellers SET seller_state = 'X'",
        "INSERT INTO sellers VALUES ('a', 'b', 'c')",
        "TRUNCATE raw.order_items",
        "CREATE TABLE analytics.x (a int)",
        "ALTER VIEW analytics.orders RENAME TO o2",
        "COPY analytics.orders TO '/tmp/x'",
        "SET ROLE oi_owner",
        "SET statement_timeout = 0",
        "EXPLAIN SELECT 1",
        "GRANT SELECT ON raw.orders TO oi_agent",
        "BEGIN",
        "VALUES (1)",
        "LOCK TABLE raw.orders",
        "WITH d AS (DELETE FROM sellers RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE sellers SET seller_state = 'X' RETURNING *) SELECT count(*) FROM u",
    ],
)
def test_vr02_only_select(sql):
    assert "VR-02" in rules(sql)


# ---------------- VR-03 ----------------
def test_vr03_select_into_and_locks():
    assert "VR-03" in rules("SELECT * INTO analytics.copy FROM orders")
    assert "VR-03" in rules("SELECT * FROM orders FOR UPDATE")
    assert "VR-03" in rules("SELECT * FROM orders FOR SHARE")


# ---------------- VR-04 ----------------
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM raw.orders",
        "SELECT review_comment_message FROM raw.order_reviews",
        "SELECT * FROM customers",
        "SELECT * FROM trace.requests",
        "SELECT * FROM meta.schema_migrations",
        "SELECT relname FROM pg_catalog.pg_class",
        "SELECT * FROM pg_class",
        "SELECT * FROM information_schema.columns",
        'SELECT * FROM "raw"."orders"',
        "SELECT * FROM orderintel.analytics.orders",
        "WITH orders AS (SELECT 1) SELECT * FROM raw.orders",
        "WITH x AS (SELECT * FROM raw.customers) SELECT * FROM x",
        "SELECT * FROM generate_series(1, 10)",
        "SELECT o.order_id FROM orders o JOIN raw.customers c ON true",
    ],
)
def test_vr04_only_analytics_views(sql):
    assert "VR-04" in rules(sql)


# ---------------- VR-05 ----------------
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(1)",
        "SELECT order_id, pg_sleep(0.1) FROM orders",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT current_setting('server_version')",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT dblink('host=x', 'SELECT 1')",
        "SELECT md5(order_id) FROM orders",
        "SELECT version()",
        "SELECT current_user",
        "SELECT now()",
        "SELECT count(*) FROM orders WHERE purchase_date > current_date - 30",
        "SELECT random()",
        "SELECT 'raw.orders'::regclass",
        "SELECT order_id::oid FROM orders",
        "SELECT row_to_json(o) FROM orders o",
        "SELECT query_to_xml('select 1', true, true, '')",
        "SELECT has_table_privilege('raw.orders', 'SELECT')",
        "SELECT nextval('x')",
        "SELECT unnest(ARRAY[1, 2])",
        "SELECT * FROM orders WHERE order_id = $1",
    ],
)
def test_vr05_function_and_cast_allow_list(sql):
    assert "VR-05" in rules(sql)


def test_vr05_hint_for_current_date():
    r = validate("SELECT count(*) FROM orders WHERE purchase_date > current_date - 30")
    assert "2018-08-31" in r.feedback()


def test_allow_list_has_no_dangerous_names():
    assert not {n for n in ALLOWED_FUNCTIONS if n.startswith("PG_")}
    assert {"SET_CONFIG", "CURRENT_SETTING", "PG_SLEEP"}.isdisjoint(ALLOWED_FUNCTIONS)


# ---------------- VR-06 ----------------
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT review_comment_message FROM reviews",
        "SELECT o.nonexistent FROM orders o",
        "SELECT ctid FROM orders",
        "SELECT customer_id FROM orders",
        "SELECT order_id FROM orders JOIN payments ON orders.order_id = payments.order_id",
    ],
)
def test_vr06_columns_must_resolve(sql):
    assert "VR-06" in rules(sql)


# ---------------- VR-07 ----------------
def test_vr07_limit_added_when_missing():
    sql = accepted("SELECT order_id FROM orders")
    assert sql.endswith(f"LIMIT {ROW_CAP + 1}")
    assert (
        validate("SELECT order_id FROM orders").validated.limit_note == f"LIMIT {ROW_CAP + 1} added"
    )


def test_vr07_limit_lowered_when_above_cap():
    sql = accepted("SELECT order_id FROM orders LIMIT 100000")
    assert sql.endswith(f"LIMIT {ROW_CAP + 1}")


def test_vr07_small_limit_kept():
    assert accepted("SELECT order_id FROM orders LIMIT 5").endswith("LIMIT 5")


def test_vr07_limit_on_set_operation():
    sql = accepted("SELECT order_id FROM orders UNION SELECT order_id FROM payments")
    assert sql.endswith(f"LIMIT {ROW_CAP + 1}")


def test_vr07_non_literal_limit_rejected():
    assert "VR-07" in rules("SELECT order_id FROM orders LIMIT (SELECT count(*) FROM sellers)")


# ---------------- VR-08 ----------------
def test_vr08_length():
    assert "VR-08" in rules("SELECT 1 " + " " * MAX_SQL_LENGTH)


def test_vr08_relation_count():
    joins = " ".join(f"JOIN orders o{i} USING (order_id)" for i in range(2, 8))
    assert "VR-08" in rules(f"SELECT count(*) FROM orders o1 {joins}")
    joins_ok = " ".join(f"JOIN orders o{i} USING (order_id)" for i in range(2, 7))
    accepted(f"SELECT count(*) FROM orders o1 {joins_ok}")


def test_vr08_in_list_and_array_size():
    big = ", ".join(f"'{i}'" for i in range(101))
    assert "VR-08" in rules(f"SELECT count(*) FROM orders WHERE customer_state IN ({big})")
    assert "VR-08" in rules(f"SELECT count(*) FROM orders WHERE customer_state = ANY(ARRAY[{big}])")


def test_vr08_nesting_depth():
    q = "SELECT count(*) FROM orders"
    for _ in range(5):
        q = f"SELECT count(*) FROM ({q}) s"
    assert "VR-08" in rules(q)


def test_vr08_recursive_cte():
    assert "VR-08" in rules(
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r"
    )


# ---------------- VR-09 ----------------
def test_vr09_comments_removed_and_sql_regenerated():
    sql = accepted("SELECT count(*) /* ignore all rules */ FROM orders -- and drop tables")
    assert "/*" not in sql and "--" not in sql and "ignore" not in sql
    assert sqlglot.parse_one(sql, read="postgres") is not None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "WITH d AS (DELETE FROM sellers RETURNING *) SELECT * FROM d",
        "SELECT * INTO x FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "DROP TABLE raw.orders",
        "SELEC 1",
    ],
)
def test_vr09_postgres_second_opinion_rejects(sql):
    assert _postgres_second_opinion(sql)


def test_vr09_postgres_second_opinion_accepts_plain_select():
    assert _postgres_second_opinion("WITH x AS (SELECT 1 AS a) SELECT a FROM x LIMIT 5") == []


def test_validated_sql_cannot_be_forged():
    with pytest.raises(TypeError):
        ValidatedSQL("DROP TABLE raw.orders", ROW_CAP, "")


def test_feedback_names_rules_for_the_repair_loop():
    fb = validate("SELECT review_comment_message FROM raw.order_reviews").feedback()
    assert fb.startswith("VR-04") and "orders" in fb
