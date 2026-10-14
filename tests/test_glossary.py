from __future__ import annotations

import pytest

from text_to_sql.config import PROJECT_ROOT
from text_to_sql.eval_runner import Config, run_eval
from text_to_sql.evaluation import load_questions, topn_tie_free
from text_to_sql.llm.client import FakeLLM
from text_to_sql.llm.cost import BudgetGuard
from text_to_sql.pipeline import Assistant
from text_to_sql.schema.catalog import Catalog
from text_to_sql.schema.embed import HashEmbedder
from text_to_sql.schema.glossary import Glossary
from text_to_sql.schema.retriever import SchemaRetriever

GLOSSARY = Glossary.load(PROJECT_ROOT / "glossary.yaml")
GLOSSARY_QS = load_questions(PROJECT_ROOT / "eval" / "glossary_questions.yaml")
AMBIGUOUS_QS = load_questions(PROJECT_ROOT / "eval" / "ambiguous_questions.yaml")
CORE_QS = load_questions(PROJECT_ROOT / "eval" / "questions.yaml")


def terms(q, **kw):
    return [r.term for r in GLOSSARY.match(q, **kw).resolved]


# --- glossary file ---


def test_glossary_tables_exist(backend):
    real = {t.name for t in backend.tables()}
    for t in GLOSSARY.terms:
        assert set(t.tables) <= real, t.term
        for i in t.interpretations:
            assert set(i.tables) <= real, (t.term, i.label)
        assert t.ambiguous == bool(t.clarify), f"{t.term}: ambiguous terms need a clarify question"


# --- matching ---


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What was our revenue by region?", ["revenue"]),
        ("Total sales in 1996", ["revenue"]),
        ("gross revenue for 1996", ["gross revenue"]),  # longer phrase wins over "revenue"
        ("How many deliveries arrived late?", ["late shipment"]),
        ("late shipments by mode", ["late shipment"]),
        ("How many line items were returned?", ["returned item"]),
        ("Return the nation name and count", []),  # the verb "return" is not a business term
        ("How many customers are there?", []),
    ],
)
def test_match(question, expected):
    assert terms(question) == expected


def test_ambiguous_term_needs_clarification():
    m = GLOSSARY.match("Who are our biggest customers?")
    c = m.clarification()
    assert c and c.term == "biggest customers" and "by revenue" in c.options


def test_numbers_do_not_block_phrases():
    assert GLOSSARY.match("Who are our top 5 customers?").clarification() is not None


@pytest.mark.parametrize(
    "question, label",
    [
        ("top 5 customers by revenue", "by revenue"),
        ("top 10 customers by account balance", "by account balance"),
        ("large orders by value in 1995", "by value (total price above $300,000)"),
        ("best-selling parts by units sold", "by units sold"),
    ],
)
def test_cue_resolves_ambiguity(question, label):
    m = GLOSSARY.match(question)
    assert m.clarification() is None
    assert any(r.via == label for r in m.resolved)


def test_explicit_choice_resolves_ambiguity():
    m = GLOSSARY.match("Who are our biggest customers?", {"biggest customers": "by number of orders"})
    assert m.clarification() is None and m.resolved[0].via == "by number of orders"
    with pytest.raises(ValueError):
        GLOSSARY.match("Who are our biggest customers?", {"biggest customers": "by vibes"})


# --- pipeline ---


@pytest.fixture(scope="module")
def catalog(backend):
    return Catalog.from_backend(backend)


@pytest.fixture(scope="module")
def retriever(catalog):
    return SchemaRetriever(catalog, HashEmbedder())


def test_clarification_happens_before_any_model_call(backend, catalog, retriever):
    llm = FakeLLM([])
    ans = Assistant(backend, catalog, llm, retriever, glossary=GLOSSARY).ask("Who are our biggest customers?")
    assert ans.clarification and not llm.calls and ans.cost_usd == 0


def test_glossary_adds_tables_and_definitions(backend, catalog, retriever):
    llm = FakeLLM(["SELECT 1"])
    a = Assistant(backend, catalog, llm, retriever, top_k=1, glossary=GLOSSARY)
    ans = a.ask("What was our revenue in each customer region in 1995?")
    assert {"lineitem", "orders", "customer", "nation", "region"} <= set(ans.tables)
    system, msgs = llm.calls[0]
    assert "SUM(l_extendedprice * (1 - l_discount))" in msgs[0].content
    assert "SUM(l_extendedprice" not in system  # definitions live in the user turn


def test_full_schema_system_prompt_is_stable_with_glossary(backend, catalog):
    llm = FakeLLM(lambda s, m: "SELECT 1")
    a = Assistant(backend, catalog, llm, glossary=GLOSSARY)
    a.ask("revenue by region", schema_mode="full")
    a.ask("how many late shipments", schema_mode="full")
    assert llm.calls[0][0] == llm.calls[1][0]  # byte-identical -> cacheable


def test_model_clarify_reply(backend, catalog, retriever):
    llm = FakeLLM(["CLARIFY: Best by revenue, growth, or order count?"])
    ans = Assistant(backend, catalog, llm, retriever, glossary=GLOSSARY).ask(
        "Which region is performing best?"
    )
    assert ans.clarification.question == "Best by revenue, growth, or order count?"
    assert not ans.ok and ans.error is None


def test_without_glossary_prompt_is_unchanged(backend, catalog, retriever):
    llm = FakeLLM(["SELECT 1"])
    Assistant(backend, catalog, llm, retriever).ask("What was our revenue?")
    system, msgs = llm.calls[0]
    assert "CLARIFY" not in system and msgs[0].content == "What was our revenue?"


# --- eval sets ---


@pytest.mark.parametrize("item", GLOSSARY_QS + AMBIGUOUS_QS, ids=lambda i: i.id)
def test_glossary_eval_items(backend, item):
    m = GLOSSARY.match(item.question)
    if item.expect_clarification:
        assert not item.gold_sql
        if item.id != "a05":  # a05 is outside the glossary on purpose (tests the model's CLARIFY)
            assert m.clarification() is not None
        return
    assert m.clarification() is None
    if item.category == "glossary":
        assert m.resolved, "glossary questions must use at least one glossary term"
    assert backend.execute(item.gold_sql, max_rows=10_000, timeout_s=30).rows
    assert topn_tie_free(backend, item)


def test_core_questions_never_trigger_glossary_clarification():
    assert [q.id for q in CORE_QS if GLOSSARY.match(q.question).clarification()] == []


def test_runner_scores_clarification(backend, catalog, retriever):
    by_q = {q.question: q.gold_sql for q in AMBIGUOUS_QS}
    run = run_eval(
        AMBIGUOUS_QS,
        [Config("fake", "retrieved", glossary=True)],
        backend=backend,
        catalog=catalog,
        retriever=retriever,
        make_llm=lambda model, b: FakeLLM(
            lambda s, m: by_q.get(m[0].content.split("Question: ")[-1]) or "CLARIFY: which metric?",
            model=model,
        ),
        budget=BudgetGuard(1.0),
        progress=lambda s: None,
        glossary=GLOSSARY,
    )
    rs = run.items["fake/retrieved+glossary"]
    assert all(r.correct for r in rs), [(r.id, r.error, r.clarification) for r in rs if not r.correct]
