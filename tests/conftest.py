from __future__ import annotations

import os
from pathlib import Path

import pytest

from text_to_sql.db import DuckDBBackend, build_tpch

# Tests never talk to Anthropic or Snowflake, and never read the developer's .env.
for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PASSWORD"):
    os.environ.pop(var, None)
os.environ["T2S_NO_DOTENV"] = "1"
os.environ["T2S_EMBEDDER"] = "hash"


@pytest.fixture(scope="session")
def tpch_path(tmp_path_factory) -> Path:
    return build_tpch(tmp_path_factory.mktemp("db") / "tpch.duckdb", scale=0.01)


@pytest.fixture(scope="session")
def backend(tpch_path):
    b = DuckDBBackend(tpch_path)
    yield b
    b.close()
