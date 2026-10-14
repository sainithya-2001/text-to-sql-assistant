"""Settings, read from the environment (and `.env` if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SNOWFLAKE_VARS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


@dataclass(frozen=True)
class Settings:
    backend: str = "duckdb"  # "duckdb" | "snowflake"
    duckdb_path: Path = PROJECT_ROOT / "data" / "tpch.duckdb"
    tpch_scale: float = 0.01
    model: str = "claude-sonnet-5-5"
    effort: str = "low"
    max_rows: int = 200
    timeout_s: float = 15.0
    top_k_tables: int = 4
    embedder: str = "fastembed"  # "fastembed" | "hash"
    glossary_path: Path = PROJECT_ROOT / "glossary.yaml"
    use_glossary: bool = True
    snowflake: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True) -> Settings:
        if load_dotenv_file and not os.environ.get("T2S_NO_DOTENV"):  # tests set T2S_NO_DOTENV
            load_dotenv(PROJECT_ROOT / ".env", override=False)
        snowflake = {k: os.environ[k] for k in SNOWFLAKE_VARS if os.environ.get(k)}
        backend = _env("T2S_BACKEND", "duckdb")
        if backend == "snowflake" and len(snowflake) < len(SNOWFLAKE_VARS):
            missing = [k for k in SNOWFLAKE_VARS if k not in snowflake]
            raise ValueError(f"T2S_BACKEND=snowflake but these are unset: {', '.join(missing)}")
        return cls(
            backend=backend,
            duckdb_path=Path(_env("T2S_DUCKDB_PATH", str(cls.duckdb_path))),
            tpch_scale=float(_env("T2S_TPCH_SCALE", str(cls.tpch_scale))),
            model=_env("T2S_MODEL", cls.model),
            effort=_env("T2S_EFFORT", cls.effort),
            max_rows=int(_env("T2S_MAX_ROWS", str(cls.max_rows))),
            timeout_s=float(_env("T2S_TIMEOUT_S", str(cls.timeout_s))),
            top_k_tables=int(_env("T2S_TOP_K", str(cls.top_k_tables))),
            embedder=_env("T2S_EMBEDDER", cls.embedder),
            glossary_path=Path(_env("T2S_GLOSSARY_PATH", str(cls.glossary_path))),
            use_glossary=_env("T2S_GLOSSARY", "on").lower() not in ("off", "0", "false", "no"),
            snowflake=snowflake,
        )

    @property
    def snowflake_available(self) -> bool:
        return len(self.snowflake) == len(SNOWFLAKE_VARS)
