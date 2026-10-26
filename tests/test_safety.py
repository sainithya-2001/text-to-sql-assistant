from __future__ import annotations

import pytest

from text_to_sql.db.duckdb_backend import TPCH_TABLES
from text_to_sql.llm.client import FakeLLM
from text_to_sql.pipeline import Assistant
from text_to_sql.safety.guard import GuardError, SqlGuard
from text_to_sql.schema.catalog import Catalog


@pytest.fixture(scope="module")
def guard():
    return SqlGuard(set(TPCH_TABLES), "duckdb", max_rows=200)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM region",
        "SELECT * FROM region;",
        "FROM region",
        "WITH x AS (SELECT * FROM region) SELECT * FROM x",
        "SELECT r_name FROM region UNION ALL SELECT n_name FROM nation",
        "SELECT * FROM (SELECT * FROM region) s",
        "SELECT * FROM main.region",
        "SELECT n_name, count(*) FROM nation n JOIN region r ON n.n_regionkey = r.r_regionkey GROUP BY 1",
        "SELECT EXTRACT(YEAR FROM o_orderdate) AS y, sum(o_totalprice) FROM orders GROUP BY 1",
        "SELECT o_orderdate + INTERVAL 3 MONTH, date_trunc('month', o_orderdate) FROM orders",
        "SELECT c_name, rank() OVER (ORDER BY c_acctbal DESC) AS r FROM customer",
        "SELECT count(*) FROM orders WHERE o_orderdate < current_date",
        "WITH a AS (SELECT 1 AS x), b AS (SELECT * FROM a) SELECT * FROM b",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT * FROM n",
        "WITH t AS (SELECT 1 AS x) SELECT * FROM region WHERE EXISTS (SELECT * FROM t)",
        "SELECT * FROM (SELECT o_orderpriority, o_orderstatus FROM orders) "
        "PIVOT (count(*) FOR o_orderstatus IN ('F', 'O', 'P'))",
    ],
)
def test_allowed(guard, sql):
    guard.check(sql)


@pytest.mark.parametrize(
    "sql, retryable",
    [
        ("DELETE FROM region", False),
        ("UPDATE region SET r_name = 'x'", False),
        ("INSERT INTO region SELECT * FROM region", False),
        ("DROP TABLE region", False),
        ("CREATE TABLE t AS SELECT * FROM region", False),
        ("WITH d AS (DELETE FROM region RETURNING *) SELECT * FROM d", False),
        ("SELECT * INTO t2 FROM region", False),
        ("PRAGMA database_list", False),
        ("ATTACH 'x.db' AS x", False),
        ("CALL dbgen(sf=1)", False),
        ("COPY region TO 'out.csv'", False),
        ("SET threads = 1", False),
        ("DESCRIBE region", False),
        ("SHOW TABLES", False),
        ("EXPLAIN SELECT 1", False),
        ("VALUES (1)", False),
        ("SELECT * FROM read_csv('x.csv')", False),
        ("SELECT * FROM duckdb_settings()", False),
        ("SELECT * FROM generate_series(1, 10)", False),
        ("SELECT * FROM query('select 1')", False),
        ("SELECT * FROM information_schema.tables", False),
        ("SELECT * FROM x.region", False),
        ("SELECT getenv('HOME')", False),
        ("SELECT current_setting('threads')", False),
        ("SELECT version()", False),
        ("SELECT current_user", False),
        ("SELECT * FROM region WHERE r_regionkey IN (SELECT 1 FROM pragma_table_info('nation'))", False),
        # a disallowed operation in any statement is a policy block, even with several statements
        ("SELECT * FROM nation; DROP TABLE nation", False),
        ("SELECT * FROM nation; DELETE FROM orders", False),
        ("DROP TABLE nation; SELECT * FROM nation", False),
        ("SELECT 1; SELECT getenv('HOME')", False),
        ("SELECT 1; SELECT * FROM read_csv('x.csv')", False),
        ("SELECT getenv('HOME') FROM employees", False),  # policy wins over a fixable unknown table
        # CTE scope confusion (safety_eval/RESULTS.md): a CTE name only counts where it is in scope
        ('SELECT * FROM (WITH "/etc/passwd" AS (SELECT 1) SELECT 1) s, "/etc/passwd"', False),
        ("SELECT * FROM duckdb_databases WHERE EXISTS (WITH duckdb_databases AS (SELECT 1) SELECT 1)", False),
        ('WITH x AS (SELECT * FROM "/etc/passwd"), "/etc/passwd" AS (SELECT 1) SELECT * FROM x', False),
        # DuckDB plans this as CREATE TYPE + SELECT although sqlglot reads a SELECT
        ("SELECT * FROM (PIVOT region ON r_name)", False),
        # fixable mistakes go back to the model once
        ("SELECT 1; SELECT 2", True),
        ("SELECT * FROM nation; SELECT * FROM region", True),
        ("SELEC 1", True),
        ("SELECT 'unterminated FROM region", True),  # TokenError, not ParseError: crashed a paid eval run
        ("SELECT * FROM employees", True),
        ("SELECT * FROM 'file.parquet'", True),
        ("", True),
    ],
)
def test_rejected(guard, sql, retryable):
    with pytest.raises(GuardError) as ei:
        guard.check(sql)
    assert ei.value.retryable is retryable


