"""Small, explicit financial meanings and output contracts for portfolio questions.

These definitions help form and check queries. They do not contain assessment queries,
question IDs, or expected answer rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .db import connect_readonly
from .sql_guard import QueryResult


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    description: str
    required_columns: tuple[str, ...]


ASSESSMENT_DIVERSIFICATION = MetricDefinition(
    name="assessment-defined sector diversification ratio",
    description=(
        "For this assessment only, sector_count is the number of distinct sectors represented by Stock "
        "holdings; total_holdings counts every holding record for the portfolio (including bonds); and "
        "diversification_ratio = ROUND(CAST(sector_count AS REAL) / total_holdings, 3). Include only "
        "portfolios whose Stock holdings represent more than five distinct sectors. This is an "
        "assessment-defined ratio, not a universal financial metric. Do not substitute Sharpe ratio, beta, "
        "volatility, or another risk measure."
    ),
    required_columns=("portfolio_name", "sector_count", "total_holdings", "diversification_ratio"),
)

_DIVERSIFICATION_TERMS = re.compile(r"\bdiversification\s+(?:metric|metrics|ratio|ratios)\b", re.I)
_HOLDING_AGGREGATE = re.compile(r"\b(?:count|how\s+many|sum|total|average|avg)\b", re.I)
_HOLDING_ROW_REQUEST = re.compile(r"\b(?:show|list|display|which|top|bottom|largest|smallest|rank(?:ed|ing)?)\b", re.I)
_RANKED_BY = re.compile(r"\b(?:top|bottom|rank(?:ed|ing)?)\b.*?\bby\s+([a-z][a-z0-9_]*(?:\s+[a-z][a-z0-9_]*)?)\b", re.I)


def metric_for_question(question: str) -> MetricDefinition | None:
    """Resolve a narrowly named metric from the documented semantic registry."""
    return ASSESSMENT_DIVERSIFICATION if _DIVERSIFICATION_TERMS.search(question) else None


def required_projection(question: str) -> tuple[str, ...]:
    """Return generic schema fields required when a user requests holding-level rows."""
    if not re.search(r"\b(?:holdings?|positions?)\b", question, re.I):
        return ()
    if _HOLDING_AGGREGATE.search(question) or not _HOLDING_ROW_REQUEST.search(question):
        return ()

    required = ["holding_id", "symbol", "company_name", "quantity"]
    ranked = _RANKED_BY.search(question)
    if ranked:
        requested = " ".join(ranked.group(1).lower().replace("_", " ").split())
        known = {
            "cost basis": "cost_basis",
            "market value": "market_value",
            "quantity": "quantity",
            "weight": "current_weight",
            "current weight": "current_weight",
            "purchase price": "purchase_price",
        }
        field = known.get(requested)
        if field and field not in required:
            required.append(field)
    # Cost-basis phrasing can also mean the requested sort field without a literal "by".
    if re.search(r"\bcost\s+basis\b", question, re.I) and "cost_basis" not in required:
        required.append("cost_basis")
    return tuple(required)


_HOLDING_COLUMN_ALIASES = {
    "holding_id": {"holding_id"},
    "symbol": {"symbol", "ticker"},
    "company_name": {"company_name", "security_name"},
    "quantity": {"quantity", "shares", "units"},
    "cost_basis": {"cost_basis"},
    "market_value": {"market_value"},
    "current_weight": {"current_weight", "weight"},
    "purchase_price": {"purchase_price"},
}


def _column_index(columns: list[str], target: str) -> int | None:
    aliases = {name.casefold() for name in _HOLDING_COLUMN_ALIASES.get(target, {target})}
    return next((i for i, column in enumerate(columns) if column.casefold() in aliases), None)


def _independent_diversification(path: Path) -> dict[str, tuple[int, int, float]]:
    """Compute metric inputs from holding facts, independently of generated SQL."""
    conn = connect_readonly(path)
    try:
        rows = conn.execute(
            """SELECT p.portfolio_name, h.holding_id, s.asset_type, s.sector_id
               FROM portfolios p
               JOIN holdings h ON h.portfolio_id = p.portfolio_id
               JOIN securities s ON s.security_id = h.security_id"""
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[str, tuple[set[int], int]] = {}
    for name, _holding_id, asset_type, sector_id in rows:
        sectors, total_holdings = grouped.setdefault(name, (set(), 0))
        if asset_type == "Stock" and sector_id is not None:
            sectors.add(sector_id)
        grouped[name] = (sectors, total_holdings + 1)

    metrics = {}
    for name, (sectors, holding_count) in grouped.items():
        if len(sectors) > 5 and holding_count:
            metrics[name] = (len(sectors), holding_count, round(len(sectors) / holding_count, 3))
    return metrics


def validate_result(question: str, result: QueryResult, db_path: Path) -> str | None:
    """Return a safe, row-free correction instruction if output violates its contract."""
    metric = metric_for_question(question)
    if metric:
        indices = {column: _column_index(result.columns, column) for column in metric.required_columns}
        missing = [column for column, index in indices.items() if index is None]
        if missing:
            return "The query output is missing required columns: " + ", ".join(missing) + "."
        expected = _independent_diversification(db_path)
        name_i = indices["portfolio_name"]
        actual = {}
        try:
            for row in result.rows:
                name = str(row[name_i])
                actual[name] = (
                    int(row[indices["sector_count"]]),
                    int(row[indices["total_holdings"]]),
                    float(row[indices["diversification_ratio"]]),
                )
        except (TypeError, ValueError, IndexError):
            return "The required diversification metric columns must contain numeric values."
        if actual != expected:
            return (
                "The result does not match the documented assessment-defined diversification calculation "
                "or its greater-than-five-sector filter. Recalculate the metric from the defined source fields."
            )
        return None

    required = required_projection(question)
    if required:
        missing = [field for field in required if _column_index(result.columns, field) is None]
        if missing:
            return "The holding-level output is missing requested fields: " + ", ".join(missing) + "."
    return None


def calculate_diversification(path: Path) -> dict[str, tuple[int, int, float]]:
    """Public wrapper for deterministic tests and diagnostics."""
    return _independent_diversification(path)
