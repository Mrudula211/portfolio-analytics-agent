"""Central configuration. Values come from environment variables / .env."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional at runtime
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "database_schema.sql"
GROUND_TRUTH_PATH = ROOT / "ground_truth_dataset.json"
DB_PATH = Path(os.getenv("PORTFOLIO_DB_PATH", ROOT / "portfolio_database.db"))
CACHE_PATH = ROOT / ".cache" / "decision_cache.json"
TRACE_PATH = ROOT / "logs" / "agent_trace.jsonl"
REPORT_DIR = ROOT / "evaluation" / "reports"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
PROMPT_VERSION = "v3"

MAX_ROWS = 500                 # result-size cap returned to the user
MAX_VM_STEPS = 20_000_000      # SQLite VM instruction budget (deterministic timeout)
MAX_SQL_REPAIRS = 2            # bounded self-correction attempts
MAX_QUESTION_CHARS = 1000

# Data "as of" date: last date present in historical_prices / performance tables.
DATA_AS_OF = "2023-10-09"


def api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
