"""Run the execution-accuracy eval across (model x schema mode) configurations."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .db.base import Backend, QueryResult
from .evaluation import DIFFICULTIES, EvalItem, gold_tables, results_match
from .llm.client import LLM
from .llm.cost import BudgetExceeded, BudgetGuard
from .pipeline import Answer, Assistant
from .schema.catalog import Catalog
from .schema.glossary import Glossary
from .schema.retriever import SchemaRetriever


@dataclass(frozen=True)
class Config:
    model: str
    schema_mode: str  # "full" | "retrieved"
    glossary: bool = False

    @property
    def name(self) -> str:
        return f"{self.model}/{self.schema_mode}" + ("+glossary" if self.glossary else "")


@dataclass
class ItemResult:
    id: str
    difficulty: str
    category: str
    correct: bool
    sql: str | None
    error: str | None
    cannot_answer: str | None
    clarification: str | None
    blocked: bool
    retried: bool
    tables: list[str]
    gold_tables: list[str]
    retrieval_recall: bool | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    elapsed_s: float


@dataclass
class RunResult:
    started: str
    configs: list[str]
    items: dict[str, list[ItemResult]] = field(default_factory=dict)
    stopped_reason: str | None = None
    budget_cap_usd: float = 0.0
    spent_usd: float = 0.0

    def to_json(self) -> dict:
        return {
            "started": self.started,
            "configs": self.configs,
            "stopped_reason": self.stopped_reason,
            "budget_cap_usd": self.budget_cap_usd,
            "spent_usd": round(self.spent_usd, 6),
            "items": {k: [asdict(r) for r in v] for k, v in self.items.items()},
        }


def score(item: EvalItem, ans: Answer, gold: QueryResult | None) -> bool:
    if item.expect_clarification:
        return ans.clarification is not None
    if ans.clarification is not None or not ans.ok or gold is None:
        return False
    return results_match(ans.result.rows, gold.rows, order_matters=item.order_matters)


def run_eval(
    items: list[EvalItem],
    configs: list[Config],
    *,
    backend: Backend,
    catalog: Catalog,
    retriever: SchemaRetriever | None,
    make_llm: Callable[[str, BudgetGuard], LLM],
    budget: BudgetGuard,
    out_path: Path | None = None,
    top_k: int = 4,
    progress: Callable[[str], None] = print,
    assistant_kwargs: dict | None = None,
    glossary: Glossary | None = None,
) -> RunResult:
    run = RunResult(
        started=dt.datetime.now().isoformat(timespec="seconds"),
        configs=[c.name for c in configs],
        budget_cap_usd=budget.cap_usd,
    )
    golds: dict[str, QueryResult | None] = {}
    for it in items:
        golds[it.id] = backend.execute(it.gold_sql, max_rows=10_000, timeout_s=60) if it.gold_sql else None

    try:
        for cfg in configs:
            llm = make_llm(cfg.model, budget)
            assistant = Assistant(
                backend,
                catalog,
                llm,
                retriever,
                top_k=top_k,
                max_rows=1000,
                timeout_s=30,
                glossary=glossary if cfg.glossary else None,
                **(assistant_kwargs or {}),
            )
            results = run.items.setdefault(cfg.name, [])
            for it in items:
                ans = assistant.ask(it.question, schema_mode=cfg.schema_mode)
                gt = sorted(gold_tables(it.gold_sql, backend.dialect)) if it.gold_sql else []
                ok = score(it, ans, golds[it.id])
                recall = set(gt) <= set(ans.tables) if cfg.schema_mode == "retrieved" and gt else None
                u = ans.usage
                results.append(
                    ItemResult(
                        id=it.id,
                        difficulty=it.difficulty,
                        category=it.category,
                        correct=ok,
                        sql=ans.sql,
                        error=ans.error,
                        cannot_answer=ans.cannot_answer,
                        clarification=ans.clarification.question if ans.clarification else None,
                        blocked=ans.blocked,
                        retried=ans.retried,
                        tables=ans.tables,
                        gold_tables=gt,
                        retrieval_recall=recall,
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_input_tokens,
                        cache_write_tokens=u.cache_creation_input_tokens,
                        cost_usd=ans.cost_usd,
                        elapsed_s=round(ans.elapsed_s, 2),
                    )
                )
                run.spent_usd = budget.spent_usd
                mark = "ok " if ok else "ERR" if ans.error else "?  " if ans.clarification else "x  "
                progress(
                    f"[{cfg.name}] {it.id} {mark} retry={int(ans.retried)} "
                    f"${ans.cost_usd:.4f} total=${budget.spent_usd:.4f}"
                )
                if out_path:
                    _save(run, out_path)
    except BudgetExceeded as e:
        run.stopped_reason = str(e)
        progress(f"STOPPED: {e}")
    run.spent_usd = budget.spent_usd
    if out_path:
        _save(run, out_path)
    return run


def _save(run: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_json(), indent=1), encoding="utf-8")


# --- reporting ---


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "-"


def summarize(run_json: dict) -> str:
    """Markdown summary tables from a saved run."""
    lines = []
    items = run_json["items"]
    cats = sorted({r["category"] for rs in items.values() for r in rs})
    for cat in cats:
        title = {"core": "Core set", "glossary": "Glossary set", "ambiguous": "Ambiguity set"}.get(cat, cat)
        lines.append(f"### {title}\n")
        lines.append("| Config | Easy | Medium | Hard | **Overall** | Retried | Retrieval recall | Cost |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for cfg, rs in items.items():
            rs = [r for r in rs if r["category"] == cat]
            if not rs:
                continue
            cells = []
            for d in DIFFICULTIES:
                sub = [r for r in rs if r["difficulty"] == d]
                cells.append(_pct(sum(r["correct"] for r in sub), len(sub)))
            overall = _pct(sum(r["correct"] for r in rs), len(rs))
            retried = sum(r["retried"] for r in rs)
            rec = [r["retrieval_recall"] for r in rs if r["retrieval_recall"] is not None]
            recall = _pct(sum(rec), len(rec)) if rec else "n/a"
            cost = sum(r["cost_usd"] for r in rs)
            lines.append(
                f"| `{cfg}` | {' | '.join(cells)} | **{overall}** | {retried} | {recall} | ${cost:.3f} |"
            )
        lines.append("")
    total = run_json["spent_usd"]
    lines.append(f"Total spend: **${total:.3f}** (cap ${run_json['budget_cap_usd']:.2f}).")
    if run_json.get("stopped_reason"):
        lines.append(f"\n**Run stopped early:** {run_json['stopped_reason']}")
    return "\n".join(lines)


def failures(run_json: dict) -> str:
    out = ["| Config | Question | Outcome |", "|---|---|---|"]
    for cfg, rs in run_json["items"].items():
        for r in rs:
            if r["correct"]:
                continue
            if r.get("clarification"):
                why = f"asked instead of answering: {r['clarification'][:80]}"
            elif r["category"] == "ambiguous" and not r["gold_tables"]:
                why = "answered instead of asking for clarification"
            elif r["cannot_answer"]:
                why = f"declined: {r['cannot_answer'][:80]}"
            elif r["error"]:
                why = f"error: {r['error'][:80]}"
            elif r["retrieval_recall"] is False:
                missing = sorted(set(r["gold_tables"]) - set(r["tables"]))
                why = f"wrong result; retrieval missed {', '.join(missing)}"
            else:
                why = "ran, wrong result"
            out.append(f"| `{cfg}` | {r['id']} | {why.replace('|', '/')} |")
    return "\n".join(out)
