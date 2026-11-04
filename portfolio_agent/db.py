"""Build the SQLite database from the CSVs and audit the data it contains."""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

# Parents before children so foreign keys hold while loading.
LOAD_ORDER = (
    "sectors",
    "securities",
    "benchmarks",
    "portfolios",
    "holdings",
    "transactions",
    "historical_prices",
    "portfolio_performance",
    "risk_metrics",
)


class DataLoadError(RuntimeError):
    """The source CSVs cannot be loaded into a consistent database."""


def _load_csv(conn: sqlite3.Connection, table: str, path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        columns = ",".join(header)  # Header names come from the bundled files, not from users.
        marks = ",".join("?" * len(header))
        rows = ([value if value != "" else None for value in row] for row in reader)
        conn.executemany(f"INSERT INTO {table} ({columns}) VALUES ({marks})", rows)


def build_database(settings: Settings) -> Path:
    """Build atomically, so concurrent workers never see a half-written file."""
    target = settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
    os.close(handle)
    try:
        conn = sqlite3.connect(temp_name)
        try:
            conn.executescript(settings.schema_file.read_text(encoding="utf-8"))
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                for table in LOAD_ORDER:
                    _load_csv(conn, table, settings.data_dir / f"{table}.csv")
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise DataLoadError(f"Foreign key violations: {violations[:5]}")
            conn.execute("ANALYZE")  # Gives the query planner real statistics.
            conn.commit()
        except sqlite3.Error as exc:
            raise DataLoadError(f"Could not load data: {exc}") from exc
        finally:
            conn.close()
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    log.info("database_built path=%s", target)
    return target


def ensure_database(settings: Settings) -> Path:
    """Build the database if it is missing or older than its sources."""
    path = settings.db_path
    sources = [settings.schema_file, *settings.data_dir.glob("*.csv")]
    if path.exists() and all(path.stat().st_mtime >= src.stat().st_mtime for src in sources):
        return path
    return build_database(settings)


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open read-only at the file layer; one connection per query keeps threads independent."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def data_quality_findings(path: Path) -> list[str]:
    """Issues in the data itself that change how answers should be read."""
    conn = connect_readonly(path)
    findings: list[str] = []
    try:
        for name, total in conn.execute(
            "SELECT p.portfolio_name, ROUND(SUM(h.current_weight), 4) FROM holdings h "
            "JOIN portfolios p USING (portfolio_id) GROUP BY p.portfolio_id "
            "HAVING ABS(SUM(h.current_weight) - 1) > 0.001"
        ):
            findings.append(f"{name}: holding weights sum to {total}, not 1.0.")
        no_equity = [
            row[0]
            for row in conn.execute(
                "SELECT p.portfolio_name FROM portfolios p WHERE NOT EXISTS ("
                "SELECT 1 FROM holdings h JOIN securities s USING (security_id) "
                "WHERE h.portfolio_id = p.portfolio_id AND s.asset_type = 'Stock')"
            )
        ]
        if no_equity:
            findings.append(f"No equity holdings, so no sector exposure: {', '.join(no_equity)}.")
        low, high = conn.execute(
            "SELECT MIN(r), MAX(r) FROM (SELECT p.total_aum / SUM(h.quantity * s.current_price) r "
            "FROM portfolios p JOIN holdings h USING (portfolio_id) "
            "JOIN securities s USING (security_id) GROUP BY p.portfolio_id)"
        ).fetchone()
        findings.append(
            f"total_aum is {low:.0f}x to {high:.0f}x the value of listed holdings "
            "(quantity x current_price), so the two must not be mixed."
        )
        total = conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0]
        for table in ("portfolio_performance", "risk_metrics"):
            covered = conn.execute(f"SELECT COUNT(DISTINCT portfolio_id) FROM {table}").fetchone()[0]
            findings.append(f"{table} covers only {covered} of {total} portfolios.")
        empty = [
            row[0]
            for row in conn.execute(
                "SELECT sector_name FROM sectors WHERE sector_id NOT IN "
                "(SELECT sector_id FROM securities WHERE sector_id IS NOT NULL)"
            )
        ]
        if empty:
            findings.append(f"Sectors with no securities: {', '.join(empty)}.")
    finally:
        conn.close()
    return findings
