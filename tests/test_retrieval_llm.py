from __future__ import annotations

import numpy as np
import pytest

from text_to_sql.llm.client import ClaudeLLM, FakeLLM, LLMError
from text_to_sql.llm.cost import BudgetExceeded, BudgetGuard, Usage, cost_usd
from text_to_sql.pipeline import Assistant, extract_sql
from text_to_sql.schema.catalog import Catalog
from text_to_sql.schema.embed import HashEmbedder
from text_to_sql.schema.retriever import SchemaRetriever, build_docs


@pytest.fixture(scope="module")
def catalog(backend):
    return Catalog.from_backend(backend)


@pytest.fixture(scope="module")
def retriever(catalog):
    return SchemaRetriever(catalog, HashEmbedder())


# --- embeddings / retrieval ---


def test_hash_embedder_is_normalized_and_deterministic():
    e = HashEmbedder()
    a = e.embed_documents(["orders by customer", "orders by customer"])
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert np.allclose(a[0], a[1])


def test_docs_cover_every_table_and_column(catalog):
    docs = build_docs(catalog)
    n_cols = sum(len(t.columns) for t in catalog.tables.values())
    assert len(docs) == len(catalog.tables) + n_cols


@pytest.mark.parametrize(
    "question, expected",
    [
        ("How many customers are in each market segment?", {"customer"}),
        ("Which suppliers have the most parts available in stock?", {"partsupp"}),
        ("Average discount on returned line items by ship mode", {"lineitem"}),
        ("Number of nations in each region", {"nation", "region"}),
    ],
)
def test_retrieval_finds_relevant_tables(retriever, question, expected):
    r = retriever.retrieve(question, k=4)
    assert expected <= set(r.tables), r.ranked


def test_retrieval_adds_join_bridges(retriever, catalog):
    r = retriever.retrieve("customers in the EUROPE region", k=2)
    # whatever was chosen, the final set must be FK-connected
    assert catalog.join_path(set(r.tables)) == set(r.tables)


# --- cost / budget ---


def test_cost_math():
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd("claude-haiku-5-5", u) == pytest.approx(0.60)
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(12.00)
    cached = Usage(cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000)
    assert cost_usd("claude-sonnet-5-5", cached) == pytest.approx(0.2 + 2.5)
    with pytest.raises(KeyError):
        cost_usd("unknown-model", u)


def test_budget_guard_blocks_before_overspend():
    g = BudgetGuard(cap_usd=0.02)
    g.check("claude-sonnet-5-5", 3000)  # ~$0.002 + 600 out tokens ~$0.006 -> fine
    g.record("claude-sonnet-5-5", Usage(input_tokens=5000, output_tokens=1500))  # $0.025
    with pytest.raises(BudgetExceeded):
        g.check("claude-sonnet-5-5", 3000)


# --- SQL extraction ---


@pytest.mark.parametrize(
    "raw",
    [
        "SELECT 1;",
        "```sql\nSELECT 1\n```",
        "Here you go:\n```SQL\nSELECT 1;\n```\nThis counts.",
        "  SELECT 1  ",
    ],
)
def test_extract_sql(raw):
    assert extract_sql(raw) == "SELECT 1"


# --- pipeline with a fake model ---


def test_pipeline_uses_only_retrieved_schema(backend, catalog, retriever):
    llm = FakeLLM(["SELECT c_mktsegment, count(*) AS n FROM customer GROUP BY 1 ORDER BY 1"])
    a = Assistant(backend, catalog, llm, retriever, top_k=1)
    ans = a.ask("How many customers are in each market segment?")
    assert ans.ok, ans.error
    assert len(ans.result.rows) == 5
    system = llm.calls[0][0]
    assert "TABLE customer" in system
    assert "TABLE lineitem" not in system  # not retrieved -> not shown


