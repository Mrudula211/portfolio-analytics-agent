"""Database build (CSV -> SQLite file) and a hardened, read-only execution layer.

Defence in depth for model-generated SQL; the layers in this file are enforced by
the SQLite engine itself, independent of any parsing done in ``sql_guard``:
  1. read-only URI connection (mode=ro) + PRAGMA query_only
  2. authorizer callback: only SELECT/READ on allow-listed tables + allow-listed functions
  3. progress handler: deterministic VM-instruction budget (acts as a timeout)
  4. row cap on fetched results
"""
from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

TABLES = (
    "sectors", "securities", "portfolios", "holdings", "transactions",
    "historical_prices", "portfolio_performance", "risk_metrics", "benchmarks",
)
# Parent tables first so foreign keys are satisfiable during load.
LOAD_ORDER = TABLES

ALLOWED_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "total", "round", "abs", "coalesce", "ifnull",
    "nullif", "lower", "upper", "length", "substr", "substring", "trim", "ltrim", "rtrim",
    "replace", "instr", "date", "datetime", "strftime", "julianday", "group_concat",
    "printf", "format", "iif", "like", "glob", "cast", "sqrt", "power", "pow", "ln", "log",
    "exp", "floor", "ceil", "ceiling", "sign", "row_number", "rank", "dense_rank", "lag",
    "lead", "ntile", "first_value", "last_value", "percent_rank", "cume_dist", "typeof",
}


class DatabaseError(Exception):
    """Execution failed for a reason the model may be able to fix (syntax, unknown column)."""


class SecurityViolation(Exception):
    """Statement attempted something outside the read-only contract. Never retried."""


class ResourceLimitExceeded(Exception):
    """Query exceeded the VM-step budget."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False
    vm_steps: int = 0
    elapsed_ms: float = 0.0
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- build
def build_database(db_path: Path = config.DB_PATH, force: bool = False) -> Path:
    """Create the SQLite file from schema + CSVs. Idempotent; source files are never modified."""
    sources = [config.SCHEMA_PATH, *config.DATA_DIR.glob("*.csv")]
    if db_path.exists() and not force:
        newest_source = max(p.stat().st_mtime for p in sources)
        if db_path.stat().st_mtime >= newest_source:
            return db_path
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
        for table in LOAD_ORDER:
            path = config.DATA_DIR / f"{table}.csv"
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader)
                # Empty CSV cells become NULL (e.g. bond sector_id, stock maturity_date).
                rows = [[v if v != "" else None for v in r] for r in reader]
            cols = ", ".join(header)
            marks = ", ".join("?" * len(header))
            conn.executemany(f"INSERT INTO {table} ({cols}) VALUES ({marks})", rows)
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"Foreign-key violations in source data: {bad[:5]}")
        conn.commit()
    finally:
        conn.close()
    tmp.replace(db_path)
    return db_path


# --------------------------------------------------------------------------- read-only access
def _authorizer(action, arg1, arg2, _db, _trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if (arg1 or "").lower() in TABLES else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if (arg2 or "").lower() in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, INSERT, UPDATE, DELETE, CREATE, DROP, ...


class ReadOnlyDatabase:
    """Single hardened connection used for every model-generated statement."""

    STEP_GRANULARITY = 10

    def __init__(self, db_path: Path = config.DB_PATH, max_steps: int = config.MAX_VM_STEPS):
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database not found at {db_path}. Run: python agent.py --build-db")
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.conn.execute("PRAGMA query_only = ON")
        self.conn.set_authorizer(_authorizer)
        self.max_steps = max_steps
        self._ticks = 0

    def _progress(self) -> int:
        self._ticks += 1
        return 1 if self._ticks * self.STEP_GRANULARITY > self.max_steps else 0

    def execute(self, sql: str, params: tuple = (), max_rows: int = config.MAX_ROWS) -> QueryResult:
        self._ticks = 0
        self.conn.set_progress_handler(self._progress, self.STEP_GRANULARITY)
        start = time.perf_counter()
        try:
            cur = self.conn.execute(sql, params)
            rows = cur.fetchmany(max_rows + 1)
            columns = [d[0] for d in (cur.description or [])]
        except sqlite3.DatabaseError as exc:
            msg = str(exc)
            if self._ticks * self.STEP_GRANULARITY > self.max_steps or "interrupted" in msg:
                raise ResourceLimitExceeded(f"query exceeded {self.max_steps:,} VM steps") from exc
            if any(k in msg for k in ("not authorized", "prohibited", "readonly", "query_only")):
                raise SecurityViolation(msg) from exc
            if isinstance(exc, sqlite3.Warning) or "one statement at a time" in msg:
                raise SecurityViolation("multiple statements are not allowed") from exc
            raise DatabaseError(msg) from exc
        except sqlite3.Warning as exc:  # multiple statements
            raise SecurityViolation("multiple statements are not allowed") from exc
        finally:
            self.conn.set_progress_handler(None, 0)
        elapsed = (time.perf_counter() - start) * 1000
        truncated = len(rows) > max_rows
        return QueryResult(columns, rows[:max_rows], truncated, self._ticks * self.STEP_GRANULARITY, elapsed)

    def query_plan(self, sql: str) -> list[str]:
        """EXPLAIN QUERY PLAN details (used for efficiency diagnostics)."""
        try:
            return [r[-1] for r in self.conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall()]
        except sqlite3.DatabaseError:
            return []

    def close(self) -> None:
        self.conn.close()
