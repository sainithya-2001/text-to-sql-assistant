"""Command-line interface: `t2s <command>`."""

from __future__ import annotations

import argparse
import sys

from .config import Settings
from .db import build_tpch, open_backend
from .llm.client import ClaudeLLM
from .llm.cost import BudgetGuard
from .pipeline import Answer, Assistant
from .schema.catalog import Catalog
from .schema.embed import make_embedder
from .schema.retriever import SchemaRetriever


def build_assistant(settings: Settings, *, model: str | None = None, budget: BudgetGuard | None = None):
    backend = open_backend(settings)
    catalog = Catalog.from_backend(backend)
    retriever = SchemaRetriever(catalog, make_embedder(settings.embedder))
    llm = ClaudeLLM(model or settings.model, effort=settings.effort, budget=budget)
    return Assistant(
        backend,
        catalog,
        llm,
        retriever,
        top_k=settings.top_k_tables,
        max_rows=settings.max_rows,
        timeout_s=settings.timeout_s,
    )


def format_table(columns: list[str], rows: list[tuple], limit: int = 20) -> str:
    shown = [tuple("NULL" if v is None else str(v) for v in r) for r in rows[:limit]]
    widths = [max([len(c)] + [len(r[i]) for r in shown]) for i, c in enumerate(columns)]

    def line(vals) -> str:
        return " | ".join(v.ljust(w) for v, w in zip(vals, widths, strict=True))

    out = [line(columns), "-+-".join("-" * w for w in widths)] + [line(r) for r in shown]
    if len(rows) > limit:
        out.append(f"... {len(rows) - limit} more rows")
    return "\n".join(out)


def print_answer(ans: Answer, verbose: bool = False) -> None:
    if verbose and ans.retrieval:
        top = ", ".join(f"{t}={s:.2f}" for t, s in ans.retrieval.ranked[:6])
        bridges = f" | bridges: {ans.retrieval.bridges}" if ans.retrieval.bridges else ""
        print(f"retrieval: {top}{bridges}")
    print(f"schema ({ans.schema_mode}): {', '.join(ans.tables)}")
    for i, a in enumerate(ans.attempts, 1):
        print(f"\n-- attempt {i}\n{a.sql}")
        if a.error:
            print(f"-- error: {a.error}")
    if ans.cannot_answer:
        print(f"\nCannot answer: {ans.cannot_answer}")
    elif ans.ok:
        print()
        print(format_table(ans.result.columns, ans.result.rows))
        if ans.result.truncated:
            print(f"(truncated at {len(ans.result.rows)} rows)")
    elif ans.error:
        print(f"\nError: {ans.error}")
    u = ans.usage
    print(
        f"\n[{ans.model}] in={u.input_tokens} cache_read={u.cache_read_input_tokens} "
        f"cache_write={u.cache_creation_input_tokens} out={u.output_tokens} "
        f"cost=${ans.cost_usd:.5f} time={ans.elapsed_s:.1f}s"
    )


def cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    path = build_tpch(settings.duckdb_path, args.scale or settings.tpch_scale, overwrite=args.force)
    print(f"TPC-H ready at {path}")
    return 0


def cmd_schema(args: argparse.Namespace, settings: Settings) -> int:
    backend = open_backend(settings)
    try:
        print(Catalog.from_backend(backend).render(args.tables or None))
    finally:
        backend.close()
    return 0


def cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    budget = BudgetGuard(cap_usd=args.budget)
    assistant = build_assistant(settings, model=args.model, budget=budget)
    try:
        ans = assistant.ask(args.question, schema_mode=args.schema)
    finally:
        assistant.backend.close()
    print_answer(ans, verbose=args.verbose)
    return 0 if ans.ok or ans.cannot_answer else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="t2s", description="Text-to-SQL assistant over TPC-H")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="generate the local DuckDB TPC-H database")
    s.add_argument("--scale", type=float, help="TPC-H scale factor (default 0.01)")
    s.add_argument("--force", action="store_true", help="rebuild if it exists")
    s.set_defaults(func=cmd_init_db)

    s = sub.add_parser("schema", help="print the schema as the model sees it")
    s.add_argument("tables", nargs="*")
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser("ask", help="answer a question")
    s.add_argument("question")
    s.add_argument("--model", help="e.g. claude-sonnet-5-5 or claude-haiku-5-5")
    s.add_argument("--schema", choices=["retrieved", "full"], default="retrieved")
    s.add_argument("--budget", type=float, default=0.05, help="max dollars for this command (default 0.05)")
    s.add_argument("-v", "--verbose", action="store_true", help="show retrieval scores")
    s.set_defaults(func=cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, Settings.from_env())


if __name__ == "__main__":
    sys.exit(main())
