"""Ask mode: router -> SQL (validator, executor, repairs) -> answer writer -> checks.

Nodes are plain functions over a typed state, so each is testable without LangGraph; the
graph only wires them together (technical design section 3, Q-05: LangGraph 1.2.15,
StateGraph with conditional edges).
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from orderintel.agent.answer import AnswerText, write_answer
from orderintel.agent.grounding import causal_findings, check_grounding, scope_texts
from orderintel.agent.narrate import narrate
from orderintel.agent.pipeline import SQLRun, run_question
from orderintel.agent.router import RouterDecision, route
from orderintel.agent.scope import build_scope, choose_components
from orderintel.agent.session import STORE, SessionScope, SessionStore, scope_presence_warnings
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
from orderintel.playbooks import PLAYBOOKS
from orderintel.playbooks.base import PlaybookParams

EVIDENCE_PREVIEW_ROWS = 10


class AskState(TypedDict, total=False):
    question: str
    request_id: str
    config_name: str
    session_id: str | None
    inherited: SessionScope | None
    started: float
    decision: RouterDecision
    sqlrun: SQLRun
    llm_results: list[LLMResult]
    response: AskResponse


def month_end(first_day: dt.date) -> dt.date:
    """Last day of the month that starts on first_day."""
    return (first_day + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)


def _with_scope(question: str, scope: SessionScope | None) -> str:
    return question if scope is None else f"{question}\n\n{scope.context_for_sql()}"


def _inherited_filters(scope: SessionScope | None) -> list[str]:
    if scope is None:
        return []
    return [f"inherited from investigation {scope.source_request_id[:8]}: {scope.describe()}"]


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
def make_nodes(client: LLMClient, store: SessionStore = STORE):
    def route_node(state: AskState) -> dict:
        question = _with_scope(state["question"], state.get("inherited"))
        decision, result = route(client, question, state["config_name"])
        return {"decision": decision, "llm_results": [*state.get("llm_results", []), result]}

    def sql_node(state: AskState) -> dict:
        question = _with_scope(state["question"], state.get("inherited"))
        run = run_question(client, "D", question, label=state["config_name"])
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
        inherited = state.get("inherited")
        if inherited is not None:
            warnings += scope_presence_warnings(run.sql or "", inherited)

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
                filters=_inherited_filters(inherited),
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
        params = PlaybookParams(period=d.params.period, state=d.params.state)
        module = PLAYBOOKS[d.playbook]
        pb_run, f = module.run(params)
        findings = f.as_dict()
        narration, check, narr_results, regenerated = narrate(
            client, state["question"], findings, state["config_name"]
        )
        results = [*state.get("llm_results", []), *narr_results]

        warnings = []
        if narration.parse_error:
            warnings.append("The narration could not be generated; showing the findings only.")
        if check.untraced:
            warnings.append(
                "Some numbers in the narration could not be traced to the findings: "
                + ", ".join(check.untraced)
            )
        if not check.driver_agrees:
            warnings.append(
                f"The narration named a different top driver than the computed one "
                f"({f.top_driver}); trust the findings table."
            )
        if check.causal_terms:
            warnings.append(
                "The narration uses causal wording ("
                + ", ".join(check.causal_terms)
                + "); the data shows associations only."
            )

        population = (
            "delivered orders"
            if d.playbook == "late_delivery_diagnosis"
            else "orders with a review"
        )
        store.set(
            state.get("session_id"),
            SessionScope(params.period, params.state, population, state["request_id"], time.time()),
        )
        where = f" in {params.state}" if params.state else ""
        followups = []
        if f.verdict == "elevated":
            followups.append(
                Followup(
                    label=f"Which sellers had the most late orders{where} in {params.period}?",
                    question=f"Which sellers had the most late orders{where} in {params.period}?",
                    inherits_scope=True,
                )
            )
            followups.append(
                Followup(
                    label=f"Break down {params.period}{where} by product category",
                    question=f"Break down {params.period}{where} by product category.",
                    inherits_scope=True,
                )
            )

        month = params.month
        resp = AskResponse(
            request_id=state["request_id"],
            route="investigate",
            status="ok",
            headline=narration.headline or f"Verdict: {f.verdict}.",
            components=[
                {
                    "type": "report",
                    "playbook": d.playbook,
                    "verdict": f.verdict,
                    "top_driver": f.top_driver,
                    "findings": findings,
                }
            ],
            scope=ScopeOut(
                period=Period(
                    start=month.isoformat(), end=month_end(month).isoformat(), source="sql"
                ),
                population=population,
                filters=[f"state {params.state}"] if params.state else [],
                definitions=[
                    "Baseline: all other months of January 2017 to August 2018, same filters"
                ],
                n=getattr(f, "delivered_orders", None) or getattr(f, "reviews", 0),
            ),
            evidence=[
                Evidence(
                    id=f"s{i + 1}",
                    kind="playbook_step",
                    sql=s.sql,
                    params=params.model_dump(),
                    row_count=len(s.rows),
                    rows_preview=[
                        [normalise_value(v) for v in r] for r in s.rows[:EVIDENCE_PREVIEW_ROWS]
                    ],
                    validator=ValidatorOut(ok=True, rules_checked=list(RULES)),
                    ms=s.ms,
                )
                for i, s in enumerate(pb_run.steps)
            ],
            notes=narration.summary_points,
            caveats=list(dict.fromkeys([*narration.caveats, *f.caveats])),
            warnings=warnings,
            grounding=Grounding(
                numbers_checked=check.numbers_checked,
                untraced=check.untraced,
                causal_terms=check.causal_terms,
                regenerated=regenerated,
            ),
            followups=followups,
        )
        resp.usage = _usage({**state, "llm_results": results})
        return {"llm_results": results, "response": resp}

    return {
        "route": route_node,
        "sql": sql_node,
        "answer": answer_node,
        "sql_failed": sql_failed_node,
        "clarify": clarify_node,
        "refuse": refuse_node,
        "investigate": investigate_node,
    }


def build_graph(client: LLMClient, store: SessionStore = STORE):
    nodes = make_nodes(client, store)
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


def ask(
    client: LLMClient,
    question: str,
    config_name: str = "ask",
    graph=None,
    session_id: str | None = None,
    store: SessionStore = STORE,
    request_id: str | None = None,
) -> AskResponse:
    app = graph or build_graph(client, store)
    state: dict[str, Any] = {
        "question": question,
        "request_id": request_id or str(uuid.uuid4()),
        "config_name": config_name,
        "session_id": session_id,
        "inherited": store.get(session_id),
        "started": time.perf_counter(),
        "llm_results": [],
    }
    return app.invoke(state)["response"]
