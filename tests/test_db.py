from __future__ import annotations

import pytest

from text_to_sql.config import Settings
from text_to_sql.db import QueryError, QueryTimeout
from text_to_sql.db.duckdb_backend import TPCH_TABLES
from text_to_sql.schema import descriptions
from text_to_sql.schema.catalog import Catalog


def test_tpch_tables_generated(backend):
    tables = {t.name: t for t in backend.tables()}
    assert set(tables) == set(TPCH_TABLES)
    assert tables["region"].row_count == 5
    assert tables["nation"].row_count == 25
    assert tables["lineitem"].row_count > 50_000


def test_execute_returns_rows(backend):
    res = backend.execute("SELECT r_name FROM region ORDER BY r_name", max_rows=10, timeout_s=5)
    assert res.columns == ["r_name"]
    assert [r[0] for r in res.rows][0] == "AFRICA"
    assert not res.truncated


def test_row_cap_truncates(backend):
    res = backend.execute("SELECT * FROM nation", max_rows=10, timeout_s=5)
    assert len(res.rows) == 10
    assert res.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE x (a INT)",
        "DELETE FROM region",
        "INSERT INTO region VALUES (9, 'X', 'y')",
        "SELECT * FROM read_csv('pyproject.toml')",
        "COPY region TO 'out.csv'",
        "ATTACH 'other.duckdb' AS other",
        "SET enable_external_access = true",
        "INSTALL httpfs",
    ],
)
def test_connection_is_locked_down(backend, sql):
    with pytest.raises(QueryError):
        backend.execute(sql, max_rows=10, timeout_s=5)


def test_timeout_interrupts_long_query(backend):
    with pytest.raises(QueryTimeout):
        backend.execute("SELECT count(*) FROM lineitem a, lineitem b, lineitem c", max_rows=10, timeout_s=0.3)
    # connection still usable afterwards
    assert backend.execute("SELECT 1", max_rows=1, timeout_s=5).rows == [(1,)]


def test_bad_sql_is_query_error(backend):
    with pytest.raises(QueryError, match="no_such_table"):
        backend.execute("SELECT * FROM no_such_table", max_rows=1, timeout_s=5)


def test_every_column_has_a_description(backend):
    for t in backend.tables():
        assert t.name in descriptions.TABLES
        missing = {c.name for c in t.columns} - set(descriptions.COLUMNS[t.name])
        assert not missing, f"{t.name}: undocumented columns {missing}"


def test_foreign_keys_reference_real_columns(backend):
    cols = {(t.name, c.name) for t in backend.tables() for c in t.columns}
    for t, c, rt, rc in descriptions.FOREIGN_KEYS:
        assert (t, c) in cols and (rt, rc) in cols


def test_catalog_render_and_join_path(backend):
    cat = Catalog.from_backend(backend)
    text = cat.render(["orders", "customer"])
    assert "TABLE customer" in text and "TABLE orders" in text
    assert "orders.o_custkey -> customer.c_custkey" in text
    # region <-> customer needs nation as a bridge
    assert cat.join_path({"region", "customer"}) == {"region", "nation", "customer"}
    # part <-> customer goes through lineitem and orders
    assert {"lineitem", "orders"} <= cat.join_path({"part", "customer"})


def test_settings_snowflake_off_without_keys(monkeypatch):
    for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(load_dotenv_file=False)
    assert s.backend == "duckdb" and not s.snowflake_available
    monkeypatch.setenv("T2S_BACKEND", "snowflake")
    with pytest.raises(ValueError, match="SNOWFLAKE_ACCOUNT"):
        Settings.from_env(load_dotenv_file=False)


def test_join_path_is_deterministic_across_hash_seeds(tpch_path):
    import os
    import subprocess
    import sys

    code = (
        "from text_to_sql.db import DuckDBBackend; from text_to_sql.schema.catalog import Catalog;"
        f"c = Catalog.from_backend(DuckDBBackend(r'{tpch_path}'));"
        "print(sorted(c.join_path({'lineitem', 'region'})))"
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout
        for seed in range(6)
    }
    assert len(outs) == 1, outs
