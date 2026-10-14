from __future__ import annotations

from ..config import Settings
from .base import Backend, Column, QueryError, QueryResult, QueryTimeout, Table
from .duckdb_backend import DuckDBBackend, build_tpch

__all__ = [
    "Backend",
    "Column",
    "QueryError",
    "QueryResult",
    "QueryTimeout",
    "Table",
    "DuckDBBackend",
    "build_tpch",
    "open_backend",
]


def open_backend(settings: Settings) -> Backend:
    if settings.backend == "snowflake":
        from .snowflake_backend import SnowflakeBackend

        return SnowflakeBackend(settings.snowflake)
    if settings.backend != "duckdb":
        raise ValueError(f"unknown backend {settings.backend!r}")
    build_tpch(settings.duckdb_path, settings.tpch_scale)
    return DuckDBBackend(settings.duckdb_path)
