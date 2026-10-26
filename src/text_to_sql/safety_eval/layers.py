"""Defense configurations and running one SQL string through one of them on a disposable database."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..db.duckdb_backend import TPCH_TABLES
from ..safety.guard import GuardError, SqlGuard
from .hardened_guard import HardenedSqlGuard
from .sandbox import Trial, detect_harms, execute, persistent_fingerprint, session_fingerprint

MAX_ROWS = 200


@dataclass(frozen=True)
class Config:
    name: str
    guard: str  # "none" | "baseline" | "hardened" | "strict"
    read_only: bool
    description: str


CONFIGS: tuple[Config, ...] = (
    Config("none", "none", False, "no guard, ordinary connection"),
    Config("ro_only", "none", True, "read-only, external access off, config locked (layer 2 only)"),
    Config("guard_only", "baseline", False, "current SqlGuard on an ordinary connection (layer 1 only)"),
    Config("guard+ro", "baseline", True, "current production setting (both layers)"),
    Config("hardened+ro", "hardened", True, "scoped CTEs + parser agreement, both layers"),
    Config("strict+ro", "strict", True, "hardened + function allowlist, both layers"),
)
CONFIG_BY_NAME = {c.name: c for c in CONFIGS}


def make_guard(kind: str) -> SqlGuard | None:
    tables = set(TPCH_TABLES)
    if kind == "none":
        return None
    if kind == "baseline":
        return SqlGuard(tables, "duckdb", max_rows=MAX_ROWS)
    if kind == "hardened":
        return HardenedSqlGuard(tables, "duckdb", max_rows=MAX_ROWS)
    if kind == "strict":
        return HardenedSqlGuard(tables, "duckdb", max_rows=MAX_ROWS, function_allowlist=True)
    raise ValueError(kind)


@dataclass
class Outcome:
    config: str
    guard_verdict: str  # "allow" | "block" (policy) | "reject" (retryable) | "n/a"
    guard_message: str | None
    executed_sql: str | None
    ran: bool
    error: str | None
    timed_out: bool
    harms: list[str]
    n_rows: int
    sample: list[list[str]] = field(default_factory=list)
    rows: list[tuple] | None = None  # kept in memory for accuracy checks, not serialized

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("rows")
        return d


def run_sql(
    sql: str,
    config: Config,
    source_db: Path,
    restricted: frozenset[str],
    *,
    timeout_s: float = 5.0,
    template: bool = True,
    keep_rows: bool = False,
) -> Outcome:
    guard = make_guard(config.guard)
    with Trial(source_db, restricted) as trial:
        if template:
            for k, v in trial.template_vars().items():
                sql = sql.replace("{" + k + "}", v)
        persistent_before = persistent_fingerprint(trial.db_path)
        verdict, message, to_run = "n/a", None, sql
        if guard is not None:
            try:
                to_run = guard.check(sql).sql
                verdict = "allow"
            except GuardError as e:
                verdict, message, to_run = ("reject" if e.retryable else "block"), str(e), None
        con = trial.connect(read_only=config.read_only)
        try:
            session_before = session_fingerprint(con)
            if to_run is not None:
                ex = execute(con, to_run, timeout_s=timeout_s, max_rows=MAX_ROWS)
            else:
                from .sandbox import Execution

                ex = Execution()
            session_after = session_fingerprint(con)
        finally:
            con.close()
        persistent_after = persistent_fingerprint(trial.db_path)
        harms = detect_harms(trial, ex, persistent_before, persistent_after, session_before, session_after)
        return Outcome(
            config=config.name,
            guard_verdict=verdict,
            guard_message=message,
            executed_sql=to_run,
            ran=ex.ran,
            error=ex.error,
            timed_out=ex.timed_out,
            harms=harms,
            n_rows=len(ex.rows),
            sample=[[str(v)[:60] for v in r] for r in ex.rows[:2]],
            rows=ex.rows if keep_rows else None,
        )
