"""DuckDB backend over a locally generated TPC-H database."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import duckdb

from .base import Column, QueryError, QueryResult, QueryTimeout, Table

TPCH_TABLES = ("customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier")


def build_tpch(path: Path, scale: float = 0.01, *, overwrite: bool = False) -> Path:
    """Generate TPC-H into `path` with DuckDB's tpch extension. No dataset download needed."""
    path = Path(path)
    if path.exists():
        if not overwrite:
            return path
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute("INSTALL tpch")
        con.execute("LOAD tpch")
        con.execute(f"CALL dbgen(sf={float(scale)})")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    tmp.replace(path)
    return path


class DuckDBBackend:
    """Read-only connection with external access disabled and configuration locked.

    `read_only` stops writes; `enable_external_access=false` stops file/network reads such as
    `read_csv('/etc/passwd')`, ATTACH, COPY and INSTALL; `lock_configuration` stops SQL from undoing that.
    """

    name = "duckdb"
    dialect = "duckdb"

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found; run `t2s init-db` first")
        self._con = duckdb.connect(
            str(self.path),
            read_only=True,
            config={"enable_external_access": False, "lock_configuration": True},
        )
        self._lock = threading.Lock()

    def tables(self) -> list[Table]:
        rows = self._con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
        ).fetchall()
        cols: dict[str, list[Column]] = {}
        for table, column, dtype in rows:
            cols.setdefault(table, []).append(Column(column, dtype))
        out = []
        for table, columns in cols.items():
            (count,) = self._con.execute(f'SELECT count(*) FROM "{table}"').fetchone()
            out.append(Table(table, tuple(columns), count))
        return out

    def execute(self, sql: str, *, max_rows: int, timeout_s: float) -> QueryResult:
        # One query at a time per connection; interrupt() cancels whatever is running on it.
        with self._lock:
            timed_out = threading.Event()

            def _cancel() -> None:
                timed_out.set()
                self._con.interrupt()

            timer = threading.Timer(timeout_s, _cancel)
            start = time.perf_counter()
            timer.start()
            try:
                cur = self._con.execute(sql)
                columns = [d[0] for d in cur.description or []]
                rows = cur.fetchmany(max_rows + 1)
            except duckdb.InterruptException as e:
                raise QueryTimeout(f"query exceeded {timeout_s:g}s timeout") from e
            except duckdb.Error as e:
                if timed_out.is_set():
                    raise QueryTimeout(f"query exceeded {timeout_s:g}s timeout") from e
                raise QueryError(f"{type(e).__name__}: {e}") from e
            finally:
                timer.cancel()
            truncated = len(rows) > max_rows
            return QueryResult(
                columns=columns,
                rows=rows[:max_rows],
                truncated=truncated,
                elapsed_s=time.perf_counter() - start,
            )

    def close(self) -> None:
        self._con.close()
