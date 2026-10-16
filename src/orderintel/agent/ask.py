"""Ask mode: router -> SQL (validator, executor, repairs) -> answer writer -> checks.

Nodes are plain functions over a typed state, so each is testable without LangGraph; the
graph only wires them together (technical design section 3, Q-05: LangGraph 1.2.15,
StateGraph with conditional edges).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from orderintel.agent.answer import AnswerText, write_answer
from orderintel.agent.grounding import causal_findings, check_grounding, scope_texts
from orderintel.agent.pipeline import SQLRun, run_question
from orderintel.agent.router import RouterDecision, route
from orderintel.agent.scope import build_scope, choose_components
from orderintel.api.schemas import (
    AskResponse,
    Evidence,
    Followup,
    Grounding,
    Period,
    ScopeOut,
    UsageOut,
    ValidatorOut,
)
from orderintel.evaluation.compare import normalise_value
from orderintel.guard.validator import RULES
from orderintel.llm.client import LLMClient, LLMResult

EVIDENCE_PREVIEW_ROWS = 10


class AskState(TypedDict, total=False):
    question: str
    request_id: str
    config_name: str
    started: float
    decision: RouterDecision
    sqlrun: SQLRun
    llm_results: list[LLMResult]
    response: AskResponse


def _usage(state: AskState) -> UsageOut:
    results = state.get("llm_results", [])
    run = state.get("sqlrun")
    u = UsageOut(
        llm_calls=len(results) + (run.llm_calls if run else 0),
        cached_calls=sum(r.cached for r in results) + (run.cached_calls if run else 0),
        tokens_in=sum(r.usage.prompt_tokens for r in results) + (run.tokens_in if run else 0),
        tokens_cache_hit=sum(r.usage.cache_hit_tokens for r in results)
        + (run.tokens_cache_hit if run else 0),
        tokens_out=sum(r.usage.completion_tokens for r in results) + (run.tokens_out if run else 0),
        cost_usd=round(sum(r.cost_usd for r in results) + (run.cost_usd if run else 0), 8),
        latency_ms=int((time.perf_counter() - state["started"]) * 1000),
    )
    return u


def _evidence(run: SQLRun) -> Evidence:
    return Evidence(
        id="e1",
        sql=run.sql,
        row_count=len(run.rows),
        rows_preview=[[normalise_value(v) for v in r] for r in run.rows[:EVIDENCE_PREVIEW_ROWS]],
        validator=ValidatorOut(ok=run.status == "ok", rules_checked=list(RULES)),
        attempts=[a.__dict__ for a in run.attempts],
        ms=run.latency_ms,
    )


# ---------------- nodes ----------------
def make_nodes(client: LLMClient):
    def route_node(state: AskState) -> dict:
        decision, result = route(client, state["question"], state["config_name"])
        return {"decision": decision, "llm_results": [*state.get("llm_results", []), result]}

    def sql_node(state: AskState) -> dict:
        run = run_question(client, "D", state["question"], label=state["config_name"])
        return {"sqlrun": run}

    def answer_node(state: AskState) -> dict:
        run, question = state["sqlrun"], state["question"]
        scope = build_scope(run.sql or "", run.assumptions, len(run.rows), run.truncated)
        context = scope_texts(question, scope)
        results = list(state.get("llm_results", []))

        answer, res = write_answer(
            client, question, scope, run.columns, run.rows, config_name=state["config_name"]
        )
        results.append(res)
        grounding = check_grounding(answer.prose(), run.rows, context)
        causal = causal_findings(answer.prose())
        regenerated = False
        if answer.parse_error or not grounding.ok or causal:
            problems = []
            if answer.parse_error:
                problems.append(answer.parse_error)
            if grounding.untraced:
                problems.append(
                    "these numbers do not appear in the rows, question, or scope: "
                    + ", ".join(grounding.untraced)
                )
            if causal:
                problems.append("avoid causal wording: " + ", ".join(causal))
            answer, res = write_answer(
                client,
                question,
                scope,
                run.columns,
                run.rows,
                feedback="Please fix: " + "; ".join(problems),
                previous=res.content,
                config_name=state["config_name"],
            )
            results.append(res)
            regenerated = True
            grounding = check_grounding(answer.prose(), run.rows, context)
            causal = causal_findings(answer.prose())

        warnings = []
        if answer.parse_error:
            answer = AnswerText(headline="The query ran; see the table for the result.")
            warnings.append("The answer text could not be generated; showing the result only.")
        if grounding.untraced:
            warnings.append(
                "Some numbers in the text could not be traced to the result: "
                + ", ".join(grounding.untraced)
            )
        if causal:
            warnings.append(
                "The text uses causal wording ("
                + ", ".join(causal)
                + "); the data shows associations only."
            )

        response = AskResponse(
            request_id=state["request_id"],
            route="answer",
            status="ok",
            headline=answer.headline,
            components=choose_components(run.columns, run.rows),
            scope=ScopeOut(
                period=Period(
                    start=scope.period_start, end=scope.period_end, source=scope.period_source
                ),
                definitions=scope.definitions,
                assumptions=scope.assumptions,
                n=scope.n,
                truncated=scope.truncated,
                partial_period_warnings=scope.partial_period_warnings,
            ),
            evidence=[_evidence(run)],
            notes=answer.notes,
            caveats=answer.caveats + scope.partial_period_warnings,
            warnings=warnings,
            grounding=Grounding(
                numbers_checked=grounding.numbers_checked,
                untraced=grounding.untraced,
                causal_terms=causal,
                regenerated=regenerated,
            ),
            followups=[Followup(label=q, question=q) for q in answer.followups],
        )
        new_state = {**state, "llm_results": results}
        response.usage = _usage(new_state)
        return {"llm_results": results, "response": response}

    def sql_failed_node(state: AskState) -> dict:
        run = state["sqlrun"]
        if run.status == "declined":
            headline = "This question cannot be answered from the order data."
            status, route_name = "refused", "refuse"
        else:
            headline = (
                "No answer: a valid query could not be produced after "
                f"{run.repairs} repair attempt(s). The last attempt is shown as evidence."
            )
            status, route_name = "sql_failed", "answer"
        resp = AskResponse(
            request_id=state["request_id"],
            route=route_name,
            status=status,
            headline=headline,
            evidence=[_evidence(run)],
            caveats=run.assumptions if run.status == "declined" else [],
            warnings=[run.error] if run.error else [],
        )
        resp.usage = _usage(state)
        return {"response": resp}

    def clarify_node(state: AskState) -> dict:
        d = state["decision"]
        resp = AskResponse(
            request_id=state["request_id"],
            route="clarify",
            status="clarify",
            headline=d.clarifying_question or "Could you clarify the question?",
            notes=[d.reason] if d.reason else [],
        )
        resp.usage = _usage(state)
        return {"response": resp}

    def refuse_node(state: AskState) -> dict:
        d = state["decision"]
        resp = AskResponse(
            request_id=state["request_id"],
            route="refuse",
            status="refused",
            headline="I can't help with that request.",
            notes=[d.reason] if d.reason else [],
        )
        resp.usage = _usage(state)
        return {"response": resp}

    def investigate_node(state: AskState) -> dict:
        d = state["decision"]
        resp = AskResponse(
            request_id=state["request_id"],
            route="investigate",
            status="not_available",
            headline=(
                f"This is an investigation question ({d.playbook}, "
                f"{d.params.period}{', ' + d.params.state if d.params.state else ''}). "
                "Investigate mode arrives in milestone M7."
            ),
        )
        resp.usage = _usage(state)
        return {"response": resp}

    return {
        "route": route_node,
        "sql": sql_node,
        "answer": answer_node,
        "sql_failed": sql_failed_node,
        "clarify": clarify_node,
        "refuse": refuse_node,
        "investigate": investigate_node,
    }


def build_graph(client: LLMClient):
    nodes = make_nodes(client)
    g = StateGraph(AskState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        lambda s: s["decision"].route,
        {"answer": "sql", "clarify": "clarify", "refuse": "refuse", "investigate": "investigate"},
    )
    g.add_conditional_edges(
        "sql",
        lambda s: "ok" if s["sqlrun"].ran else "failed",
        {"ok": "answer", "failed": "sql_failed"},
    )
    for terminal in ("answer", "sql_failed", "clarify", "refuse", "investigate"):
        g.add_edge(terminal, END)
    return g.compile()


def ask(client: LLMClient, question: str, config_name: str = "ask", graph=None) -> AskResponse:
    app = graph or build_graph(client)
    state: dict[str, Any] = {
        "question": question,
        "request_id": str(uuid.uuid4()),
        "config_name": config_name,
        "started": time.perf_counter(),
        "llm_results": [],
    }
    return app.invoke(state)["response"]
