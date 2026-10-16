"""Order Intelligence Agent: Streamlit UI (T-9.3, T-9.5; PRD section 8).

Talks only to the HTTP API. The access code is typed by the user and kept in the
Streamlit session (server side); it is never pre-filled or shown.

Run (with the API already running):  streamlit run src/orderintel/ui/app.py
Local mode:  streamlit run src/orderintel/ui/app.py -- --local
  The UI server reads ACCESS_CODE from .env and sends it to the API itself; the code stays
  in the Python process and never reaches the browser. Accepted only when API_URL points to
  localhost or 127.0.0.1, so a deployed UI always asks for the code.
Tests inject a fake API through st.session_state["api"].
"""

from __future__ import annotations

import sys
import uuid
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from orderintel.config import get_settings
from orderintel.ui.view import (
    GROUP_FIELDS,
    STATUS_MESSAGES,
    HttpApi,
    error_message,
    find_table,
    md,
    report_metrics,
    scope_lines,
    stage_rows,
    table_records,
    usage_line,
)

EXAMPLES = [
    "Top 5 categories by revenue in 2017",
    "How is the late-delivery rate trending?",
    "Why was March 2018 so bad for deliveries?",
]

SETTINGS = get_settings()
LOCAL = "--local" in sys.argv[1:] and urlparse(SETTINGS.api_url).hostname in (
    "localhost",
    "127.0.0.1",
)

st.set_page_config(page_title="Order Intelligence Agent", layout="wide")
ss = st.session_state
if "api" not in ss:
    ss.api = HttpApi(SETTINGS.api_url)
ss.setdefault("session_id", uuid.uuid4().hex[:16])
ss.setdefault("result", None)
ss.setdefault("error", None)
ss.setdefault("active_scope", None)
ss.setdefault("pending", None)


def access_code() -> str:
    if LOCAL and SETTINGS.access_code:
        return SETTINGS.access_code.get_secret_value()
    return ss.get("access_code", "")


def submit(question: str) -> None:
    res = ss.api.ask(access_code(), question, ss.session_id)
    ss.question = question
    if res.ok:
        ss.result, ss.error = res.data, None
        if res.data["route"] == "investigate":
            ss.active_scope = scope_lines(res.data["scope"])[:2]
    else:
        ss.result, ss.error = None, res.error_code


# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Order Intelligence Agent")
    if st.button("Show budget"):
        b = ss.api.budget(access_code())
        if b.ok:
            d = b.data
            st.caption(
                f"Spent ${d['total_usd']:.4f} of ${d['total_cap_usd']:.2f} "
                f"(today ${d['today_usd']:.4f} of ${d['daily_cap_usd']:.2f})"
            )
        else:
            st.error(error_message(b.error_code))
    st.caption("Examples")
    for i, q in enumerate(EXAMPLES):
        if st.button(q, key=f"example_{i}"):
            ss.pending = q

# The access code sits on the main page (not the sidebar), so it stays visible in narrow
# windows. Typed by the user, kept server side, never pre-filled or shown.
if LOCAL:
    st.caption("Local mode: the UI server uses the access code from .env.")
else:
    st.text_input(
        "Access code",
        type="password",
        key="access_code",
        help="The ACCESS_CODE configured on the server. Press Enter after typing.",
    )
# The scope bar sits at the top but is filled after the question below has run, so an
# investigation's scope shows in the same run that set it.
scope_bar = st.container()

# ---------------- question ----------------
with st.form("ask"):
    question = st.text_input("Ask a question about the orders", max_chars=500, key="question_box")
    asked = st.form_submit_button("Ask")
if asked and question.strip():
    submit(question.strip())
elif ss.pending:
    q, ss.pending = ss.pending, None
    submit(q)

# ---------------- scope bar ----------------
if ss.active_scope:
    c1, c2 = scope_bar.columns([5, 1])
    c1.info("Session scope (follow-ups inherit it): " + " · ".join(ss.active_scope))
    if c2.button("Clear scope"):
        ss.api.clear_scope(access_code(), ss.session_id)
        ss.active_scope = None
        st.rerun()