def test_limit_injected_only_when_missing(guard):
    g = guard.check("SELECT * FROM nation")
    assert g.limit_added and g.sql.endswith("LIMIT 201")
    g = guard.check("SELECT * FROM nation LIMIT 5")
    assert not g.limit_added and g.sql == "SELECT * FROM nation LIMIT 5"


def test_tables_reported(guard):
    g = guard.check("WITH t AS (SELECT * FROM orders) SELECT * FROM t JOIN customer ON o_custkey = c_custkey")
    assert g.tables == {"orders", "customer"}


# --- self-correction in the pipeline ---


@pytest.fixture(scope="module")
def catalog(backend):
    return Catalog.from_backend(backend)


def test_retry_fixes_bad_column(backend, catalog):
    llm = FakeLLM(["SELECT r_nam FROM region", "SELECT r_name FROM region ORDER BY 1"])
    ans = Assistant(backend, catalog, llm).ask("list regions", schema_mode="full")
    assert ans.ok and ans.retried
    assert ans.attempts[0].stage == "execute" and "r_nam" in ans.attempts[0].error
    # the repair turn carries the failed SQL and the DB error
    repair = llm.calls[1][1][-1].content
    assert "SELECT r_nam FROM region" in repair and "r_nam" in repair
    assert [m.role for m in llm.calls[1][1]] == ["user", "assistant", "user"]


def test_retry_fixes_unknown_table(backend, catalog):
    llm = FakeLLM(["SELECT * FROM regions", "SELECT * FROM region"])
    ans = Assistant(backend, catalog, llm).ask("regions", schema_mode="full")
    assert ans.ok and ans.attempts[0].stage == "guard"


def test_only_one_retry(backend, catalog):
    llm = FakeLLM(["SELECT a FROM region", "SELECT b FROM region", "SELECT r_name FROM region"])
    ans = Assistant(backend, catalog, llm).ask("regions", schema_mode="full")
    assert not ans.ok and len(ans.attempts) == 2 and len(llm.calls) == 2


def test_policy_violation_not_retried(backend, catalog):
    llm = FakeLLM(["DELETE FROM orders", "SELECT 1"])
    ans = Assistant(backend, catalog, llm).ask("delete all orders", schema_mode="full")
    assert ans.blocked and not ans.ok and len(llm.calls) == 1
    assert "DELETE" in ans.error


def test_timeout_triggers_retry(backend, catalog):
    llm = FakeLLM(
        ["SELECT count(*) FROM lineitem a, lineitem b, lineitem c", "SELECT count(*) FROM lineitem"]
    )
    a = Assistant(backend, catalog, llm, timeout_s=0.3)
    ans = a.ask("count line items", schema_mode="full")
    assert ans.ok and "timeout" in ans.attempts[0].error
    assert ans.result.rows[0][0] > 50_000


def test_row_cap_applied_end_to_end(backend, catalog):
    llm = FakeLLM(["SELECT * FROM customer"])
    ans = Assistant(backend, catalog, llm, max_rows=50).ask("all customers", schema_mode="full")
    assert len(ans.result.rows) == 50 and ans.result.truncated
    assert ans.attempts[0].executed_sql.endswith("LIMIT 51")
