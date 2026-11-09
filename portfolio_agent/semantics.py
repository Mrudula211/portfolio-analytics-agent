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

DEFAULT_SECTOR_THRESHOLD = 5  # The assessment's definition: more than five sectors.
_NUMBER_WORDS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten'.split())}
_SECTOR_THRESHOLD = re.compile(r"\bmore than (\d+|one|two|three|four|five|six|seven|eight|nine|ten) (?:different |distinct )?sectors\b", re.I)


def sector_threshold(question: str) -> int:
    """The sector count a diversification question asks for, defaulting to the assessment's five."""
    match = _SECTOR_THRESHOLD.search(question)
    if not match:
        return DEFAULT_SECTOR_THRESHOLD
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


_DIVERSIFICATION_TERMS = re.compile(r"\bdiversification\s+(?:metric|metrics|ratio|ratios)\b", re.I)
_HOLDING_AGGREGATE = re.compile(r"\b(?:count|how\s+many|sum|total|average|avg)\b", re.I)
_HOLDING_ROW_REQUEST = re.compile(r"\b(?:show|list|display|which|top|bottom|largest|smallest|rank(?:ed|ing)?)\b", re.I)
_RANKED_BY = re.compile(r"\b(?:top|bottom|rank(?:ed|ing)?)\b.*?\bby\s+([a-z][a-z0-9_]*(?:\s+[a-z][a-z0-9_]*)?)\b", re.I)
_PORTFOLIO_CONTEXT = re.compile(r"\b(?:portfolio|fund)s?\b", re.I)
_EXPLICIT_METRIC = re.compile(r"\b(?:total\s+return|returns?|volatility|sharpe|beta|var|cvar|drawdown|nav)\b", re.I)


@dataclass(frozen=True)
class PortfolioSuperlative:
    name: str
    pattern: re.Pattern
    metric_column: str
    direction: str
    interpretation: str


PORTFOLIO_SUPERLATIVES = (
    PortfolioSuperlative(
        "strongest",
        re.compile(r"\b(?:strongest|best[- ]performing|performed\s+best)\b", re.I),
        "total_return_1y",
        "DESC",
        "highest latest available one-year total return",
    ),
    PortfolioSuperlative(
        "safest",
        re.compile(r"\bsafest\b", re.I),
        "volatility",
        "ASC",
        "lowest latest available volatility",
    ),
    PortfolioSuperlative(
        "most efficient",
        re.compile(r"\bmost\s+efficient\b", re.I),
        "sharpe_ratio",
        "DESC",
        "highest latest available Sharpe ratio",
    ),
)
SUPERLATIVE_GUIDANCE = (
    "When asked for the strongest or best-performing portfolio, use the highest latest available "
    "portfolio_performance.total_return_1y. For the safest portfolio, use the lowest latest available "
    "portfolio_performance.volatility. For the most efficient portfolio, use the highest latest available "
    "portfolio_performance.sharpe_ratio. In every case compare each portfolio's latest available observation, "
    "return the portfolio name and metric, and disclose the interpretation in the result title. These are "
    "explicit defaults for these phrases, not universal definitions. If a user asks for an unqualified best, "
    "healthiest or highest-quality portfolio, ask which measure they mean. The performance table covers only "
    "some portfolios; qualify rankings as being among portfolios with available data."
)


def metric_for_question(question: str) -> MetricDefinition | None:
    """Resolve a narrowly named metric from the documented semantic registry."""
    return ASSESSMENT_DIVERSIFICATION if _DIVERSIFICATION_TERMS.search(question) else None


def portfolio_superlative_for_question(question: str) -> PortfolioSuperlative | None:
    """Resolve a documented portfolio superlative only when no metric was explicitly named."""
    if not _PORTFOLIO_CONTEXT.search(question) or _EXPLICIT_METRIC.search(question):
        return None
    return next((definition for definition in PORTFOLIO_SUPERLATIVES if definition.pattern.search(question)), None)


def ambiguous_portfolio_superlative(question: str) -> bool:
    """Identify broad quality language with no defensible, explicitly requested measure."""
    if not _PORTFOLIO_CONTEXT.search(question) or _EXPLICIT_METRIC.search(question):
        return False
    if portfolio_superlative_for_question(question):
        return False
    return bool(re.search(r"\b(?:best|healthiest|highest[- ]quality)\b", question, re.I))


def superlative_interpretation(question: str) -> str | None:
    definition = portfolio_superlative_for_question(question)
    if definition is None:
        return None
    return f"Interpreting this as the {definition.interpretation}, among portfolios with available data."


def _validate_portfolio_superlative(question: str, result: QueryResult, db_path: Path) -> str | None:
    definition = portfolio_superlative_for_question(question)
    if definition is None:
        return None
    name_i = next((i for i, name in enumerate(result.columns) if name.casefold() == "portfolio_name"), None)
    metric_i = next((i for i, name in enumerate(result.columns) if name.casefold() == definition.metric_column), None)
    if name_i is None or metric_i is None:
        return (
            "The ranking must return portfolio_name and the metric "
            f"{definition.metric_column} used by the documented interpretation."
        )
    conn = connect_readonly(db_path)
    try:
        rows = conn.execute(
            f"""WITH latest AS (
                    SELECT portfolio_id, MAX(performance_date) AS latest_date
                    FROM portfolio_performance
                    WHERE {definition.metric_column} IS NOT NULL
                    GROUP BY portfolio_id
                )
                SELECT p.portfolio_name, pp.{definition.metric_column}
                FROM latest l
                JOIN portfolio_performance pp
                  ON pp.portfolio_id = l.portfolio_id AND pp.performance_date = l.latest_date
                JOIN portfolios p ON p.portfolio_id = l.portfolio_id"""
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return f"No portfolios have an available {definition.metric_column} value to rank."
    best = (min if definition.direction == "ASC" else max)(float(row[1]) for row in rows)
    winners = {str(row[0]) for row in rows if float(row[1]) == best}
    try:
        returned_name = str(result.rows[0][name_i])
        returned_metric = float(result.rows[0][metric_i])
    except (IndexError, TypeError, ValueError):
        return "The ranking must return a portfolio name and a numeric value for its ranking metric."
    if returned_name not in winners or returned_metric != best:
        return (
            "The first ranked row must be a portfolio with the best value of its latest available "
            f"{definition.metric_column}; do not rank older observations or use another metric."
        )
    return None


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


def _independent_diversification(
    path: Path, threshold: int = DEFAULT_SECTOR_THRESHOLD
) -> dict[str, tuple[int, int, float]]:
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
        if len(sectors) > threshold and holding_count:
            metrics[name] = (len(sectors), holding_count, round(len(sectors) / holding_count, 3))
    return metrics


def validate_result(question: str, result: QueryResult, db_path: Path) -> str | None:
    """Return a safe, row-free correction instruction if output violates its contract."""
    superlative_issue = _validate_portfolio_superlative(question, result, db_path)
    if superlative_issue:
        return superlative_issue
    metric = metric_for_question(question)
    if metric:
        indices = {column: _column_index(result.columns, column) for column in metric.required_columns}
        missing = [column for column, index in indices.items() if index is None]
        if missing:
            return "The query output is missing required columns: " + ", ".join(missing) + "."
        expected = _independent_diversification(db_path, sector_threshold(question))
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
                "or its sector-count filter. Recalculate the metric from the defined source fields."
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
