"""Question -> SQL -> result, for the ablation configurations (technical design 8.3).

A, B, C: one SQL-generation call; the SQL runs as oi_eval (read-only, timeout, row cap)
         WITHOUT the validator, because these configurations measure generation alone.
D:       the product path: validator, guarded executor (oi_agent), and at most two
         repairs in which the model sees why its SQL was rejected (FR-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg
from psycopg import sql as pgsql

from orderintel.agent.sqlgen import (
    PROMPT_VERSION,
    SQLGEN_MAX_TOKENS,
    build_messages,
    parse_reply,
    repair_messages,
)
from orderintel.db.connect import connect_eval
from orderintel.db.executor import ExecutionError, execute
from orderintel.guard.validator import ROW_CAP, validate
from orderintel.llm.client import LLMClient

MAX_REPAIRS = 2
EVAL_TIMEOUT_S = 10


@dataclass
class Attempt:
    sql: str | None
    stage: str  # parse_error | declined | rejected | exec_error | ok
    feedback: str = ""


@dataclass
class SQLRun:
    config: str
    question: str
    sql: str | None = None
    assumptions: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    status: str = "pending"  # ok | declined | parse_error | rejected | exec_error
    error: str = ""
    truncated: bool = False
    attempts: list[Attempt] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_cache_hit: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    cached_calls: int = 0

    @property
    def repairs(self) -> int:
        return max(len(self.attempts) - 1, 0)

    @property
    def ran(self) -> bool:
        return self.status == "ok"


def eval_execute(sql: str) -> tuple[list[str], list[tuple], bool]:
    """Run unvalidated SQL for configurations A to C: read-only role, read-only transaction,
    statement timeout, at most ROW_CAP rows. The database permissions are the safety net."""
    with connect_eval() as conn:
        conn.read_only = True
        with conn.transaction(force_rollback=True):
            conn.execute(
                pgsql.SQL("SET LOCAL statement_timeout = {}").format(
                    pgsql.Literal(f"{EVAL_TIMEOUT_S}s")
                )
            )
            cur = conn.execute(pgsql.SQL(sql))
            rows = cur.fetchmany(ROW_CAP + 1)
            cols = [d.name for d in cur.description or []]
    return cols, rows[:ROW_CAP], len(rows) > ROW_CAP


def _call(client: LLMClient, run: SQLRun, messages: list[dict], config_name: str) -> str:
    r = client.complete(
        messages,
        config_name=config_name,
        prompt_version=PROMPT_VERSION,
        max_tokens=SQLGEN_MAX_TOKENS,
        question=run.question,
    )
    run.llm_calls += 1
    run.cached_calls += r.cached
    run.cost_usd += r.cost_usd
    run.latency_ms += r.latency_ms
    run.tokens_in += r.usage.prompt_tokens
    run.tokens_cache_hit += r.usage.cache_hit_tokens
    run.tokens_out += r.usage.completion_tokens
    return r.content


def run_question(client: LLMClient, config: str, question: str, label: str = "eval") -> SQLRun:
    run = SQLRun(config=config, question=question)
    config_name = f"{label}:{config}"
    messages = build_messages(config, question)
    attempts_allowed = 1 + (MAX_REPAIRS if config == "D" else 0)

    for _ in range(attempts_allowed):
        reply = _call(client, run, messages, config_name)
        sql, assumptions, parse_error = parse_reply(reply)
        run.sql, run.assumptions = sql, assumptions

        if parse_error:
            feedback = parse_error
            run.attempts.append(Attempt(None, "parse_error", feedback))
            run.status, run.error = "parse_error", feedback
        elif sql is None:
            run.attempts.append(Attempt(None, "declined", "; ".join(assumptions)))
            run.status = "declined"
            return run  # a deliberate refusal is not repaired
        elif config != "D":
            try:
                run.columns, run.rows, run.truncated = eval_execute(sql)
                run.attempts.append(Attempt(sql, "ok"))
                run.status = "ok"
            except psycopg.Error as e:
                msg = (e.diag.message_primary if e.diag else None) or type(e).__name__
                run.attempts.append(Attempt(sql, "exec_error", msg))
                run.status, run.error = "exec_error", msg
            return run
        else:
            v = validate(sql)
            if not v.ok:
                feedback = v.feedback()
                run.attempts.append(Attempt(sql, "rejected", feedback))
                run.status, run.error = "rejected", feedback
            else:
                try:
                    res = execute(v.validated)
                    run.sql = v.sql
                    run.columns, run.rows, run.truncated = res.columns, res.rows, res.truncated
                    run.attempts.append(Attempt(v.sql, "ok"))
                    run.status = "ok"
                    return run
                except ExecutionError as e:
                    feedback = f"{e.code}: {e.message}"
                    run.attempts.append(Attempt(v.sql, "exec_error", feedback))
                    run.status, run.error = "exec_error", feedback
        if config == "D":
            messages = repair_messages(messages, reply, feedback)
    return run
