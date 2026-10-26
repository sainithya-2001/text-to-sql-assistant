"""Generate safety_eval/results/summary.md from the raw JSON results."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from .experiments import RESULTS_DIR
from .layers import CONFIGS

CFG = [c.name for c in CONFIGS]
SERIOUS = {"integrity", "file_write", "file_read", "env_read", "system_disclosure", "session_state"}


def _load(name: str):
    p = RESULTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def attacks_section(d) -> str:
    rows = d["results"]
    cats = sorted({r["category"] for r in rows})
    lines = [
        "## Exp 1: hand-written attacks",
        "",
        "Cells: attacks that achieved their goal / attacks in the category. Harm is measured on the "
        "database and filesystem, not inferred from the guard's verdict.",
        "",
    ]
    body = []
    for cat in cats:
        cells = []
        for c in CFG:
            rs = [r for r in rows if r["category"] == cat and r["config"] == c]
            cells.append(f"{sum(r['success'] for r in rs)}/{len(rs)}")
        body.append([cat] + cells)
    tot = []
    for c in CFG:
        rs = [r for r in rows if r["config"] == c and r["category"] not in ("dos", "restricted")]
        tot.append(f"**{sum(r['success'] for r in rs)}/{len(rs)}**")
    body.append(["**all except dos, restricted**"] + tot)
    lines.append(_table(["category"] + CFG, body))
    lines += ["", "Any serious harm (goal or not) that got through a guarded configuration:", ""]
    hits = [r for r in rows if r["config"] not in ("none", "ro_only") and set(r["harms"]) & SERIOUS]
    hb = [[r["config"], r["id"], r["category"], ", ".join(r["harms"]), f"`{r['sql'][:70]}`"] for r in hits]
    lines.append(_table(["config", "id", "category", "harms", "sql"], hb) if hb else "None.")
    return "\n".join(lines)


def benign_section(d) -> str:
    rows = [r for r in d["results"] if r["reference_ok"]]
    groups = defaultdict(list)
    for r in rows:
        key = f"tricky:{r['kind']}" if r["set"] == "tricky" else r["set"]
        groups[key].append(r)
    lines = [
        "## Exp 2: over-blocking of legitimate queries",
        "",
        "Cells: queries served with the same rows as an unprotected connection / queries.",
        "",
    ]
    body = []
    for key in sorted(groups):
        body.append(
            [key]
            + [
                f"{sum(r['served'] for r in groups[key] if r['config'] == c)}/"
                f"{sum(1 for r in groups[key] if r['config'] == c)}"
                for c in CFG
            ]
        )
    body.append(
        ["**all**"]
        + [
            f"**{sum(r['served'] for r in rows if r['config'] == c)}/"
            f"{sum(1 for r in rows if r['config'] == c)}**"
            for c in CFG
        ]
    )
    lines.append(_table(["set"] + CFG, body))
    lines += ["", "Legitimate queries not served in a guarded configuration:", ""]
    miss = [
        [r["config"], r["id"], r["guard_verdict"], (r["guard_message"] or r["error"] or "rows differ")[:80]]
        for r in rows
        if r["config"] not in ("none", "ro_only") and not r["served"]
    ]
    lines.append(_table(["config", "id", "verdict", "reason"], miss) if miss else "None.")
    fh = [r for r in rows if r["false_harm"]]
    lines += ["", f"Oracle false alarms on legitimate queries: {len(fh)}."]
    return "\n".join(lines)


def fuzz_section(d) -> str:
    rows = d["results"]
    p = d["params"]
    names = list(rows[0]["outcomes"]) if rows else []
    lines = [
        "## Exp 1b: mutation fuzzing",
        "",
        f"{p['n_mutants']} unique mutants from {p['n_seeds']} seed attacks "
        f"(up to {p['per_seed']} per seed, depth {p['depth']}, rng seed {p['seed']}).",
        "",
    ]
    body = []
    for n in names:
        allowed = [r for r in rows if r["outcomes"][n]["guard_verdict"] == "allow"]
        harmful = [r for r in allowed if set(r["outcomes"][n]["harms"]) & SERIOUS]
        parents = sorted({r["parent"] for r in harmful})
        ops = Counter(op for r in harmful for op in set(r["ops"]))
        body.append(
            [
                n,
                str(len(allowed)),
                str(len(harmful)),
                ", ".join(parents) or "-",
                ", ".join(f"{k} ({v})" for k, v in ops.most_common(4)) or "-",
            ]
        )
    lines.append(
        _table(["config", "mutants allowed", "allowed AND harmful", "seed attacks", "top mutators"], body)
    )
    return "\n".join(lines)


def write_report():
    parts = [
        "# Safety eval: generated summary",
        "",
        "Regenerate with `python -m text_to_sql.safety_eval report`. Configurations:",
        "",
    ]
    parts += [f"- `{c.name}`: {c.description}" for c in CONFIGS]
    for name, fn in (("attacks", attacks_section), ("fuzz", fuzz_section), ("benign", benign_section)):
        d = _load(name)
        if d:
            parts += ["", fn(d), "", f"_Environment: {d['env']}_"]
    out = RESULTS_DIR / "summary.md"
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out
