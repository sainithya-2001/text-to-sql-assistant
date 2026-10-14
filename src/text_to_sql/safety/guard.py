"""SELECT-only validation with sqlglot.

The guard is the first layer; the read-only, external-access-disabled connection is the second. The
guard is an allowlist where it can be (statement shape, table names) and a denylist only for scalar
functions that expose server state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class GuardError(ValueError):
    """The SQL was rejected. The message is safe to show the user and the LLM.

    `retryable` is False for policy violations (writes, system access): those are refused outright
    rather than handed back to the model to "fix".
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


# Anything that writes, changes state, or runs another statement.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy",
        "Pragma", "Set", "Use", "Transaction", "Commit", "Rollback", "Describe", "Show",
        "LoadData", "Attach", "Detach", "Install", "Grant", "Revoke", "TruncateTable", "Into",
    )
    if hasattr(exp, name)
)  # fmt: skip

# Scalar functions that read server/environment state or run nested SQL.
FORBIDDEN_FUNCTION = re.compile(
    # current_* covers current_setting/user/database/schema/version (sqlglot maps version() to
    # CURRENT_VERSION) but keeps current_date/current_time/current_timestamp.
    r"^(duckdb_\w*|pragma_\w*|read_\w*|sqlite_\w*|parquet_\w*|glob|getenv|"
    r"current_(?!date$|time$|timestamp$)\w+|version|query|query_table|system\$\w*|"
    r"system_\w*|load_file|sniff_csv|which_secret|get_ddl|result_scan)$",
    re.I,
)


@dataclass(frozen=True)
class GuardedSQL:
    sql: str  # what will actually run
    original: str
    limit_added: bool
    tables: frozenset[str]


class SqlGuard:
    def __init__(self, allowed_tables: set[str], dialect: str = "duckdb", *, max_rows: int = 200):
        self.allowed_tables = {t.lower() for t in allowed_tables}
        self.dialect = dialect
        self.max_rows = max_rows

    def check(self, sql: str) -> GuardedSQL:
        text = sql.strip().rstrip(";").strip()
        if not text:
            raise GuardError("empty query", retryable=True)
        try:
            statements = [s for s in sqlglot.parse(text, read=self.dialect) if s is not None]
        except ParseError as e:
            raise GuardError(f"could not parse SQL: {_first_line(e)}", retryable=True) from e
        if len(statements) != 1:
            raise GuardError(f"expected exactly one statement, got {len(statements)}", retryable=True)
        tree = statements[0]

        if not isinstance(tree, (exp.Select, exp.SetOperation)):
            raise GuardError(f"only SELECT queries are allowed (got {tree.key.upper()})")
        for node in tree.walk():
            if isinstance(node, FORBIDDEN_NODES):
                raise GuardError(f"{node.key.upper()} is not allowed in a read-only query")
            if isinstance(node, exp.Select) and node.args.get("into"):
                raise GuardError("SELECT ... INTO is not allowed")

        cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
        used: set[str] = set()
        for table in tree.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                raise GuardError(f"table functions are not allowed: {table.this.sql(self.dialect)}")
            name = table.name.lower()
            if table.args.get("db") or table.args.get("catalog"):
                if name in cte_names or table.db.lower() not in {"main", "tpch_sf1"}:
                    raise GuardError(f"only the business tables are queryable, not {table.sql()}")
            if name in cte_names:
                continue
            if name not in self.allowed_tables:
                raise GuardError(
                    f"unknown table {table.name!r}; available: {', '.join(sorted(self.allowed_tables))}",
                    retryable=True,
                )
            used.add(name)

        for func in tree.find_all(exp.Func):
            fname = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
            if FORBIDDEN_FUNCTION.match(fname or ""):
                raise GuardError(f"function {fname}() is not allowed")

        limit_added = False
        if tree.args.get("limit") is None:
            # Cap the work the database does; fetch one extra row so truncation is detectable.
            tree = tree.limit(self.max_rows + 1, copy=True)
            limit_added = True
        out = tree.sql(dialect=self.dialect) if limit_added else text
        return GuardedSQL(sql=out, original=sql, limit_added=limit_added, tables=frozenset(used))


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0][:300]
