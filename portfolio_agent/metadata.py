"""Metadata the model needs: schema cards, a business glossary and entity linking.

`EntityLinker` maps loose wording ("international equity") to exact database values.
`SchemaCatalog` renders compact table cards generated from the live database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .db import LOAD_ORDER, connect_readonly

# Only short, curated vocabularies are copied from the data into prompts. Free-text
# columns such as transactions.notes are excluded so stored text can never act as a
# prompt injection.
ENUM_COLUMNS = {
    "portfolios": ("portfolio_name", "target_risk_level", "strategy_type", "status"),
    "sectors": ("sector_name",),
    "securities": ("asset_type", "exchange", "country", "currency"),
    "transactions": ("transaction_type",),
    "benchmarks": ("benchmark_type",),
}

COLUMN_NOTES = {
    "holdings.current_weight": "fraction of portfolio, 0-1",
    "holdings.cost_basis": "quantity x purchase_price",
    "securities.market_cap": "USD millions",
    "securities.sector_id": "NULL for bonds",
    "securities.coupon_rate": "percent, bonds only",
    "securities.maturity_date": "bonds only",
    "portfolio_performance.total_return_1m": "percent; same for 3m, 6m, 1y",
    "portfolio_performance.volatility": "percent",
    "portfolio_performance.max_drawdown": "percent, negative",
    "risk_metrics.var_95": "percent, negative; same for var_99, cvar_95",
    "portfolios.benchmark_index": "matches benchmarks.benchmark_symbol only for some rows",
}

GLOSSARY = """\
- market value of a holding = holdings.quantity * securities.current_price. "Value" of a portfolio or \
holding means this, not total_aum and not cost_basis.
- percentage of portfolio value = market value share, unless the question says "weight".
- diversification metrics = number of distinct equity sectors, total number of holdings, and \
diversification_ratio = sector count / total holdings. Only Stock rows have a sector.
- portfolio_performance and risk_metrics are daily series for only some portfolios. A question about the \
current or latest figure must filter to the latest date for that portfolio, never mix dates or average them \
unless asked.
- portfolio_performance holds NAV, returns, volatility, Sharpe ratio and max drawdown. risk_metrics holds VaR, \
CVaR, beta, correlation, tracking error, information ratio and Sortino ratio.
- "holdings" listings show holding_id, symbol, company_name, quantity and the requested metric."""

_GENERIC_NAME_TOKENS = frozenset(
    [
        "fund",
        "portfolio",
        "index",
        "total",
        "market",
        "plus",
        "the",
        "stock",
        "bond",
        "equity",
        "value",
        "cap",
        "small",
        "income",
    ]
)
_COMPANY_SUFFIXES = frozenset(["inc", "corp", "corporation", "co", "company", "plc", "ltd", "the", "com"])
_SECTOR_ALIASES = {
    "tech": "Technology",
    "financial": "Financials",
    "health care": "Healthcare",
    "staples": "Consumer Staples",
    "discretionary": "Consumer Discretionary",
    "auto": "Automotive",
    "autos": "Automotive",
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Links:
    """Result of linking a question to database entities."""

    portfolios: list[str] = field(default_factory=list)  # Confident matches.
    candidates: list[str] = field(default_factory=list)  # Partial matches needing judgement.
    sectors: list[str] = field(default_factory=list)
    securities: list[str] = field(default_factory=list)  # "AAPL (Apple Inc.)"


class EntityLinker:
    def __init__(
        self,
        portfolio_names: list[str],
        sector_names: list[str],
        securities: list[tuple[str, str]] = (),
        typo_cutoff: float = 0.88,
    ):
        self._securities: dict[str, str] = {}
        for symbol, company in securities:
            label = f"{symbol} ({company})"
            self._securities[" ".join(tokens(symbol))] = label
            brand = [w for w in tokens(company) if w not in _COMPANY_SUFFIXES]
            if brand:
                self._securities[" ".join(brand)] = label
                self._securities[brand[0]] = label
        self._aliases: list[tuple[list[str], str]] = []
        for name in portfolio_names:
            full = tokens(name)
            self._aliases.append((full, name))
            if full[-1] in {"fund", "portfolio"}:
                self._aliases.append((full[:-1], name))
        self._aliases.sort(key=lambda item: -len(item[0]))
        self._sector_map = {" ".join(tokens(s)): s for s in sector_names}
        self._sector_map.update(_SECTOR_ALIASES)
        self._typo_cutoff = typo_cutoff

    def link(self, question: str) -> Links:
        words = tokens(question)
        links = Links()
        covered = [False] * len(words)
        for alias, name in self._aliases:
            for start in range(len(words) - len(alias) + 1):
                span = range(start, start + len(alias))
                if any(covered[i] for i in span):
                    continue
                window = words[start : start + len(alias)]
                similar = " ".join(window) == " ".join(alias)
                # Single words are too short for fuzzy matching to be trustworthy.
                if not similar and len(alias) >= 2:
                    ratio = SequenceMatcher(None, " ".join(window), " ".join(alias)).ratio()
                    similar = ratio >= self._typo_cutoff
                if similar:
                    for i in span:
                        covered[i] = True
                    if name not in links.portfolios:
                        links.portfolios.append(name)
        open_words = {w for w, used in zip(words, covered, strict=False) if not used} - _GENERIC_NAME_TOKENS
        for alias, name in self._aliases:
            if open_words & set(alias) and name not in links.portfolios and name not in links.candidates:
                links.candidates.append(name)
        # Only words outside portfolio names count, so "Tech Innovation Fund" is not a sector.
        free_text = " ".join("|" if used else word for word, used in zip(words, covered, strict=False))
        for key, sector in self._sector_map.items():
            if re.search(rf"\b{re.escape(key)}\b", free_text) and sector not in links.sectors:
                links.sectors.append(sector)
        for key, label in self._securities.items():
            if re.search(rf"\b{re.escape(key)}\b", free_text) and label not in links.securities:
                links.securities.append(label)
        return links

    def resolve(self, name: str) -> tuple[str | None, list[str]]:
        """Map a portfolio reference to (exact name, []) or (None, candidates)."""
        links = self.link(name)
        if len(links.portfolios) == 1:
            return links.portfolios[0], []
        if links.portfolios:
            return None, links.portfolios
        if len(links.candidates) == 1:
            return links.candidates[0], []
        return None, links.candidates


class SchemaCatalog:
    """Prompt-ready description of the database, generated from the database itself."""

    def __init__(self, db_path: Path):
        conn = connect_readonly(db_path)
        self.cards: dict[str, str] = {}
        try:
            for table in LOAD_ORDER:
                self.cards[table] = self._card(conn, table)
            self.portfolio_names = [r[0] for r in conn.execute("SELECT portfolio_name FROM portfolios ORDER BY 1")]
            self.sector_names = [r[0] for r in conn.execute("SELECT sector_name FROM sectors ORDER BY 1")]
            self.securities = [
                (r[0], r[1])
                for r in conn.execute("SELECT symbol, company_name FROM securities WHERE asset_type = 'Stock'")
            ]
        finally:
            conn.close()

    @staticmethod
    def _card(conn, table: str) -> str:
        parts = []
        foreign = {fk[3]: f"{fk[2]}.{fk[4]}" for fk in conn.execute(f"PRAGMA foreign_key_list({table})")}
        for _, column, kind, _, _, is_pk in conn.execute(f"PRAGMA table_info({table})"):
            piece = f"{column} {kind}"
            if is_pk:
                piece += " PK"
            if column in foreign:
                piece += f" FK->{foreign[column]}"
            if column in ENUM_COLUMNS.get(table, ()):
                values = [r[0] for r in conn.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY 1")]
                piece += " in {" + ", ".join(str(v) for v in values) + "}"
            note = COLUMN_NOTES.get(f"{table}.{column}")
            if note:
                piece += f" [{note}]"
            parts.append(piece)
        return f"{table}({'; '.join(parts)})"

    def render(self) -> str:
        return "\n".join(self.cards[t] for t in LOAD_ORDER)
