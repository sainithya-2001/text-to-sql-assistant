"""The assistant: question -> retrieved schema -> SQL -> rows."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .db.base import Backend, QueryError, QueryResult
from .llm.client import LLM, LLMError, Message
from .llm.cost import Usage
from .llm.prompts import CANNOT_ANSWER, system_prompt
from .schema.catalog import Catalog
from .schema.retriever import Retrieval, SchemaRetriever

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def extract_sql(text: str) -> str:
    """Strip markdown fences, surrounding prose markers and trailing semicolons."""
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
        t = m.group(1) if m else _FENCE.sub("", t)
    return t.strip().rstrip(";").strip()


@dataclass
class Attempt:
    sql: str
    error: str | None = None


@dataclass
class Answer:
    question: str
    sql: str | None
    result: QueryResult | None
    error: str | None = None
    cannot_answer: str | None = None
    schema_mode: str = "retrieved"
    tables: list[str] = field(default_factory=list)
    retrieval: Retrieval | None = None
    attempts: list[Attempt] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    model: str = ""
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.result is not None and self.error is None


class Assistant:
    def __init__(
        self,
        backend: Backend,
        catalog: Catalog,
        llm: LLM,
        retriever: SchemaRetriever | None = None,
        *,
        top_k: int = 4,
        max_rows: int = 200,
        timeout_s: float = 15.0,
    ):
        self.backend = backend
        self.catalog = catalog
        self.llm = llm
        self.retriever = retriever
        self.top_k = top_k
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def select_schema(self, question: str, schema_mode: str) -> tuple[list[str], Retrieval | None]:
        if schema_mode == "full":
            return self.catalog.names(), None
        if schema_mode != "retrieved":
            raise ValueError(f"schema_mode must be 'full' or 'retrieved', not {schema_mode!r}")
        if self.retriever is None:
            raise ValueError("schema_mode='retrieved' needs a retriever")
        r = self.retriever.retrieve(question, self.top_k)
        return r.tables, r

    def ask(self, question: str, *, schema_mode: str = "retrieved") -> Answer:
        start = time.perf_counter()
        tables, retrieval = self.select_schema(question, schema_mode)
        ans = Answer(
            question=question,
            sql=None,
            result=None,
            schema_mode=schema_mode,
            tables=tables,
            retrieval=retrieval,
            model=self.llm.model,
        )
        system = system_prompt(self.catalog.render(tables), self.backend.dialect)
        messages = [Message("user", question)]
        try:
            resp = self.llm.complete(system, messages, cache=schema_mode == "full")
        except LLMError as e:
            ans.error = str(e)
            ans.elapsed_s = time.perf_counter() - start
            return ans
        ans.usage = ans.usage + resp.usage
        ans.cost_usd += resp.cost_usd

        text = resp.text.strip()
        if text.startswith(CANNOT_ANSWER):
            ans.cannot_answer = text[len(CANNOT_ANSWER) :].lstrip(": ").strip() or "not answerable"
            ans.elapsed_s = time.perf_counter() - start
            return ans

        sql = extract_sql(text)
        ans.sql = sql
        try:
            ans.result = self.backend.execute(sql, max_rows=self.max_rows, timeout_s=self.timeout_s)
            ans.attempts.append(Attempt(sql))
        except QueryError as e:
            ans.error = str(e)
            ans.attempts.append(Attempt(sql, str(e)))
        ans.elapsed_s = time.perf_counter() - start
        return ans