def test_pipeline_full_schema_mode(backend, catalog):
    llm = FakeLLM(["SELECT count(*) FROM region"])
    ans = Assistant(backend, catalog, llm).ask("how many regions", schema_mode="full")
    assert ans.result.rows == [(5,)]
    assert all(f"TABLE {t}" in llm.calls[0][0] for t in catalog.names())


def test_pipeline_cannot_answer(backend, catalog, retriever):
    llm = FakeLLM(["CANNOT_ANSWER: there is no employee table"])
    ans = Assistant(backend, catalog, llm, retriever).ask("What is the CEO's salary?")
    assert ans.sql is None and ans.cannot_answer == "there is no employee table"


def test_pipeline_reports_sql_error(backend, catalog, retriever):
    llm = FakeLLM(["SELECT no_such_col FROM region", "SELECT no_such_col FROM region"])
    ans = Assistant(backend, catalog, llm, retriever).ask("regions")
    assert not ans.ok and "no_such_col" in ans.error


# --- Claude client against a stubbed SDK (no network) ---


class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Resp:
    def __init__(self, stop_reason="end_turn", text="SELECT 1"):
        self.content = [_Block("thinking"), _Block("text", text)]
        self.stop_reason = stop_reason
        self.usage = type(
            "U",
            (),
            dict(
                input_tokens=100, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=900
            ),
        )()


class _StubClient:
    def __init__(self, resp):
        self.resp, self.kwargs = resp, None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


def test_claude_llm_request_shape_and_cost():
    stub = _StubClient(_Resp())
    budget = BudgetGuard(cap_usd=1.0)
    llm = ClaudeLLM("claude-haiku-5-5", client=stub, budget=budget)
    from text_to_sql.llm.client import Message

    r = llm.complete("SYSTEM", [Message("user", "q")], cache=True)
    assert r.text == "SELECT 1"
    kw = stub.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"] == {"effort": "low"}
    assert "temperature" not in kw
    assert r.cost_usd == pytest.approx((100 * 0.10 + 900 * 0.01 + 20 * 0.50) / 1e6)
    assert budget.calls == 1
    llm.complete("SYSTEM", [Message("user", "q")])
    assert "cache_control" not in stub.kwargs["system"][0]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_claude_llm_bad_stop_reasons(stop):
    llm = ClaudeLLM("claude-haiku-5-5", client=_StubClient(_Resp(stop_reason=stop)))
    from text_to_sql.llm.client import Message

    with pytest.raises(LLMError):
        llm.complete("S", [Message("user", "q")])


def test_keyword_half_catches_named_entities(retriever):
    # Regression: the smoke test question where pure vector search ranked `orders` 5th.
    r = retriever.retrieve("Which 5 nations had the most orders placed in 1996?", k=4)
    assert {"orders", "nation"} <= set(r.tables), r.ranked


def test_stemming():
    from text_to_sql.schema.retriever import keywords

    assert {"order", "country", "supplier"} <= keywords("orders by countries and suppliers")


def test_budget_projection_learns_token_ratio_and_max_output():
    g = BudgetGuard(cap_usd=10)
    before = g.projected("claude-sonnet-5-5", 3000)
    # observed: 3000 chars -> 1500 tokens (0.5/char, above the 1/3 default) and a long 2000-token output
    g.record("claude-sonnet-5-5", Usage(input_tokens=1500, output_tokens=2000), prompt_chars=3000)
    after = g.projected("claude-sonnet-5-5", 3000)
    assert after > before
    assert after >= cost_usd("claude-sonnet-5-5", Usage(input_tokens=1500, output_tokens=2000))


def test_missing_credentials_become_llm_error():
    class NoAuth:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            # what anthropic 1.x raises when no api key / token / profile is available
            raise TypeError('"Could not resolve authentication method. Expected one of api_key, ..."')

    from text_to_sql.llm.client import Message

    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        ClaudeLLM("claude-haiku-5-5", client=NoAuth()).complete("S", [Message("user", "q")])
