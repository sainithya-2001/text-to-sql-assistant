from __future__ import annotations

import os
from pathlib import Path

import pytest

from text_to_sql.db import DuckDBBackend, build_tpch

# Tests never talk to Anthropic or Snowflake.
for var in ("ANTHROPIC_API_KEY", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PASSWORD"):
    os.environ.pop(var, None)


@pytest.fixture(scope="session")
def tpch_path(tmp_path_factory) -> Path:
    return build_tpch(tmp_path_factory.mktemp("db") / "tpch.duckdb", scale=0.01)


@pytest.fixture(scope="session")
def backend(tpch_path):
    b = DuckDBBackend(tpch_path)
    yield b
    b.close()
