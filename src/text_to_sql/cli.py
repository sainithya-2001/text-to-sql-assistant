"""Command-line interface: `t2s <command>`."""

from __future__ import annotations

import argparse
import sys

from .config import Settings
from .db import build_tpch, open_backend
from .schema.catalog import Catalog


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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, Settings.from_env())


if __name__ == "__main__":
    sys.exit(main())