# ---------------- result ----------------
if ss.error:
    st.error(error_message(ss.error))

r = ss.result
if r:
    st.subheader(md(r["headline"]))
    level, msg = STATUS_MESSAGES.get(r["status"], (None, None))
    if level:
        getattr(st, level)(msg)
    for w in r.get("warnings") or []:
        st.warning(md(w))
    if r["grounding"].get("untraced"):
        st.warning(
            "Some numbers in this answer could not be traced to the query results: "
            + ", ".join(r["grounding"]["untraced"])
        )

    comps = r.get("components") or []
    table = find_table(comps)
    for comp in comps:
        kind = comp.get("type")
        if kind == "text" and comp.get("variant") == "answer_card":
            cols = st.columns(max(len(comp["columns"]), 1))
            for col, name, value in zip(cols, comp["columns"], comp["row"], strict=False):
                col.metric(name, f"{value:,}" if isinstance(value, int) else str(value))
        elif kind == "text":
            st.write(md(comp.get("text", "")))
        elif kind == "table":
            st.dataframe(
                pd.DataFrame(table_records(comp["columns"], comp["rows"])), hide_index=True
            )
        elif kind == "chart" and table:
            df = pd.DataFrame(table_records(table["columns"], table["rows"]))
            chart = st.line_chart if comp.get("kind") == "line" else st.bar_chart
            chart(df, x=comp["x"], y=comp["y"])
        elif kind == "report":
            f = comp["findings"]
            st.markdown(
                f"**Verdict:** {comp['verdict'].replace('_', ' ')} · "
                f"**Top driver:** {comp['top_driver'].replace('_', ' ')}"
            )
            metrics = report_metrics(f)
            if metrics:
                for col, (label, value, delta) in zip(
                    st.columns(len(metrics)), metrics, strict=True
                ):
                    col.metric(label, value, delta, delta_color="off")
            if stage_rows(f):
                st.dataframe(pd.DataFrame(stage_rows(f)), hide_index=True)
            for key, title in GROUP_FIELDS:
                if f.get(key):
                    st.caption(title)
                    st.dataframe(pd.DataFrame(f[key]), hide_index=True)

    for n in r.get("notes") or []:
        st.markdown(f"- {md(n)}")
    for c in r.get("caveats") or []:
        st.caption(f"Caveat: {md(c)}")

    with st.expander("Scope", expanded=True):
        for line in scope_lines(r["scope"]):
            st.write(md(line))
        for w in r["scope"].get("partial_period_warnings") or []:
            st.warning(md(w))

    with st.expander(f"Evidence ({len(r.get('evidence') or [])} queries)"):
        for e in r.get("evidence") or []:
            v = e.get("validator") or {}
            st.markdown(
                f"**{e['id']}** · {e['kind']} · {e['row_count']} rows · {e['ms']} ms · "
                f"validator: {'passed' if v.get('ok') else 'not passed'}"
                + (f" ({len(v.get('rules_checked', []))} rules)" if v else "")
            )
            if e.get("sql"):
                st.code(e["sql"], language="sql")
            if e.get("params"):
                st.json(e["params"])
            for a in e.get("attempts") or []:
                if a.get("stage") != "ok":
                    st.caption(f"Attempt {a['stage']}: {a.get('feedback', '')}")
            if e.get("rows_preview"):
                st.dataframe(pd.DataFrame(e["rows_preview"]), hide_index=True)

    if r.get("followups"):
        st.caption("Follow-up questions")
        for i, fu in enumerate(r["followups"]):
            label = fu["label"] + (" (keeps the scope)" if fu.get("inherits_scope") else "")
            if st.button(label, key=f"followup_{i}"):
                ss.pending = fu["question"]
                st.rerun()

    st.caption(usage_line(r["usage"]) + f" · request {r['request_id'][:8]}")
