# PostgreSQL behaviour findings (Q-03)

Confirmed by experiment as `oi_agent` on PostgreSQL 18.6, 2026-10-15. Each finding is a regression test in `tests/integration/test_postgres_findings.py`; the permission results are in `tests/integration/test_permissions.py`.

## Behaviours the design assumed (technical design, section 7.2)

| # | Assumption | Result | Consequence for the design |
|---|---|---|---|
| 1 | Views execute with the owner's privileges | **Confirmed.** `oi_agent` reads all six views with no privilege on `raw`. | Views are a sound data boundary. |
| 2 | Built-in functions such as `pg_sleep` are executable by `PUBLIC` | **Confirmed.** `pg_sleep` and `set_config` are executable. | The validator needs a function allow-list (VR-05). |
| 3 | `set_config` can change session settings inside a plain `SELECT` | **Confirmed.** `SELECT set_config('statement_timeout','0',false)` disabled the 8 s role timeout: a 9 s `pg_sleep` then completed, while without it the same query was cancelled at 8.0 s. `default_transaction_read_only` can be switched off the same way. | Role defaults are not guarantees. The validator blocks `set_config`; the executor sets `SET LOCAL statement_timeout` and a read-only transaction itself on every request, plus a client-side timer (M4). |
| 4 | System catalogs are readable | **Confirmed.** The agent can list raw table names and column names (including `review_comment_message`) via `pg_class`/`pg_attribute`, and read view definitions. It cannot read the data. `pg_stats` shows nothing for unreadable tables. | Schema names are not secret; data is. The validator's schema allow-list (VR-04) keeps catalog queries out of generated SQL anyway. |
| 5 | `temp_file_limit` can only be set by a superuser | **Confirmed.** `SET temp_file_limit` fails with 42501. | The 256 MB role default is an enforceable limit on disk use by large sorts and joins. |

## Additional findings

- **Read-only mode is not the real wall.** With the role defaults, 15 of the 38 attack statements were rejected only because the transaction was read-only (SQLSTATE 25006). With read-only switched off by the session, all 38 are still rejected by permissions (42501). SC-01 is therefore tested in both modes.
- Other sessions' query text in `pg_stat_activity` is hidden from the agent (`<insufficient privilege>`).
- `current_setting('data_directory')` and other server paths are hidden.
- `generate_series` is callable (it is denied by the validator to limit resource use, not by the database).
- `dblink` and `postgres_fdw` are installable in this image, but only by roles allowed to create extensions; `oi_agent` is not.
- `PUBLIC` privileges on the database (CONNECT, TEMPORARY) and on schema `public` are revoked; each role receives only explicit grants. `oi_agent` therefore cannot create temporary tables.

## What these results do not prove

- They cover the listed statements on this PostgreSQL version and configuration only.
- They do not test resource exhaustion within the allowed views (Cartesian joins, huge sorts); that is the executor's job (M4) and the safety suite's (M8).
- They do not cover prompt injection; the model never connects to the database, and its SQL is validated first (M4, M8).
