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
from sqlglot.errors import SqlglotError


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


def _with_of(node: exp.Expression) -> exp.With | None:
    w = node.args.get("with_") or node.args.get("with")
    return w if isinstance(w, exp.With) else None


def visible_ctes(table: exp.Table) -> set[str]:
    """CTE names a table reference can bind to, following SQL scoping rules: CTEs of an enclosing
    query, earlier CTEs of the same WITH, and the CTE itself only under WITH RECURSIVE."""
    names: set[str] = set()
    path: list[exp.Expression] = []
    node: exp.Expression | None = table
    while node is not None:
        path.append(node)
        node = node.parent
    on_path = {id(n) for n in path}
    for n in path:
        if isinstance(n, exp.With):
            # The reference sits inside one of this WITH's CTE bodies.
            ctes = list(n.expressions)
            for i, cte in enumerate(ctes):
                if id(cte) in on_path:
                    names |= {c.alias_or_name.lower() for c in ctes[:i]}
                    if n.args.get("recursive"):
                        names.add(cte.alias_or_name.lower())
                    break
            continue
        w = _with_of(n)
        if w is not None and id(w) not in on_path:
            # The reference sits in the body of a query that owns this WITH.
            names |= {c.alias_or_name.lower() for c in w.expressions}
    return names


class SqlGuard:
    """`scoped_ctes` and `parser_agreement` close two bypasses found by the safety study
    (safety_eval/RESULTS.md). Both default on; turning them off reproduces the earlier guard."""

    def __init__(
        self,
        allowed_tables: set[str],
        dialect: str = "duckdb",
        *,
        max_rows: int = 200,
        scoped_ctes: bool = True,
        parser_agreement: bool = True,
    ):
        self.allowed_tables = {t.lower() for t in allowed_tables}
        self.dialect = dialect
        self.max_rows = max_rows
        self.scoped_ctes = scoped_ctes
        self.parser_agreement = parser_agreement

    def check(self, sql: str) -> GuardedSQL:
        text = sql.strip().rstrip(";").strip()
        if not text:
            raise GuardError("empty query", retryable=True)
        try:
            statements = [s for s in sqlglot.parse(text, read=self.dialect) if s is not None]
        except SqlglotError as e:  # ParseError and TokenError (e.g. an unterminated string)
            raise GuardError(f"could not parse SQL: {_first_line(e)}", retryable=True) from e
        # Policy checks run on every statement before the one-statement rule, so a smuggled
        # "SELECT ...; DROP TABLE ..." is blocked outright instead of handed back as fixable.
        for statement in statements:
            self._check_policy(statement)
        if len(statements) != 1:
            raise GuardError(f"expected exactly one statement, got {len(statements)}", retryable=True)
        tree = statements[0]

        cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
        used: set[str] = set()
        for table in tree.find_all(exp.Table):
            name = table.name.lower()
            if self.scoped_ctes:
                # A name only refers to a CTE where that CTE is in scope. Elsewhere DuckDB resolves
                # it as a table, a system view (duckdb_databases) or, quoted, a file path.
                if name in visible_ctes(table):
                    continue
                if name in cte_names and name not in self.allowed_tables:
                    raise GuardError(
                        f"{table.sql(self.dialect)} is not a business table or a CTE in scope here"
                    )
            elif name in cte_names:
                continue
            if name not in self.allowed_tables:
                raise GuardError(
                    f"unknown table {table.name!r}; available: {', '.join(sorted(self.allowed_tables))}",
                    retryable=True,
                )
            used.add(name)

        limit_added = False
        if tree.args.get("limit") is None:
            # Cap the work the database does; fetch one extra row so truncation is detectable.
            tree = tree.limit(self.max_rows + 1, copy=True)
            limit_added = True
        out = tree.sql(dialect=self.dialect) if limit_added else text
        if self.parser_agreement and self.dialect == "duckdb":
            self._check_duckdb_agrees(out)
        return GuardedSQL(sql=out, original=sql, limit_added=limit_added, tables=frozenset(used))

    def _check_duckdb_agrees(self, sql: str) -> None:
        """The executor's own parser must see exactly one SELECT in the SQL that will run. sqlglot
        reads `SELECT * FROM (PIVOT t ON c)` as a SELECT; DuckDB plans it as CREATE TYPE + SELECT."""
        import duckdb

        try:
            statements = duckdb.extract_statements(sql)
        except duckdb.Error as e:
            raise GuardError(
                f"the database could not parse the query: {_first_line(e)}", retryable=True
            ) from e
        kinds = [str(s.type).rsplit(".", 1)[-1] for s in statements]
        if kinds != ["SELECT"]:
            raise GuardError(f"the database plans this as {'+'.join(kinds)}, not a single SELECT")

    def _check_policy(self, tree: exp.Expression) -> None:
        """Raise a non-retryable GuardError for writes, table functions or system access."""
        if not isinstance(tree, (exp.Select, exp.SetOperation)):
            raise GuardError(f"only SELECT queries are allowed (got {tree.key.upper()})")
        for node in tree.walk():
            if isinstance(node, FORBIDDEN_NODES):
                raise GuardError(f"{node.key.upper()} is not allowed in a read-only query")
            if isinstance(node, exp.Select) and node.args.get("into"):
                raise GuardError("SELECT ... INTO is not allowed")

        cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                raise GuardError(f"table functions are not allowed: {table.this.sql(self.dialect)}")
            if table.args.get("db") or table.args.get("catalog"):
                if table.name.lower() in cte_names or table.db.lower() not in {"main", "tpch_sf1"}:
                    raise GuardError(f"only the business tables are queryable, not {table.sql()}")

        for func in tree.find_all(exp.Func):
            fname = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
            if FORBIDDEN_FUNCTION.match(fname or ""):
                raise GuardError(f"function {fname}() is not allowed")


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0][:300]
