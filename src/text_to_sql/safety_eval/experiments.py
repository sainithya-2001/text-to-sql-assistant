"""Offline experiments (no API calls): attack corpus, over-blocking, mutation fuzzing."""

from __future__ import annotations

import json
import logging
import platform
import time
from collections import Counter
from pathlib import Path

import duckdb
import sqlglot
import yaml

from ..evaluation import load_questions, results_match
from .fuzz import mutate
from .layers import CONFIG_BY_NAME, CONFIGS, MAX_ROWS, make_guard, run_sql
from .sandbox import RESTRICTED_READ, load_restricted_values

ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = ROOT / "safety_eval"
RESULTS_DIR = CORPUS_DIR / "results"
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "sqlglot": sqlglot.__version__,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_yaml(name: str) -> list[dict]:
    return yaml.safe_load((CORPUS_DIR / name).read_text(encoding="utf-8"))


def run_attacks(db: Path, configs=CONFIGS) -> dict:
    restricted = load_restricted_values(db)
    rows = []
    for a in load_yaml("attacks.yaml"):
        for c in configs:
            o = run_sql(a["sql"], c, db, restricted)
            rows.append(
                {
                    **{k: a.get(k) for k in ("id", "category", "goal", "sql")},
                    **o.to_json(),
                    "success": a["goal"] in o.harms,
                }
            )
    return {"env": environment(), "results": rows}


def benign_items() -> list[dict]:
    items = [
        {
            "id": i["id"],
            "kind": i["kind"],
            "sql": i["sql"],
            "set": "tricky",
            "compare": i.get("compare", "rows"),
        }
        for i in load_yaml("benign.yaml")
    ]
    for path, cat in (
        (ROOT / "eval/questions.yaml", "core"),
        (ROOT / "eval/glossary_questions.yaml", "glossary"),
    ):
        for q in load_questions(path, cat):
            if q.gold_sql:
                items.append({"id": q.id, "kind": q.difficulty, "sql": q.gold_sql, "set": f"gold_{cat}"})
    return items


def run_benign(db: Path, configs=CONFIGS) -> dict:
    """A benign query counts as served if the layer lets it run and it returns the same rows as an
    unprotected connection (compared as multisets, like the accuracy eval)."""
    restricted = load_restricted_values(db)
    rows = []
    for item in benign_items():
        ref = run_sql(item["sql"], CONFIG_BY_NAME["none"], db, restricted, template=False, keep_rows=True)
        for c in configs:
            o = (
                ref
                if c.name == "none"
                else run_sql(item["sql"], c, db, restricted, template=False, keep_rows=True)
            )
            if item.get("compare") == "count":
                same = bool(o.ran and ref.ran and len(o.rows or []) == len(ref.rows or []))
            else:
                same = bool(o.ran and ref.ran and o.rows is not None and results_match(o.rows, ref.rows))
            harms = [h for h in o.harms if h != RESTRICTED_READ]
            rows.append(
                {
                    **item,
                    **o.to_json(),
                    "reference_ok": ref.ran and not ref.error,
                    "served": same and not o.error,
                    "false_harm": harms,
                }
            )
    return {"env": environment(), "results": rows}


def run_fuzz(
    db: Path,
    *,
    per_seed: int = 40,
    depth: int = 3,
    seed: int = 0,
    configs=("guard_only", "guard+ro", "hardened+ro", "strict+ro"),
) -> dict:
    """Mutate the attack corpus, then execute only mutants some guard lets through (a blocked
    mutant cannot cause harm under that config)."""
    restricted = load_restricted_values(db)
    seeds = [a for a in load_yaml("attacks.yaml") if a["category"] not in ("restricted", "dos")]
    mutants = mutate(seeds, per_seed=per_seed, depth=depth, seed=seed)
    guards = {name: make_guard(CONFIG_BY_NAME[name].guard) for name in configs}
    rows = []
    for m in mutants:
        rec = {**m, "outcomes": {}}
        for name in configs:
            from ..safety.guard import GuardError

            guard = guards[name]
            # Guard decisions don't depend on the trial paths except through the template, so check
            # a templated copy cheaply before paying for a trial.
            probe = (
                m["sql"]
                .replace("{CANARY_FILE}", "/tmp/x/secrets.csv")
                .replace("{DIR}", "/tmp/x")
                .replace("{OUT_FILE}", "/tmp/x/o.csv")
                .replace("{DB}", "/tmp/x/t.duckdb")
            )
            try:
                guard.check(probe)
            except GuardError as e:
                rec["outcomes"][name] = {"guard_verdict": "reject" if e.retryable else "block", "harms": []}
                continue
            o = run_sql(m["sql"], CONFIG_BY_NAME[name], db, restricted)
            rec["outcomes"][name] = {
                "guard_verdict": o.guard_verdict,
                "harms": o.harms,
                "error": o.error,
                "executed_sql": o.executed_sql,
            }
        rows.append(rec)
    return {
        "env": environment(),
        "params": {
            "per_seed": per_seed,
            "depth": depth,
            "seed": seed,
            "n_seeds": len(seeds),
            "n_mutants": len(mutants),
        },
        "results": rows,
    }


def save(name: str, data: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{name}.json"
    p.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return p


def guard_rows_cap() -> int:
    return MAX_ROWS


def summarize_counter(rows: list[dict], key) -> Counter:
    return Counter(key(r) for r in rows)
