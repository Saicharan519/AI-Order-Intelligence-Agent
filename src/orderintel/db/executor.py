"""Guarded query executor (technical design, section 7.3).

The single path from validated SQL to the database. It accepts only ValidatedSQL objects
(minted by the validator) and runs them as oi_agent with its own limits, because role
defaults can be changed by a session (docs/postgres_findings.md):

  1. read-only transaction, always rolled back;
  2. SET LOCAL statement_timeout (server-side guard) and search_path;
  3. EXPLAIN cost ceiling: obviously expensive plans are refused before they run
     (an estimate; the timeout is the real guard);
  4. fetch at most row_cap + 1 rows, flagging truncation;
  5. a client-side timer cancels the query if the server timeout does not fire.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from orderintel.config import Settings
from orderintel.db.connect import connect_agent
from orderintel.guard.validator import ValidatedSQL

DEFAULT_TIMEOUT_S = 8.0
CANCEL_GRACE_S = 2.0
# Planner cost units, calibrated in M4: 26 legitimate view queries cost at most about
# 40,000; a self-join on purchase_month costs about 540,000 and a cartesian join about
# 112,000,000. Re-tuned in M5 from real model-written queries. An estimate only: the
# statement timeout is the real guard.
DEFAULT_COST_CEILING = 250_000.0


class ExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code  # not_validated | cost_ceiling | timeout | database_error
        self.message = message


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    explain_cost: float
    explain_rows: float
    ms: int
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _set_local(conn: psycopg.Connection, name: str, value: str) -> None:
    conn.execute(sql.SQL("SET LOCAL {} = {}").format(sql.Identifier(name), sql.Literal(value)))


def explain(conn: psycopg.Connection, query: ValidatedSQL) -> tuple[float, float]:
    plan = conn.execute(sql.SQL("EXPLAIN (FORMAT JSON) ") + sql.SQL(query.sql)).fetchone()[0]
    top = plan[0]["Plan"]
    return float(top["Total Cost"]), float(top["Plan Rows"])


def execute(
    query: ValidatedSQL,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cost_ceiling: float = DEFAULT_COST_CEILING,
    settings: Settings | None = None,
) -> QueryResult:
    if not isinstance(query, ValidatedSQL):
        raise ExecutionError("not_validated", "only SQL returned by the validator can be executed")

    started = time.perf_counter()
    conn = connect_agent(settings)
    conn.read_only = True  # every transaction starts as BEGIN READ ONLY
    timer = threading.Timer(timeout_s + CANCEL_GRACE_S, conn.cancel_safe)
    timer.daemon = True
    try:
        with conn.transaction(force_rollback=True):
            _set_local(conn, "statement_timeout", f"{int(timeout_s * 1000)}ms")
            _set_local(conn, "search_path", "analytics")

            cost, est_rows = explain(conn, query)
            if cost > cost_ceiling:
                raise ExecutionError(
                    "cost_ceiling",
                    f"estimated cost {cost:,.0f} exceeds the ceiling {cost_ceiling:,.0f}; "
                    "add filters or aggregate before joining",
                )

            timer.start()
            cur = conn.execute(sql.SQL(query.sql))
            rows = cur.fetchmany(query.row_cap + 1)
            columns = [d.name for d in cur.description or []]
    except psycopg.errors.QueryCanceled as e:
        raise ExecutionError("timeout", f"query exceeded {timeout_s:g} s and was cancelled") from e
    except psycopg.Error as e:
        message = (e.diag.message_primary if e.diag else None) or type(e).__name__
        raise ExecutionError("database_error", message) from e
    finally:
        timer.cancel()
        conn.close()

    truncated = len(rows) > query.row_cap
    notes = [query.limit_note] if query.limit_note else []
    if truncated:
        notes.append(f"result truncated to {query.row_cap} rows")
    return QueryResult(
        columns=columns,
        rows=rows[: query.row_cap],
        truncated=truncated,
        explain_cost=cost,
        explain_rows=est_rows,
        ms=int((time.perf_counter() - started) * 1000),
        notes=notes,
    )
