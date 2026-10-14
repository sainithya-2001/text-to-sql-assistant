"""Minimal Streamlit UI: `streamlit run app/streamlit_app.py`."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from text_to_sql.config import Settings
from text_to_sql.db import open_backend
from text_to_sql.llm.client import ClaudeLLM
from text_to_sql.llm.cost import BudgetExceeded, BudgetGuard
from text_to_sql.pipeline import Assistant
from text_to_sql.schema.catalog import Catalog
from text_to_sql.schema.embed import make_embedder
from text_to_sql.schema.glossary import Glossary
from text_to_sql.schema.retriever import SchemaRetriever

MODELS = {"Claude Sonnet 5.5": "claude-sonnet-5-5", "Claude Haiku 5.5": "claude-haiku-5-5"}
EXAMPLES = [
    "Which 5 nations had the most orders placed in 1996?",
    "What was our revenue in each customer region in 1995?",
    "How many line items shipped in 1996 were late shipments?",
    "Who are our biggest customers?",
    "Delete all orders from 1992",
]
SESSION_BUDGET = float(os.environ.get("T2S_UI_BUDGET", "0.25"))

st.set_page_config(page_title="Text-to-SQL Assistant", layout="wide")


@st.cache_resource(show_spinner="Loading database and schema index...")
def load_shared():
    settings = Settings.from_env()
    backend = open_backend(settings)
    catalog = Catalog.from_backend(backend)
    retriever = SchemaRetriever(catalog, make_embedder(settings.embedder))
    glossary = Glossary.load(settings.glossary_path)
    return settings, backend, catalog, retriever, glossary


settings, backend, catalog, retriever, glossary = load_shared()
state = st.session_state
state.setdefault("budget", BudgetGuard(cap_usd=SESSION_BUDGET))
state.setdefault("question", "")
state.setdefault("choices", {})
state.setdefault("answer", None)

with st.sidebar:
    st.header("Settings")
    model_label = st.selectbox("Model", list(MODELS))
    schema_mode = st.radio("Schema given to the model", ["retrieved", "full"], horizontal=True)
    use_glossary = st.toggle("Business glossary", value=True)
    st.caption(f"Backend: **{backend.name}** · {len(catalog.names())} tables")
    b = state.budget
    st.metric("Session spend", f"${b.spent_usd:.4f}", help=f"Hard cap ${b.cap_usd:.2f} per session")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not has_key:
        st.warning("ANTHROPIC_API_KEY is not set. Clarifying questions work; SQL generation needs a key.")

st.title("Text-to-SQL Assistant")
st.caption("Ask about the TPC-H sales data. Queries are validated as read-only SELECTs before they run.")

cols = st.columns(len(EXAMPLES))
for col, ex in zip(cols, EXAMPLES, strict=True):
    if col.button(ex, use_container_width=True):
        state.question, state.choices, state.answer = ex, {}, None

with st.form("ask"):
    question = st.text_input(
        "Question", value=state.question, placeholder="e.g. Top 5 suppliers by revenue in 1996"
    )
    submitted = st.form_submit_button("Ask", type="primary")
if submitted:
    if question != state.question:
        state.choices = {}
    state.question, state.answer = question, None


def run(q: str) -> None:
    llm = ClaudeLLM(MODELS[model_label], effort=settings.effort, budget=state.budget)
    assistant = Assistant(
        backend,
        catalog,
        llm,
        retriever,
        top_k=settings.top_k_tables,
        max_rows=settings.max_rows,
        timeout_s=settings.timeout_s,
        glossary=glossary if use_glossary else None,
    )
    try:
        with st.spinner("Thinking..."):
            state.answer = assistant.ask(q, schema_mode=schema_mode, choices=state.choices)
    except BudgetExceeded as e:
        st.error(f"Session budget reached: {e}")


if state.question and state.answer is None:
    run(state.question)

ans = state.answer
if ans is not None:
    if ans.clarification:
        c = ans.clarification
        st.info(f"**Clarification needed.** {c.question}")
        if c.options:
            pick = st.radio("Meaning", c.options, key=f"pick-{c.term}")
            if st.button("Answer with this meaning"):
                state.choices = {**state.choices, c.term: pick}
                state.answer = None
                st.rerun()
        else:
            st.caption("Rephrase the question with the detail above.")
    elif ans.cannot_answer:
        st.warning(f"Can't answer from this data: {ans.cannot_answer}")
    elif ans.blocked:
        st.error(f"Blocked: {ans.error}")
    elif ans.ok:
        r = ans.result
        st.code(ans.attempts[-1].executed_sql or ans.sql, language="sql")
        st.dataframe(pd.DataFrame(r.rows, columns=r.columns), use_container_width=True, hide_index=True)
        if r.truncated:
            st.caption(f"Showing the first {len(r.rows)} rows.")
    else:
        st.error(ans.error or "Something went wrong.")
        if ans.sql:
            st.code(ans.sql, language="sql")

    with st.expander("How this answer was produced"):
        if ans.glossary_terms:
            st.write("**Glossary terms:** " + ", ".join(ans.glossary_terms))
        if ans.tables:
            st.write(f"**Schema ({ans.schema_mode}):** " + ", ".join(ans.tables))
        if ans.retrieval:
            st.write(
                "**Retrieval scores:** " + ", ".join(f"{t} {s:.2f}" for t, s in ans.retrieval.ranked[:6])
            )
        for i, a in enumerate(ans.attempts, 1):
            st.write(f"Attempt {i}" + (f" failed at {a.stage}: {a.error}" if a.error else ""))
            st.code(a.sql, language="sql")
        u = ans.usage
        st.caption(
            f"{ans.model} · input {u.input_tokens} · cache read {u.cache_read_input_tokens} · "
            f"cache write {u.cache_creation_input_tokens} · output {u.output_tokens} · "
            f"${ans.cost_usd:.5f} · {ans.elapsed_s:.1f}s"
        )
