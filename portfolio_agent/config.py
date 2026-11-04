"""Runtime settings, read once from the environment (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    # Chosen by measurement; see scripts/model_latency_benchmark.py and docs/DESIGN.md.
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: tuple[str, ...] = ("gemini-3.6-flash", "gemini-3.1-flash-lite")
    llm_timeout_s: float = 12.0
    llm_hedge_delay_s: float = 2.5
    schema_mode: str = "full"  # "full" or "retrieved"; see docs/DESIGN.md
    db_path: Path = ROOT / "portfolio_database.db"
    data_dir: Path = ROOT / "data"
    schema_file: Path = ROOT / "database_schema.sql"
    max_rows: int = 1000
    sql_timeout_s: float = 2.0
    sql_max_vm_steps: int = 5_000_000
    sql_repair_attempts: int = 1
    max_question_chars: int = 500
    cache_size: int = 512
    cache_ttl_s: float = 3600.0
    rate_limit_per_minute: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", cls.gemini_model),
            gemini_fallback_models=tuple(
                m.strip()
                for m in os.getenv("GEMINI_FALLBACK_MODELS", ",".join(cls.gemini_fallback_models)).split(",")
                if m.strip()
            ),
            schema_mode=os.getenv("SCHEMA_MODE", cls.schema_mode),
            rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute)),
        )
