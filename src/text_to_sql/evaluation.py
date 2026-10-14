"""Execution-accuracy evaluation helpers: load questions, normalize and compare result sets."""

from __future__ import annotations

import datetime as dt
import decimal
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlglot import exp

DIFFICULTIES = ("easy", "medium", "hard")


@dataclass(frozen=True)
class EvalItem:
    id: str
    difficulty: str
    question: str
    gold_sql: str
    order_matters: bool = False
    order_key: str | None = None
    category: str = "core"  # "core" | "glossary" | "ambiguous"
    expect_clarification: bool = False


def load_questions(path: Path, category: str = "core") -> list[EvalItem]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items = []
    for r in raw:
        items.append(
            EvalItem(
                id=r["id"],
                difficulty=r["difficulty"],
                question=r["question"].strip(),
                gold_sql=(r.get("gold_sql") or "").strip(),
                order_matters=bool(r.get("order_matters", False)),
                order_key=r.get("order_key"),
                category=r.get("category", category),
                expect_clarification=bool(r.get("expect_clarification", False)),
            )
        )
    ids = [i.id for i in items]
    dupes = [k for k, v in Counter(ids).items() if v > 1]
    if dupes:
        raise ValueError(f"duplicate question ids: {dupes}")
    return items


def gold_tables(sql: str, dialect: str = "duckdb") -> set[str]:
    tree = sqlglot.parse_one(sql, read=dialect)
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table)} - ctes


def normalize_value(v: Any) -> Any:
    """Make values from different-but-equivalent queries compare equal."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (decimal.Decimal, float, int)):
        f = float(v)
        if math.isnan(f):
            return None
        # 2 decimal places absolute, but also tolerate tiny relative error on large sums
        r = round(f, 2)
        return 0.0 if r == 0 else r
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip()
    return str(v)


def _row_key(row: tuple) -> tuple:
    # Column order is ignored: compare each row as a sorted multiset of normalized values.
    vals = [normalize_value(v) for v in row]
    return tuple(sorted(vals, key=lambda x: (x is None, type(x).__name__, str(x))))


def _close(a: tuple, b: tuple) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        if isinstance(x, float) and isinstance(y, float):
            if not math.isclose(x, y, rel_tol=1e-6, abs_tol=0.011):
                return False
        elif x != y:
            return False
    return True


def results_match(pred: list[tuple], gold: list[tuple], *, order_matters: bool = False) -> bool:
    """Execution accuracy: same rows (as multisets, or as sequences if order matters).

    Column names and column order are ignored; the number of columns must match.
    """
    if len(pred) != len(gold):
        return False
    if pred and gold and len(pred[0]) != len(gold[0]):
        return False
    p = [_row_key(r) for r in pred]
    g = [_row_key(r) for r in gold]
    if order_matters:
        return all(_close(a, b) for a, b in zip(p, g, strict=True))
    # exact multiset first (fast path), then tolerant greedy matching for float noise
    if Counter(p) == Counter(g):
        return True
    remaining = sorted(g, key=str)
    for row in sorted(p, key=str):
        for i, cand in enumerate(remaining):
            if _close(row, cand):
                del remaining[i]
                break
        else:
            return False
    return True


def topn_tie_free(backend, item: EvalItem, max_rows: int = 10_000) -> bool:
    """A LIMIT N gold query must have a well-defined answer.

    The Nth and (N+1)th rows must differ on `order_key` (otherwise *which* rows make the cut is
    arbitrary), and when `order_matters`, no two of the top N may tie (otherwise their order is).
    """
    tree = sqlglot.parse_one(item.gold_sql, read=backend.dialect)
    limit = tree.args.get("limit")
    if limit is None or not item.order_key:
        return True
    n = int(limit.expression.name)
    probe = tree.limit(n + 1, copy=True).sql(dialect=backend.dialect)
    res = backend.execute(probe, max_rows=max_rows, timeout_s=30)
    k = res.columns.index(item.order_key)
    keys = [r[k] for r in res.rows]
    if len(keys) > n and keys[n - 1] == keys[n]:
        return False
    if item.order_matters and len(set(keys[:n])) < len(keys[:n]):
        return False
    return True
