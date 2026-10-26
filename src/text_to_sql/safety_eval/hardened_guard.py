"""Candidate fixes to SqlGuard, kept separate so the study can compare before and after.

Three independent changes, each switchable so the ablation can attribute effects:

1. `scoped_ctes` — a table reference only counts as a CTE if that CTE is *visible at that point*
   (defined in an enclosing WITH, or earlier in the same WITH; itself only under RECURSIVE). The
   baseline collects CTE names from the whole tree, so `SELECT * FROM (WITH "/x.csv" AS (...) ...) s,
   "/x.csv"` passes the guard and DuckDB resolves the outer reference to a file or a system view.
2. `parser_agreement` — the executor's own parser must agree: `duckdb.extract_statements` on the SQL
   that will actually run must yield exactly one SELECT. Catches constructs sqlglot reads as a SELECT
   but DuckDB plans as something else (e.g. `SELECT * FROM (PIVOT ...)` is CREATE TYPE + SELECT).
3. `function_allowlist` — only functions sqlglot models as known expressions are allowed; anything
   that parses as an anonymous function (`getvariable`, `setseed`, extension functions) is rejected.
   Stricter, so it trades usefulness for safety; the over-blocking experiment measures the cost.
"""

from __future__ import annotations

import duckdb
from sqlglot import exp

from ..safety.guard import FORBIDDEN_FUNCTION, GuardedSQL, GuardError, SqlGuard


def _with_of(node: exp.Expression) -> exp.With | None:
    w = node.args.get("with_") or node.args.get("with")
    return w if isinstance(w, exp.With) else None


def visible_ctes(table: exp.Table) -> set[str]:
    """CTE names a table reference can bind to, following SQL scoping rules."""
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


class HardenedSqlGuard(SqlGuard):
    def __init__(
        self,
        allowed_tables: set[str],
        dialect: str = "duckdb",
        *,
        max_rows: int = 200,
        scoped_ctes: bool = True,
        parser_agreement: bool = True,
        function_allowlist: bool = False,
    ):
        super().__init__(allowed_tables, dialect, max_rows=max_rows)
        self.scoped_ctes = scoped_ctes
        self.parser_agreement = parser_agreement
        self.function_allowlist = function_allowlist

    def check(self, sql: str) -> GuardedSQL:
        guarded = super().check(sql)
        import sqlglot

        tree = sqlglot.parse_one(guarded.sql, read=self.dialect)
        if self.scoped_ctes:
            for table in tree.find_all(exp.Table):
                name = table.name.lower()
                if name in self.allowed_tables and not table.args.get("db"):
                    continue
                if table.args.get("db") and name in self.allowed_tables:
                    continue  # schema-qualified business table, checked by the baseline
                if name not in visible_ctes(table):
                    raise GuardError(
                        f"{table.sql(self.dialect)} is not a business table or a CTE in scope here"
                    )
        if self.function_allowlist:
            for func in tree.find_all(exp.Func):
                if isinstance(func, exp.Anonymous):
                    raise GuardError(f"function {func.name}() is not on the allowlist")
                if FORBIDDEN_FUNCTION.match(func.sql_name() or ""):
                    raise GuardError(f"function {func.sql_name()}() is not allowed")
        if self.parser_agreement and self.dialect == "duckdb":
            try:
                stmts = duckdb.extract_statements(guarded.sql)
            except duckdb.Error as e:
                raise GuardError(f"the database could not parse the query: {e}", retryable=True) from e
            kinds = [str(s.type).rsplit(".", 1)[-1] for s in stmts]
            if kinds != ["SELECT"]:
                raise GuardError(f"the database plans this as {'+'.join(kinds)}, not a single SELECT")
        return guarded
