"""Execute untrusted, model-written SQL safely.

Layers, each covering a different failure:
1. The file is opened read-only with immutable=1.
2. An authorizer callback allows only SELECT on known tables and safe functions.
3. sqlite3 refuses to execute more than one statement per call.
4. A progress handler enforces time and work budgets; row and length limits cap output.

The authorizer inspects SQLite's compiled query, so comments, casing and other text
tricks that would slip past a regular expression cannot get around it.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .db import connect_readonly

_SQLITE_RECURSIVE = 33  # Not exported as a constant by every Python build.
_DENIED_FUNCTIONS = frozenset({"load_extension", "randomblob", "zeroblob", "fts3_tokenizer"})
_PROGRESS_TICK = 16  # VM instructions between progress callbacks.
_MAX_SQL_CHARS = 8000
_MAX_VALUE_BYTES = 1_000_000


class SQLGuardError(Exception):
    """Base class for rejected or failed queries."""


class SQLBlocked(SQLGuardError):
    """The query tried something forbidden. It must not be repaired or retried."""


class SQLExecutionError(SQLGuardError):
    """The query is allowed but invalid; the message is safe to send back for repair."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool = False
    elapsed_ms: float = 0.0
    vm_steps: int = 0
    full_scans: list[str] = field(default_factory=list)


def _authorizer(action: int, arg1, arg2, _db, _trigger) -> int:
    if action in (sqlite3.SQLITE_SELECT, _SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    # CTE names arrive here too (for COUNT(*) over a CTE), so internal tables are denied
    # by prefix rather than allowing a fixed list. Other names cannot exist in this file.
    if action == sqlite3.SQLITE_READ and not (arg1 or "").lower().startswith("sqlite_"):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() not in _DENIED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _open_guarded(path: Path, timeout_s: float, max_vm_steps: int) -> tuple[sqlite3.Connection, dict]:
    conn = connect_readonly(path)
    # Load the schema now, so the meter below counts only the query's own work.
    conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchall()
    conn.set_authorizer(_authorizer)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_VALUE_BYTES)
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, _MAX_SQL_CHARS)
    meter = {"ticks": 0}
    deadline = time.monotonic() + timeout_s

    def on_progress() -> int:
        meter["ticks"] += 1
        over_budget = meter["ticks"] * _PROGRESS_TICK > max_vm_steps
        return 1 if over_budget or time.monotonic() > deadline else 0

    conn.set_progress_handler(on_progress, _PROGRESS_TICK)
    return conn, meter


def _full_scans(conn: sqlite3.Connection, sql: str, params: tuple) -> list[str]:
    """Tables read without an index, taken from the query plan."""
    scans = []
    for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params):
        detail = str(row[-1])
        if detail.startswith("SCAN") and "USING" not in detail and "CONSTANT" not in detail:
            scans.append(detail.split()[1])
    return scans


def execute_select(
    path: Path,
    sql: str,
    params: tuple = (),
    *,
    max_rows: int = 1000,
    timeout_s: float = 2.0,
    max_vm_steps: int = 5_000_000,
) -> QueryResult:
    """Run one read-only query. Raises SQLBlocked or SQLExecutionError."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise SQLExecutionError("Empty query.")
    if len(statement) > _MAX_SQL_CHARS:
        raise SQLBlocked("Query is too long.")
    head = statement.split(None, 1)[0].upper()
    if head not in {"SELECT", "WITH"}:
        raise SQLBlocked(f"Only SELECT queries are allowed, got {head}.")

    conn, meter = _open_guarded(path, timeout_s, max_vm_steps)
    started = time.perf_counter()
    try:
        cursor = conn.execute(statement, params)
        if cursor.description is None:
            raise SQLBlocked("Statement did not produce a result set.")
        columns = [item[0] for item in cursor.description]
        rows = [list(row) for row in cursor.fetchmany(max_rows + 1)]
        steps = meter["ticks"] * _PROGRESS_TICK
        elapsed = (time.perf_counter() - started) * 1000
        scans = _full_scans(conn, statement, params)
    except sqlite3.ProgrammingError as exc:
        raise SQLBlocked("Only a single statement is allowed.") from exc
    except sqlite3.Warning as exc:  # Raised for multiple statements on older Pythons.
        raise SQLBlocked("Only a single statement is allowed.") from exc
    except sqlite3.Error as exc:
        message = str(exc)
        if "not authorized" in message or "prohibited" in message or "readonly" in message:
            raise SQLBlocked("Query uses an operation or object that is not allowed.") from exc
        if "interrupted" in message:
            raise SQLBlocked("Query exceeded its time or work budget.") from exc
        raise SQLExecutionError(message) from exc
    finally:
        conn.close()

    truncated = len(rows) > max_rows
    return QueryResult(columns, rows[:max_rows], truncated, elapsed, steps, scans)
