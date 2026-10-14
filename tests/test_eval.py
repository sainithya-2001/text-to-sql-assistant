from __future__ import annotations

import datetime as dt
import decimal
from collections import Counter

import pytest

from text_to_sql.config import PROJECT_ROOT
from text_to_sql.eval_runner import Config, run_eval, summarize
from text_to_sql.evaluation import gold_tables, load_questions, results_match, topn_tie_free
from text_to_sql.llm.client import FakeLLM
from text_to_sql.llm.cost import BudgetExceeded, BudgetGuard, Usage
from text_to_sql.schema.catalog import Catalog
from text_to_sql.schema.embed import HashEmbedder
from text_to_sql.schema.retriever import SchemaRetriever

QUESTIONS = load_questions(PROJECT_ROOT / "eval" / "questions.yaml")


def test_question_set_shape():
    assert len(QUESTIONS) == 40
    assert Counter(q.difficulty for q in QUESTIONS) == {"easy": 14, "medium": 14, "hard": 12}


@pytest.mark.parametrize("item", QUESTIONS, ids=lambda i: i.id)
def test_gold_sql_runs_and_is_well_defined(backend, item):
    res = backend.execute(item.gold_sql, max_rows=10_000, timeout_s=30)
    assert res.rows, "gold query returned no rows"
    assert topn_tie_free(backend, item), "ties make the expected answer ambiguous"
    assert gold_tables(item.gold_sql) <= {t.name for t in backend.tables()}


# --- comparison semantics ---


def test_match_ignores_column_order_and_names_and_types():
    gold = [("ASIA", decimal.Decimal("10.50")), ("EUROPE", decimal.Decimal("3.00"))]
    pred = [(3.0, "EUROPE"), (10.5, "ASIA")]
    assert results_match(pred, gold)


def test_match_rounds_floats():
    assert results_match([(4621.509006,)], [(4621.51,)])
    assert results_match([(1035681023.49,)], [(decimal.Decimal("1035681023.4900"),)])
    assert not results_match([(4621.6,)], [(4621.51,)])


def test_match_dates_and_nulls():
    assert results_match([(dt.date(1995, 3, 1), None)], [("1995-03-01", None)])


def test_match_respects_order_when_required():
    a, b = [("x",), ("y",)], [("y",), ("x",)]
    assert results_match(a, b)
    assert not results_match(a, b, order_matters=True)


def test_match_requires_same_shape():
    assert not results_match([("x", 1)], [("x",)])
    assert not results_match([("x",)], [("x",), ("x",)])
    assert not results_match([("x",), ("x",)], [("x",), ("y",)])


# --- runner ---


@pytest.fixture(scope="module")
def catalog(backend):
    return Catalog.from_backend(backend)


def test_runner_with_gold_answers_scores_100(backend, catalog):
    by_q = {q.question: q.gold_sql for q in QUESTIONS}
    items = QUESTIONS[:6]

    def make_llm(model, budget):
        return FakeLLM(lambda system, msgs: by_q[msgs[0].content], model=model)

    run = run_eval(
        items,
        [Config("fake", "full"), Config("fake", "retrieved")],
        backend=backend,
        catalog=catalog,
        retriever=SchemaRetriever(catalog, HashEmbedder()),
        make_llm=make_llm,
        budget=BudgetGuard(1.0),
        progress=lambda s: None,
    )
    for rs in run.items.values():
        assert all(r.correct for r in rs), [(r.id, r.error) for r in rs if not r.correct]
    md = summarize(run.to_json())
    assert "fake/full" in md and "100%" in md


def test_runner_stops_at_budget(backend, catalog):
    class Pricey(FakeLLM):
        def complete(self, system, messages, *, cache=False):
            # 300K chars -> ~100K tokens, consistent with the guard's chars/3 estimate
            self.budget.check("claude-sonnet-5-5", 300_000)
            r = super().complete(system, messages, cache=cache)
            self.budget.record("claude-sonnet-5-5", Usage(input_tokens=100_000, output_tokens=1000), 300_000)
            return r

    def make_llm(model, budget):
        llm = Pricey(lambda s, m: "SELECT 1", model=model)
        llm.budget = budget
        return llm

    budget = BudgetGuard(cap_usd=0.5)
    run = run_eval(
        QUESTIONS[:10],
        [Config("fake", "full")],
        backend=backend,
        catalog=catalog,
        retriever=None,
        make_llm=make_llm,
        budget=budget,
        progress=lambda s: None,
    )
    assert run.stopped_reason and "budget cap" in run.stopped_reason
    assert budget.spent_usd <= 0.5
    assert 0 < len(run.items["fake/full"]) < 10
    with pytest.raises(BudgetExceeded):
        budget.check("claude-sonnet-5-5", 300_000)
