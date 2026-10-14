"""The assistant: question -> retrieved schema -> SQL -> guard -> rows, with one self-correction retry."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .db.base import Backend, QueryError, QueryResult
from .llm.client import LLM, LLMError, Message
from .llm.cost import Usage
from .llm.prompts import CANNOT_ANSWER, CLARIFY, repair_prompt, system_prompt, user_message
from .safety.guard import GuardError, SqlGuard
from .schema.catalog import Catalog
from .schema.glossary import Clarification, Glossary
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
    sql: str  # as written by the model
    executed_sql: str | None = None  # after the guard (e.g. LIMIT added)
    error: str | None = None
    stage: str = ""  # "guard" | "execute" | "" (success)


@dataclass
class Answer:
    question: str
    sql: str | None
    result: QueryResult | None
    error: str | None = None
    blocked: bool = False  # refused by policy (writes, system access); not retried
    cannot_answer: str | None = None
    clarification: Clarification | None = None  # the assistant needs the user to pick a meaning
    glossary_terms: list[str] = field(default_factory=list)
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

    @property
    def retried(self) -> bool:
        return len(self.attempts) > 1


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
        max_retries: int = 1,
        glossary: Glossary | None = None,
    ):
        self.backend = backend
        self.catalog = catalog
        self.llm = llm
        self.retriever = retriever
        self.top_k = top_k
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.glossary = glossary
        # The guard allows every catalog table, not just the retrieved ones: a real table the model
        # knows about is still a valid query.
        self.guard = SqlGuard(set(catalog.names()), backend.dialect, max_rows=max_rows)

    def select_schema(self, question: str, schema_mode: str) -> tuple[list[str], Retrieval | None]:
        if schema_mode == "full":
            return self.catalog.names(), None
        if schema_mode != "retrieved":
            raise ValueError(f"schema_mode must be 'full' or 'retrieved', not {schema_mode!r}")
        if self.retriever is None:
            raise ValueError("schema_mode='retrieved' needs a retriever")
        r = self.retriever.retrieve(question, self.top_k)
        return r.tables, r

    def ask(
        self, question: str, *, schema_mode: str = "retrieved", choices: dict[str, str] | None = None
    ) -> Answer:
        """Answer `question`. `choices` maps an ambiguous glossary term to the meaning the user picked."""
        start = time.perf_counter()
        ans = Answer(question=question, sql=None, result=None, schema_mode=schema_mode, model=self.llm.model)

        glossary_text = ""
        extra_tables: set[str] = set()
        if self.glossary:
            match = self.glossary.match(question, choices)
            ans.clarification = match.clarification()
            if ans.clarification:  # ask before spending a model call on a guess
                ans.elapsed_s = time.perf_counter() - start
                return ans
            ans.glossary_terms = [r.term for r in match.resolved]
            glossary_text = match.render()
            extra_tables = match.tables & set(self.catalog.names())

        tables, retrieval = self.select_schema(question, schema_mode)
        if extra_tables:
            tables = sorted(self.catalog.join_path(set(tables) | extra_tables))
        ans.tables, ans.retrieval = tables, retrieval

        system = system_prompt(
            self.catalog.render(tables),
            self.backend.dialect,
            allow_clarify=self.glossary is not None,
        )
        messages = [Message("user", user_message(question, glossary_text))]
        try:
            self._run(ans, system, messages, cache=schema_mode == "full")
        finally:
            ans.elapsed_s = time.perf_counter() - start
        return ans

    def _run(self, ans: Answer, system: str, messages: list[Message], *, cache: bool) -> None:
        for attempt_no in range(self.max_retries + 1):
            try:
                resp = self.llm.complete(system, messages, cache=cache)
            except LLMError as e:
                ans.error = str(e)
                return
            ans.usage = ans.usage + resp.usage
            ans.cost_usd += resp.cost_usd

            text = resp.text.strip()
            if text.startswith(CLARIFY):
                ans.clarification = Clarification(text[len(CLARIFY) :].lstrip(": ").strip())
                ans.error = None
                return
            if text.startswith(CANNOT_ANSWER):
                ans.cannot_answer = text[len(CANNOT_ANSWER) :].lstrip(": ").strip() or "not answerable"
                ans.error = None
                return

            sql = extract_sql(text)
            attempt = Attempt(sql)
            ans.attempts.append(attempt)
            ans.sql = sql
            try:
                guarded = self.guard.check(sql)
                attempt.executed_sql = guarded.sql
                ans.result = self.backend.execute(
                    guarded.sql, max_rows=self.max_rows, timeout_s=self.timeout_s
                )
                ans.error = None
                return
            except GuardError as e:
                attempt.error, attempt.stage = str(e), "guard"
                ans.error = f"rejected: {e}"
                if not e.retryable:
                    ans.blocked = True
                    return
            except QueryError as e:
                attempt.error, attempt.stage = str(e), "execute"
                ans.error = str(e)

            if attempt_no < self.max_retries:
                messages = messages + [
                    Message("assistant", text),
                    Message("user", repair_prompt(ans.question, sql, attempt.error)),
                ]
