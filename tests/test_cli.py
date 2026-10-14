from __future__ import annotations

import io

import pytest

from text_to_sql.cli import main


@pytest.fixture
def db_env(monkeypatch, tpch_path):
    monkeypatch.setenv("T2S_DUCKDB_PATH", str(tpch_path))


def test_check_sql_allowed_adds_limit(db_env, capsys):
    assert main(["check-sql", "SELECT n_name FROM nation"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ALLOWED: tables nation")
    assert "LIMIT 201" in out


def test_check_sql_allowed_keeps_existing_limit(db_env, capsys):
    sql = "SELECT COUNT(*) FROM orders o JOIN customer c ON o.o_custkey = c.c_custkey"
    assert main(["check-sql", sql]) == 0
    out = capsys.readouterr().out
    assert "customer, orders" in out and "LIMIT added" in out
    assert main(["check-sql", "SELECT * FROM region LIMIT 3"]) == 0
    assert "LIMIT added" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("DELETE FROM orders", "BLOCKED (policy, never retried): only SELECT"),
        ("SELECT * FROM read_csv('/etc/passwd')", "BLOCKED (policy, never retried): table functions"),
        ("SELECT * FROM nation; DROP TABLE nation", "BLOCKED (fixable"),
        ("SELECT * FROM employees", "BLOCKED (fixable, the model would get one retry): unknown table"),
        ("SELECT 'oops FROM nation", "BLOCKED (fixable, the model would get one retry): could not parse"),
    ],
)
def test_check_sql_blocked(db_env, capsys, sql, expected):
    assert main(["check-sql", sql]) == 1
    assert capsys.readouterr().out.startswith(expected)


def test_check_sql_reads_stdin(db_env, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT r_name\nFROM region\nLIMIT 5;\n"))
    assert main(["check-sql", "-"]) == 0
    assert "ALLOWED: tables region" in capsys.readouterr().out
