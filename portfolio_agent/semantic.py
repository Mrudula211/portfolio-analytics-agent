"""Semantic layer: compact schema card + business rules given to the model,
and categorical value domains used to ground string literals in generated SQL."""
from __future__ import annotations

import re

from . import config
from .db import ReadOnlyDatabase

# Text columns whose literal values must exist in the data (case-sensitive in SQLite).
DOMAIN_COLUMNS = {
    "portfolios": ["portfolio_name", "target_risk_level", "strategy_type", "status", "benchmark_index"],
    "securities": ["symbol", "asset_type", "exchange", "country", "currency"],
    "sectors": ["sector_name", "industry_group"],
    "transactions": ["transaction_type"],
    "benchmarks": ["benchmark_symbol", "benchmark_type", "benchmark_name"],
}

BUSINESS_RULES = f"""
Business rules (authoritative):
- Data is synthetic and dated as of {config.DATA_AS_OF}. "Current" means the stored current_price / current_weight.
- portfolios.status is 'Active' or 'Passive' (Passive = index funds). Text values are case-sensitive Title Case.
- holdings.current_weight is a FRACTION of the portfolio (0.18 = 18%). Multiply by 100 for percentages.
- Market value of a holding = holdings.quantity * securities.current_price.
  "Portfolio value" computed from holdings means SUM(quantity * current_price). total_aum is the stated AUM; use it only when the question asks for AUM.
- cost_basis = quantity * purchase_price.
- securities.asset_type is 'Stock' or 'Bond'. Bonds have NULL sector_id and NULL market_cap.
- portfolios.benchmark_index matches benchmarks.benchmark_symbol (no FK).
- portfolio_performance and risk_metrics contain daily rows ONLY for portfolio_id 1-4, dates 2023-09-25..{config.DATA_AS_OF}.
  Their values are already in percent units (volatility 18.5 = 18.5%). For "latest" use the max date.
- Use exact portfolio names from the list below. Prefer explicit JOINs and only the columns needed.
""".strip()


def _schema_ddl() -> str:
    """Schema without comments/indexes: smaller prompt, same information."""
    text = config.SCHEMA_PATH.read_text(encoding="utf-8")
    text = re.sub(r"--[^\n]*", "", text)
    stmts = [s.strip() for s in text.split(";") if s.strip().upper().startswith("CREATE TABLE")]
    return ";\n".join(re.sub(r"\n\s*\n", "\n", s) for s in stmts) + ";"


class SemanticLayer:
    def __init__(self, db: ReadOnlyDatabase):
        self.domains: dict[str, set[str]] = {}
        for table, cols in DOMAIN_COLUMNS.items():
            for col in cols:
                vals = db.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL").rows
                self.domains.setdefault(col, set()).update(str(v[0]) for v in vals)
        self.portfolios = db.execute(
            "SELECT portfolio_id, portfolio_name, status, strategy_type FROM portfolios ORDER BY portfolio_id"
        ).rows
        self.schema = _schema_ddl()

    def card(self) -> str:
        enums = "\n".join(
            f"- {col}: {', '.join(sorted(vals))}"
            for col, vals in sorted(self.domains.items())
            if col not in ("symbol", "portfolio_name", "benchmark_name")
        )
        names = "\n".join(f"- {pid}: {name} ({status}, {strategy})" for pid, name, status, strategy in self.portfolios)
        return (
            f"SQLite schema:\n{self.schema}\n\n{BUSINESS_RULES}\n\n"
            f"Categorical values:\n{enums}\n\nPortfolios (id: name):\n{names}"
        )
