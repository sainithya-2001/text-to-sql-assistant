"""Run the text-to-SQL eval (`t2s eval ...` or `python eval/run_eval.py ...`).

    t2s eval --pilot 3                                # cheap cost estimate (3 questions x all configs)
    t2s eval                                          # full run, $1 hard cap
    t2s eval --models claude-haiku-5-5 --modes full --ids e01,h05
    t2s eval --questions glossary_questions.yaml,ambiguous_questions.yaml --glossary both

Results: eval/results/<name>.json, eval/results/<name>.md (summary + failures).
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import PROJECT_ROOT, Settings
from .db import open_backend
from .eval_runner import Config, failures, run_eval, summarize
from .evaluation import DIFFICULTIES, load_questions
from .llm.client import ClaudeLLM
from .llm.cost import BudgetGuard
from .schema.catalog import Catalog
from .schema.embed import make_embedder
from .schema.glossary import Glossary
from .schema.retriever import SchemaRetriever

EVAL_DIR = PROJECT_ROOT / "eval"


def pick_pilot(items, n):
    """n questions spread across difficulties (round-robin easy/medium/hard)."""
    by = {d: [i for i in items if i.difficulty == d] for d in DIFFICULTIES}
    out = []
    while len(out) < n and any(by.values()):
        for d in DIFFICULTIES:
            if by[d] and len(out) < n:
                out.append(by[d].pop(0))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="t2s eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--questions", default="questions.yaml", help="comma-separated files in eval/")
    p.add_argument("--models", default="claude-haiku-5-5,claude-sonnet-5-5")
    p.add_argument("--modes", default="full,retrieved")
    p.add_argument("--glossary", choices=["off", "on", "both"], default="off")
    p.add_argument("--budget", type=float, default=1.0, help="hard cap in dollars for this run")
    p.add_argument("--pilot", type=int, default=0, help="run only N questions and extrapolate cost")
    p.add_argument("--ids", help="comma-separated question ids")
    p.add_argument("--name", default=None, help="output name (default: pilot or full)")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p.add_argument(
        "--configs", help="explicit configs, e.g. claude-sonnet-5-5/full+glossary (overrides above)"
    )
    p.add_argument("--resume", action="store_true", help="keep finished results in eval/results/<name>.json")
    args = p.parse_args(argv)

    items = []
    for f in args.questions.split(","):
        items += load_questions(EVAL_DIR / f.strip())
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i.id in wanted]
    all_items = items
    if args.pilot:
        items = pick_pilot(items, args.pilot)
    gloss = {"off": [False], "on": [True], "both": [False, True]}[args.glossary]
    configs = [
        Config(m, mode, g) for m in args.models.split(",") for mode in args.modes.split(",") for g in gloss
    ]
    if args.configs:
        configs = [Config.parse(c.strip()) for c in args.configs.split(",")]
    n_calls = len(items) * len(configs)

    print(f"{len(items)} questions x {len(configs)} configs = {n_calls} runs; cap ${args.budget:.2f}")
    if not args.yes and not args.pilot and input("Proceed? [y/N] ").strip().lower() != "y":
        return 1

    settings = Settings.from_env()
    backend = open_backend(settings)
    catalog = Catalog.from_backend(backend)
    retriever = SchemaRetriever(catalog, make_embedder(settings.embedder))
    budget = BudgetGuard(cap_usd=args.budget)
    name = args.name or ("pilot" if args.pilot else "full")
    out = EVAL_DIR / "results" / f"{name}.json"
    resume = json.loads(out.read_text(encoding="utf-8")) if args.resume and out.exists() else None
    if resume:
        print(f"resuming {out.name}: ${resume['spent_usd']:.4f} already spent; finished pairs are skipped")

    run = run_eval(
        items,
        configs,
        backend=backend,
        catalog=catalog,
        retriever=retriever,
        make_llm=lambda model, b: ClaudeLLM(model, effort=settings.effort, budget=b),
        budget=budget,
        out_path=out,
        top_k=settings.top_k_tables,
        glossary=Glossary.load(settings.glossary_path),
        resume=resume,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    md = f"# Eval: {name}\n\n{summarize(data)}\n\n## Failures\n\n{failures(data)}\n"
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print("\n" + summarize(data))

    if args.pilot:
        per_cfg = {c: sum(r["cost_usd"] for r in rs) / max(len(rs), 1) for c, rs in data["items"].items()}
        full = sum(per_cfg.values()) * len(all_items)
        print(
            f"\nPilot cost ${run.spent_usd:.4f}. Projected full run ({len(all_items)} questions): ${full:.3f}"
        )
        for c, v in per_cfg.items():
            print(f"  {c}: ${v:.5f}/question -> ${v * len(all_items):.3f}")
    return 0 if not run.stopped_reason else 2


if __name__ == "__main__":
    sys.exit(main())
