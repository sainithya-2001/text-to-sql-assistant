"""Guard variants for the study.

The two fixes the study proposed now live in `SqlGuard` itself (`scoped_ctes`, `parser_agreement`,
both on by default). The study reproduces the pre-fix guard with both switched off, and adds one
stricter variant that was measured but not adopted:

`function_allowlist`: only functions sqlglot models as known expressions are allowed; anything that
parses as an anonymous function (`getvariable`, `setseed`, extension functions) is rejected. It added
no measured safety over the fixed guard, so it stays here rather than in production.
"""

from __future__ import annotations

from sqlglot import exp

from ..safety.guard import FORBIDDEN_FUNCTION, GuardedSQL, GuardError, SqlGuard, visible_ctes

__all__ = ["HardenedSqlGuard", "pre_fix_guard", "visible_ctes"]


def pre_fix_guard(allowed_tables: set[str], dialect: str = "duckdb", *, max_rows: int = 200) -> SqlGuard:
    """SqlGuard as it was before the study (both fixes off), for reproducing its results."""
    return SqlGuard(allowed_tables, dialect, max_rows=max_rows, scoped_ctes=False, parser_agreement=False)


class HardenedSqlGuard(SqlGuard):
    def __init__(
        self,
        allowed_tables: set[str],
        dialect: str = "duckdb",
        *,
        max_rows: int = 200,
        function_allowlist: bool = False,
    ):
        super().__init__(allowed_tables, dialect, max_rows=max_rows)
        self.function_allowlist = function_allowlist

    def check(self, sql: str) -> GuardedSQL:
        guarded = super().check(sql)
        if self.function_allowlist:
            import sqlglot

            tree = sqlglot.parse_one(guarded.sql, read=self.dialect)
            for func in tree.find_all(exp.Func):
                if isinstance(func, exp.Anonymous):
                    raise GuardError(f"function {func.name}() is not on the allowlist")
                if FORBIDDEN_FUNCTION.match(func.sql_name() or ""):
                    raise GuardError(f"function {func.sql_name()}() is not allowed")
        return guarded
