"""python -m text_to_sql.safety_eval {attacks,benign,fuzz,offline,report} [options]

Examples (all offline, no API calls):
  offline --per-seed 25                     attacks + benign + fuzz, the published run
  fuzz --per-seed 60 --depth 4 --seed 7 --configs guard+ro,hardened+ro --name fuzz_seed7
                                            the second, larger fuzz (RESULTS.md, "Version check")
  offline --per-seed 25 --db COPY.duckdb --out-dir safety_eval/results/duckdb-2.0
                                            the same study on another DuckDB version
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import experiments as ex
from .layers import CONFIG_BY_NAME


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="python -m text_to_sql.safety_eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("step", choices=["attacks", "benign", "fuzz", "offline", "report"])
    p.add_argument("--db", type=Path, default=ex.ROOT / "data" / "tpch.duckdb")
    p.add_argument("--out-dir", type=Path, default=None, help="where JSON results go (default: results/)")
    p.add_argument("--per-seed", type=int, default=40, help="fuzz: variants per seed attack")
    p.add_argument("--depth", type=int, default=3, help="fuzz: max mutations stacked per variant")
    p.add_argument("--seed", type=int, default=0, help="fuzz: random seed")
    p.add_argument(
        "--configs",
        default="guard_only,guard+ro,hardened+ro,strict+ro",
        help="fuzz: comma-separated configurations",
    )
    p.add_argument("--name", default=None, help="fuzz: output file name (default: fuzz)")
    a = p.parse_args(argv)
    configs = tuple(c.strip() for c in a.configs.split(","))
    unknown = [c for c in configs if c not in CONFIG_BY_NAME]
    if unknown:
        p.error(f"unknown config(s) {unknown}; choose from {', '.join(CONFIG_BY_NAME)}")

    steps = ["attacks", "benign", "fuzz"] if a.step == "offline" else [a.step]
    for step in steps:
        t = time.perf_counter()
        if step == "attacks":
            out = ex.save("attacks", ex.run_attacks(a.db), a.out_dir)
        elif step == "benign":
            out = ex.save("benign", ex.run_benign(a.db), a.out_dir)
        elif step == "fuzz":
            data = ex.run_fuzz(a.db, per_seed=a.per_seed, depth=a.depth, seed=a.seed, configs=configs)
            out = ex.save(a.name or "fuzz", data, a.out_dir)
        else:
            from .report import write_report

            out = write_report()
        print(f"{step}: {out} ({time.perf_counter() - t:.0f}s)")


if __name__ == "__main__":
    main()
