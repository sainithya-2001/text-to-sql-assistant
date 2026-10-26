"""Mutation fuzzer for SQL safety checks.

Takes seed queries and applies semantics-preserving rewrites that a checker might handle differently
from the database: case, comments, whitespace, quoting, wrapping in subqueries/CTEs, DuckDB's
FROM-first syntax, and the CTE "scope shield" generalised from the bug found by hand. Deterministic
for a given seed.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

from sqlglot.tokens import Tokenizer

Mutator = Callable[[str, random.Random], str | None]
KEYWORDS = re.compile(
    r"\b(select|from|where|with|delete|update|insert|drop|create|union|all|as|exists)\b", re.I
)
UNICODE_SPACES = ["\t", "\n", "\u00a0", "\u2003", "\u000b", "\u000c", "\r\n"]


def _tokens(sql: str) -> list[str] | None:
    try:
        toks = Tokenizer(dialect="duckdb").tokenize(sql)
    except Exception:
        return None
    return [sql[t.start : t.end + 1] for t in toks]


def flip_case(sql: str, rng: random.Random) -> str:
    return KEYWORDS.sub(
        lambda m: "".join(c.upper() if rng.random() < 0.5 else c.lower() for c in m.group()), sql
    )


def inline_comments(sql: str, rng: random.Random) -> str | None:
    toks = _tokens(sql)
    if not toks:
        return None
    sep = rng.choice(["/**/", " /* x */ ", "/*;*/", " --\n", "/* DROP */"])
    return sep.join(toks) if rng.random() < 0.5 else " ".join(toks).replace(" ", sep, 2)


def odd_whitespace(sql: str, rng: random.Random) -> str:
    ws = rng.choice(UNICODE_SPACES)
    return sql.replace(" ", ws)


def wrap_subquery(sql: str, rng: random.Random) -> str | None:
    if ";" in sql or not sql.lstrip().lower().startswith(("select", "with", "from")):
        return None
    return f"SELECT * FROM ({sql}) AS q{rng.randint(0, 9)}"


def wrap_cte(sql: str, rng: random.Random) -> str | None:
    if ";" in sql or not sql.lstrip().lower().startswith(("select", "from")):
        return None
    return f"WITH w AS ({sql}) SELECT * FROM w"


def from_first(sql: str, rng: random.Random) -> str | None:
    m = re.match(r"(?is)\s*select\s+\*\s+from\s+(.+)$", sql)
    return f"FROM {m.group(1)}" if m else None


def quote_names(sql: str, rng: random.Random) -> str:
    return re.sub(r"\b(duckdb_\w+|region|customer|orders|lineitem)\b", r'"\1"', sql)


def trailing_noise(sql: str, rng: random.Random) -> str:
    return sql + rng.choice([";", " ;", ";;", "; --", "\n-- end", " /* end */", ";\n"])


def add_limit(sql: str, rng: random.Random) -> str | None:
    # A LIMIT makes the baseline guard execute the original text instead of re-rendered SQL.
    if ";" in sql or re.search(r"(?i)\blimit\b", sql):
        return None
    return sql + " LIMIT 5"


SHIELDABLE = re.compile(r'(?i)\bfrom\s+("[^"]+"|duckdb_\w+|pg_\w+|information_schema\.\w+|sqlite_master)')


def scope_shield(sql: str, rng: random.Random) -> str | None:
    """Generalised CTE scope confusion: declare an out-of-scope CTE with the forbidden name."""
    m = SHIELDABLE.search(sql)
    if not m or ";" in sql:
        return None
    name = m.group(1)
    shield = f"EXISTS (WITH {name} AS (SELECT 1) SELECT 1)"
    if re.search(r"(?i)\bwhere\b", sql):
        return re.sub(r"(?i)\bwhere\b", f"WHERE {shield} AND", sql, count=1)
    return f"{sql} WHERE {shield}"


def lateral_shield(sql: str, rng: random.Random) -> str | None:
    m = SHIELDABLE.search(sql)
    if not m or ";" in sql:
        return None
    name = m.group(1)
    return f"SELECT * FROM (WITH {name} AS (SELECT 1) SELECT 1) s, ({sql}) t"


MUTATORS: dict[str, Mutator] = {
    "flip_case": flip_case,
    "inline_comments": inline_comments,
    "odd_whitespace": odd_whitespace,
    "wrap_subquery": wrap_subquery,
    "wrap_cte": wrap_cte,
    "from_first": from_first,
    "quote_names": quote_names,
    "trailing_noise": trailing_noise,
    "add_limit": add_limit,
    "scope_shield": scope_shield,
    "lateral_shield": lateral_shield,
}


def mutate(seeds: list[dict], *, per_seed: int, depth: int, seed: int = 0) -> list[dict]:
    """Return unique mutants: {id, parent, ops, sql, goal, category}."""
    rng = random.Random(seed)
    out: dict[str, dict] = {}
    names = list(MUTATORS)
    for s in seeds:
        tries = 0
        made = 0
        while made < per_seed and tries < per_seed * 6:
            tries += 1
            sql, ops = s["sql"], []
            for _ in range(rng.randint(1, depth)):
                op = rng.choice(names)
                new = MUTATORS[op](sql, rng)
                if new and new != sql:
                    sql, ops = new, ops + [op]
            if ops and sql not in out:
                out[sql] = {
                    "id": f"{s['id']}~{made}",
                    "parent": s["id"],
                    "ops": ops,
                    "sql": sql,
                    "goal": s["goal"],
                    "category": s["category"],
                }
                made += 1
    return list(out.values())
