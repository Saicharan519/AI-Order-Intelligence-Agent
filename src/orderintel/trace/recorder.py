"""Trace recorder: one trace.requests row per user request, plus its steps (FR-15).

The request row (kind = 'request', zero cost) is written BEFORE the agent runs, and the
request id is put in a context variable, so every LLM call the ledger records meanwhile is
linked to it (parent_id). On completion the row gets the route, status, latency, token
totals, scope, and the final response, and trace.steps gets one row per LLM call,
validator verdict, SQL or playbook step, grounding check, and lint. Everything written is
passed through redaction first (NFR-06). Written as oi_trace, which cannot read raw data.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from orderintel.api.schemas import AskResponse
from orderintel.db.connect import connect_trace
from orderintel.llm.budget import CURRENT_REQUEST
from orderintel.redact import redact, redact_json


@dataclass
class RequestTrace:
    id: str
    started: float


class TraceRecorder:
    def __init__(self, settings=None) -> None:
        self._connect = lambda: connect_trace(settings)

    @contextmanager
    def request(
        self, question: str, session_id: str | None, config_name: str = "api"
    ) -> Iterator[RequestTrace]:
        t = RequestTrace(str(uuid.uuid4()), time.perf_counter())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trace.requests (id, kind, config_name, session_id, question, status) "
                "VALUES (%s, 'request', %s, %s, %s, 'running')",
                (t.id, config_name, session_id, redact(question)),
            )
        token = CURRENT_REQUEST.set(t.id)
        try:
            yield t
        except Exception as e:
            self.fail(t, getattr(e, "code", type(e).__name__))
            raise
        finally:
            CURRENT_REQUEST.reset(token)

    def fail(self, t: RequestTrace, code: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE trace.requests SET status = 'error', error = %s, latency_ms = %s "
                "WHERE id = %s AND kind = 'request'",
                (redact(str(code)), _ms(t), t.id),
            )

    def finish(self, t: RequestTrace, r: AskResponse) -> None:
        with self._connect() as conn, conn.transaction():
            llm = conn.execute(
                "SELECT config_name, model, status, tokens_in, tokens_cache_hit, tokens_out, "
                "cost_usd, latency_ms, error FROM trace.requests "
                "WHERE parent_id = %s ORDER BY created_at",
                (t.id,),
            ).fetchall()
            conn.execute(
                """UPDATE trace.requests SET route = %s, status = %s, latency_ms = %s,
                       tokens_in = %s, tokens_cache_hit = %s, tokens_out = %s,
                       scope = %s, response = %s
                   WHERE id = %s AND kind = 'request'""",
                (
                    r.route,
                    r.status,
                    _ms(t),
                    r.usage.tokens_in,
                    r.usage.tokens_cache_hit,
                    r.usage.tokens_out,
                    redact_json(r.scope.model_dump()),
                    redact_json(r.model_dump()),
                    t.id,
                ),
            )
            steps = _steps(r, llm)
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO trace.steps (request_id, step_no, kind, payload, ms) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [(t.id, i, k, redact_json(p), ms) for i, (k, p, ms) in enumerate(steps, 1)],
                )

    def get(self, request_id: str) -> dict | None:
        """The stored response and its steps, for GET /v1/requests/{id}."""
        try:
            uuid.UUID(request_id)
        except ValueError:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at, status, route, latency_ms, response, error "
                "FROM trace.requests WHERE id = %s AND kind = 'request'",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                "SELECT step_no, kind, payload, ms FROM trace.steps "
                "WHERE request_id = %s ORDER BY step_no",
                (request_id,),
            ).fetchall()
            cost = conn.execute(
                "SELECT coalesce(sum(cost_usd), 0) FROM trace.requests WHERE parent_id = %s",
                (request_id,),
            ).fetchone()[0]
        return {
            "request_id": request_id,
            "created_at": row[0].isoformat(),
            "status": row[1],
            "route": row[2],
            "latency_ms": row[3],
            "billed_cost_usd": float(cost),
            "error": row[5],
            "response": row[4],
            "steps": [{"step_no": s[0], "kind": s[1], "payload": s[2], "ms": s[3]} for s in steps],
        }


def _ms(t: RequestTrace) -> int:
    return int((time.perf_counter() - t.started) * 1000)


def _steps(r: AskResponse, llm_rows: list[tuple]) -> list[tuple[str, dict, int | None]]:
    steps: list[tuple[str, dict, int | None]] = []
    for cfg, model, status, t_in, t_hit, t_out, cost, ms, err in llm_rows:
        steps.append(
            (
                "llm",
                {
                    "config_name": cfg,
                    "model": model,
                    "status": status,
                    "tokens_in": t_in,
                    "tokens_cache_hit": t_hit,
                    "tokens_out": t_out,
                    "cost_usd": float(cost),
                    "error": err,
                },
                ms,
            )
        )
    for e in r.evidence:
        for n, a in enumerate(e.attempts, 1):
            steps.append(
                (
                    "validator",
                    {
                        "evidence_id": e.id,
                        "attempt": n,
                        "stage": a.get("stage"),
                        "sql": a.get("sql"),
                        "feedback": a.get("feedback", ""),
                    },
                    None,
                )
            )
        steps.append(
            (
                "playbook" if e.kind == "playbook_step" else "sql",
                {
                    "evidence_id": e.id,
                    "sql": e.sql,
                    "row_count": e.row_count,
                    "rules_checked": e.validator.rules_checked if e.validator else [],
                },
                e.ms,
            )
        )
    steps.append(("grounding", r.grounding.model_dump(), None))
    steps.append(("lint", {"causal_terms": r.grounding.causal_terms, "warnings": r.warnings}, None))
    return steps
