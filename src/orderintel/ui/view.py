"""Pure helpers for the UI (no Streamlit): API access, error messages, scope lines, tables.

Kept separate from the Streamlit script so they can be unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

# T-9.5: every error the API can return, in words for the user.
ERROR_MESSAGES = {
    "budget_exhausted": "The spending limit for the language model is reached, so no question "
    "can be answered right now. No call was made.",
    "llm_disabled": "Questions are paused by the operator (kill switch).",
    "rate_limited": "Too many questions in a short time. Please wait a moment and try again.",
    "unauthorized": "The access code is missing or wrong.",
    "access_not_configured": "The server has no access code configured, so it refuses all "
    "questions.",
    "provider_error": "The language model service is unavailable. Please try again later.",
    "invalid_request": "The question could not be sent: keep it between 1 and 500 characters.",
    "internal_error": "Something went wrong on the server.",
    "not_found": "That request was not found.",
    "connection_error": "The API is not reachable. Is it running?",
}

# Statuses that are answers but not successes.
STATUS_MESSAGES = {
    "clarify": ("info", "The question is ambiguous. Please choose or rephrase:"),
    "refused": ("info", "This question is outside what the data can answer."),
    "sql_failed": (
        "error",
        "No safe query could be produced for this question (the validator rejected every "
        "attempt, or the query failed or timed out). Nothing was run against the data.",
    ),
    "not_available": ("info", "The data has nothing for that period or analysis."),
    "error": ("error", "The request failed."),
}


@dataclass
class ApiResult:
    ok: bool
    data: dict | None = None
    error_code: str | None = None
    status_code: int = 0


class HttpApi:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, code: str, json: dict | None = None) -> ApiResult:
        try:
            r = httpx.request(
                method,
                self.base_url + path,
                json=json,
                headers={"X-Access-Code": code},
                timeout=self.timeout,
            )
        except httpx.HTTPError:
            return ApiResult(False, error_code="connection_error")
        try:
            body = r.json()
        except ValueError:
            return ApiResult(False, error_code="internal_error", status_code=r.status_code)
        if r.status_code >= 400:
            code_ = (body.get("error") or {}).get("code", "internal_error")
            return ApiResult(False, error_code=code_, status_code=r.status_code)
        return ApiResult(True, data=body, status_code=r.status_code)

    def ask(self, code: str, question: str, session_id: str) -> ApiResult:
        return self._call("POST", "/v1/ask", code, {"question": question, "session_id": session_id})

    def budget(self, code: str) -> ApiResult:
        return self._call("GET", "/v1/budget", code)

    def clear_scope(self, code: str, session_id: str) -> ApiResult:
        return self._call("POST", f"/v1/sessions/{session_id}/scope/clear", code)


def error_message(code: str | None) -> str:
    return ERROR_MESSAGES.get(code or "", ERROR_MESSAGES["internal_error"])


def scope_lines(scope: dict) -> list[str]:
    """The scope statement (FR-08) as short lines."""
    lines = []
    p = scope.get("period")
    if p:
        lines.append(f"Period: {p['start']} to {p['end']}")
    if scope.get("population"):
        lines.append(f"Population: {scope['population']}")
    for f in scope.get("filters") or []:
        lines.append(f"Filter: {f}")
    for d in scope.get("definitions") or []:
        lines.append(f"Definition: {d}")
    for a in scope.get("assumptions") or []:
        lines.append(f"Assumption: {a}")
    if scope.get("n"):
        lines.append(
            f"Rows: {scope['n']:,}" + (" (truncated at 500)" if scope.get("truncated") else "")
        )
    return lines


def to_number(v: Any) -> Any:
    """API rows carry decimals as strings; turn numeric strings back into numbers."""
    if isinstance(v, str):
        try:
            d = Decimal(v)
        except InvalidOperation:
            return v
        return int(d) if d == d.to_integral_value() and "." not in v else float(d)
    return v


def table_records(columns: list[str], rows: list[list]) -> list[dict]:
    return [dict(zip(columns, [to_number(v) for v in r], strict=False)) for r in rows]


def find_table(components: list[dict]) -> dict | None:
    return next((c for c in components if c.get("type") == "table"), None)


def usage_line(usage: dict) -> str:
    cached = f", {usage['cached_calls']} cached" if usage.get("cached_calls") else ""
    return (
        f"{usage.get('llm_calls', 0)} model calls{cached} · "
        f"{usage.get('tokens_in', 0):,} tokens in, {usage.get('tokens_out', 0):,} out · "
        f"${usage.get('cost_usd', 0):.5f} · {usage.get('latency_ms', 0) / 1000:.1f} s"
    )


def report_metrics(findings: dict) -> list[tuple[str, str, str | None]]:
    """(label, value, delta) for the headline numbers of either playbook."""
    out = []
    if findings.get("late_rate") is not None:
        out.append(
            (
                "Late rate",
                f"{findings['late_rate']}%",
                f"{findings.get('delta_points', 0):+} pts vs {findings.get('baseline_rate')}%",
            )
        )
        out.append(("Delivered orders", f"{findings.get('delivered_orders', 0):,}", None))
    if findings.get("one_star_share") is not None:
        out.append(
            (
                "1-star share",
                f"{findings['one_star_share']}%",
                f"{findings.get('delta_points', 0):+} pts vs "
                f"{findings.get('one_star_share_baseline')}%",
            )
        )
        out.append(
            (
                "Average score",
                str(findings.get("avg_score")),
                f"baseline {findings.get('avg_score_baseline')}",
            )
        )
    return out


def stage_rows(findings: dict) -> list[dict]:
    rows = []
    for label, key in [
        ("Seller handling", "handling_days"),
        ("Carrier transit", "transit_days"),
        ("Promised", "promised_days"),
    ]:
        if findings.get(key) is not None:
            rows.append(
                {
                    "stage": label,
                    "period (days)": findings[key],
                    "baseline (days)": findings.get(f"{key}_baseline"),
                }
            )
    return rows


GROUP_FIELDS = [
    ("top_states", "States by excess late orders"),
    ("top_sellers", "Sellers by excess late orders"),
    ("top_categories", "Categories with the highest late rate"),
    ("worst_categories", "Categories with the lowest scores"),
    ("worst_sellers", "Sellers with the lowest scores"),
]


def md(text: str) -> str:
    """Escape '$' for Streamlit Markdown, which reads two dollar signs as a LaTeX formula
    ("R$497,971 ... R$486,519" rendered as math). Found in the M9 end-to-end check."""
    return str(text).replace("$", r"\$")
