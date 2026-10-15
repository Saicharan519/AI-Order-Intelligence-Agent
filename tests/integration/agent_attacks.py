"""Statements oi_agent must never be able to execute (SC-01, technical design L2).

Each case is run directly against the database, bypassing the validator (M4), to show
that the database permissions alone contain the agent. Every statement is executed in
its own transaction and rolled back.

expected: the SQLSTATE PostgreSQL returns when read-only mode is switched OFF, i.e. the
error that comes from permissions rather than from the read-only default.
  42501 insufficient_privilege
  42P01 undefined_table (the schema is not on the role's search path or not visible)
"""

PRIV = "42501"

AGENT_MUST_FAIL: list[tuple[str, str, str]] = [
    # (id, sql, expected SQLSTATE with read-only off)
    # --- reading outside the views ---
    ("read_raw_orders", "SELECT count(*) FROM raw.orders", PRIV),
    ("read_raw_review_text", "SELECT review_comment_message FROM raw.order_reviews LIMIT 1", PRIV),
    ("read_raw_customers", "SELECT * FROM raw.customers LIMIT 1", PRIV),
    ("read_trace_requests", "SELECT * FROM trace.requests LIMIT 1", PRIV),
    ("read_trace_spend", "SELECT * FROM trace.spend", PRIV),
    ("read_meta_migrations", "SELECT * FROM meta.schema_migrations", PRIV),
    ("read_pg_authid", "SELECT rolpassword FROM pg_authid", PRIV),
    ("read_server_file", "SELECT pg_read_file('/etc/passwd')", PRIV),
    ("read_server_dir", "SELECT pg_ls_dir('.')", PRIV),
    ("large_object_import", "SELECT lo_import('/etc/passwd')", PRIV),
    # --- writing through the views or directly ---
    ("insert_view", "INSERT INTO analytics.sellers VALUES ('x', 'y', 'SP')", PRIV),
    ("update_view", "UPDATE analytics.sellers SET seller_state = 'XX'", PRIV),
    ("delete_view", "DELETE FROM analytics.sellers", PRIV),
    ("insert_raw", "INSERT INTO raw.sellers VALUES ('x', '1', 'y', 'SP')", PRIV),
    ("update_raw", "UPDATE raw.orders SET order_status = 'x'", PRIV),
    ("truncate_raw", "TRUNCATE raw.orders", PRIV),
    ("insert_trace", "INSERT INTO trace.requests (id, config_name, status) "
                     "VALUES (gen_random_uuid(), 'x', 'x')", PRIV),
    ("copy_to_file", "COPY (SELECT 1) TO '/tmp/oi_agent_test.csv'", PRIV),
    ("copy_from_program", "COPY analytics.sellers FROM PROGRAM 'id'", PRIV),
    # --- changing structure ---
    ("drop_view", "DROP VIEW analytics.orders", PRIV),
    ("drop_raw_table", "DROP TABLE raw.orders", PRIV),
    ("alter_view", "ALTER VIEW analytics.orders RENAME TO o2", PRIV),
    ("create_table_analytics", "CREATE TABLE analytics.x (a int)", PRIV),
    ("create_table_public", "CREATE TABLE public.x (a int)", PRIV),
    ("create_temp_table", "CREATE TEMP TABLE x (a int)", PRIV),
    ("create_schema", "CREATE SCHEMA x", PRIV),
    ("create_function",
     "CREATE FUNCTION analytics.f() RETURNS int LANGUAGE sql AS 'SELECT 1'", PRIV),
    ("create_extension", "CREATE EXTENSION dblink", PRIV),
    ("lock_raw", "LOCK TABLE raw.orders", PRIV),
    ("lock_view", "LOCK TABLE analytics.orders IN ACCESS EXCLUSIVE MODE", PRIV),
    # --- privilege escalation ---
    ("set_role_owner", "SET ROLE oi_owner", PRIV),
    ("set_session_auth", "SET SESSION AUTHORIZATION postgres", PRIV),
    ("alter_own_role", "ALTER ROLE oi_agent SUPERUSER", PRIV),
    ("create_role", "CREATE ROLE evil LOGIN", PRIV),
    ("grant_raw", "GRANT SELECT ON raw.orders TO oi_agent", PRIV),
    ("alter_system", "ALTER SYSTEM SET statement_timeout = 0", PRIV),
    ("raise_temp_file_limit", "SET temp_file_limit = '100GB'", PRIV),
    ("create_database", "CREATE DATABASE evil", PRIV),
]

AGENT_MUST_SUCCEED: list[tuple[str, str]] = [
    (view, f"SELECT * FROM analytics.{view} LIMIT 1")  # noqa: S608
    for view in ("orders", "order_items", "payments", "reviews", "sellers", "data_coverage")
]
