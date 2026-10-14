"""Build the README results section from saved eval runs (no API calls).

python eval/report.py > eval/results/REPORT.md
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
RUNS = ["core_baseline", "core_glossary", "glossary_sets"]
DIFFS = ("easy", "medium", "hard")
SHORT = {"claude-haiku-5-5": "Haiku 5.5", "claude-sonnet-5-5": "Sonnet 5.5"}


def label(cfg: str) -> str:
    model, rest = cfg.split("/", 1)
    mode, _, gl = rest.partition("+")
    return f"{SHORT.get(model, model)} | {mode} | {'on' if gl else 'off'}"


def pct(rows) -> str:
    n = len(rows)
    k = sum(r["correct"] for r in rows)
    return f"{100 * k / n:.0f}% ({k}/{n})" if n else "-"


def table(rows_by_cfg: dict[str, list[dict]], by_difficulty: bool) -> list[str]:
    head = "| Model | Schema | Glossary |"
    head += " Easy | Medium | Hard |" if by_difficulty else ""
    head += " **Accuracy** | Retries | $ / question | Avg latency |"
    out = [head, "|" + "---|" * (head.count("|") - 1)]
    for cfg, rows in rows_by_cfg.items():
        cells = [label(cfg)]
        if by_difficulty:
            cells += [pct([r for r in rows if r["difficulty"] == d]) for d in DIFFS]
        cost = sum(r["cost_usd"] for r in rows) / len(rows)
        lat = sum(r["elapsed_s"] for r in rows) / len(rows)
        cells += [f"**{pct(rows)}**", str(sum(r["retried"] for r in rows)), f"${cost:.4f}", f"{lat:.1f}s"]
        out.append("| " + " | ".join(cells) + " |")
    return out


def main() -> None:
    runs = {n: json.loads((RESULTS / f"{n}.json").read_text(encoding="utf-8")) for n in RUNS}
    by_cat: dict[str, dict[str, list[dict]]] = {}
    for run in runs.values():
        for cfg, rows in run["items"].items():
            for r in rows:
                by_cat.setdefault(r["category"], {}).setdefault(cfg, []).append(r)

    order = lambda d: dict(sorted(d.items(), key=lambda kv: (kv[0].split("/")[0], kv[0])))  # noqa: E731
    out = ["### Core set: 40 questions, metrics spelled out in the question", ""]
    out += table(order(by_cat["core"]), by_difficulty=True)
    out += ["", "### Glossary set: 12 questions using undefined business terms", ""]
    out += table(order(by_cat["glossary"]), by_difficulty=False)
    out += [
        "",
        "### Ambiguity set: 5 should get a clarifying question, 3 have a cue and should be answered",
        "",
    ]
    out += table(order(by_cat["ambiguous"]), by_difficulty=False)
    spent = sum(r["spent_usd"] for r in runs.values())
    out += ["", f"Spend for these runs: **${spent:.3f}** (each run had its own hard cap)."]
    print("\n".join(out))


if __name__ == "__main__":
    main()
