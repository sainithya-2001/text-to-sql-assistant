"""Backend interface shared by DuckDB and Snowflake."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class QueryError(Exception):
    """The database rejected or failed to run a query. The message is safe to show the LLM."""


class QueryTimeout(QueryError):
    pass


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    row_count: int | None = None


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False
    elapsed_s: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class Backend(Protocol):
    name: str
    dialect: str  # sqlglot dialect name

    def tables(self) -> list[Table]: ...

    def execute(self, sql: str, *, max_rows: int, timeout_s: float) -> QueryResult: ...

    def close(self) -> None: ...
