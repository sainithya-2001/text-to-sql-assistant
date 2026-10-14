"""Optional Snowflake backend over the shared, read-only TPC-H sample database.

Enabled only when SNOWFLAKE_ACCOUNT/USER/PASSWORD/WAREHOUSE are set (see .env.example) and
`pip install -e ".[snowflake]"` has been run. Table and column names are the same as DuckDB's
TPC-H, upper-cased, so prompts and eval questions work unchanged.
"""

from __future__ import annotations

import time

from .base import Column, QueryError, QueryResult, QueryTimeout, Table

DATABASE = "SNOWFLAKE_SAMPLE_DATA"
SCHEMA = "TPCH_SF1"


class SnowflakeBackend:
    name = "snowflake"
    dialect = "snowflake"

    def __init__(self, creds: dict[str, str], *, database: str = DATABASE, schema: str = SCHEMA):
        try:
            import snowflake.connector
        except ImportError as e:  # pragma: no cover - optional extra
            raise RuntimeError('Snowflake support needs: pip install -e ".[snowflake]"') from e
        self._sf = snowflake.connector
        self.schema = schema
        self._con = snowflake.connector.connect(
            account=creds["SNOWFLAKE_ACCOUNT"],
            user=creds["SNOWFLAKE_USER"],
            password=creds["SNOWFLAKE_PASSWORD"],
            warehouse=creds["SNOWFLAKE_WAREHOUSE"],
            role=creds.get("SNOWFLAKE_ROLE"),
            database=database,
            schema=schema,
            session_parameters={"QUERY_TAG": "text-to-sql-assistant"},
        )

    def tables(self) -> list[Table]:
        cur = self._con.cursor()
        try:
            cur.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s ORDER BY table_name, ordinal_position",
                (self.schema,),
            )
            cols: dict[str, list[Column]] = {}
            for table, column, dtype in cur.fetchall():
                cols.setdefault(table.lower(), []).append(Column(column.lower(), dtype))
            cur.execute(
                "SELECT table_name, row_count FROM information_schema.tables WHERE table_schema = %s",
                (self.schema,),
            )
            counts = {t.lower(): n for t, n in cur.fetchall()}
        finally:
            cur.close()
        return [Table(t, tuple(c), counts.get(t)) for t, c in cols.items()]

    def execute(self, sql: str, *, max_rows: int, timeout_s: float) -> QueryResult:
        cur = self._con.cursor()
        start = time.perf_counter()
        try:
            cur.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {max(1, int(timeout_s))}")
            cur.execute(sql)
            columns = [d[0].lower() for d in cur.description or []]
            rows = cur.fetchmany(max_rows + 1)
        except self._sf.errors.ProgrammingError as e:
            if "timeout" in str(e).lower() or getattr(e, "errno", None) == 604:
                raise QueryTimeout(f"query exceeded {timeout_s:g}s timeout") from e
            raise QueryError(str(e)) from e
        except self._sf.errors.Error as e:
            raise QueryError(str(e)) from e
        finally:
            cur.close()
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows[:max_rows]],
            truncated=len(rows) > max_rows,
            elapsed_s=time.perf_counter() - start,
        )

    def close(self) -> None:
        self._con.close()
