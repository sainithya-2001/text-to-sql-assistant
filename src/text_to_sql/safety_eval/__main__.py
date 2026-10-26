"""python -m text_to_sql.safety_eval {attacks,benign,fuzz,offline,report} [--db PATH]"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import experiments as ex


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m text_to_sql.safety_eval")
    p.add_argument("step", choices=["attacks", "benign", "fuzz", "offline", "report"])
    p.add_argument("--db", type=Path, default=ex.ROOT / "data" / "tpch.duckdb")
    p.add_argument("--per-seed", type=int, default=40)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)

    steps = ["attacks", "benign", "fuzz"] if a.step == "offline" else [a.step]
    for step in steps:
        t = time.perf_counter()
        if step == "attacks":
            out = ex.save("attacks", ex.run_attacks(a.db))
        elif step == "benign":
            out = ex.save("benign", ex.run_benign(a.db))
        elif step == "fuzz":
            out = ex.save("fuzz", ex.run_fuzz(a.db, per_seed=a.per_seed, seed=a.seed))
        else:
            from .report import write_report

            out = write_report()
        print(f"{step}: {out} ({time.perf_counter() - t:.0f}s)")


if __name__ == "__main__":
    main()
