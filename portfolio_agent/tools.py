"""The agent's two tools. Each returns plain data; neither calls a model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Settings
from .metadata import EntityLinker
from .sql_guard import QueryResult, execute_select

# Bound parameters only: portfolio ids never get formatted into SQL text.
_EXPOSURE_SQL = """
SELECT COALESCE(sec.sector_name, 'Unclassified') AS sector_name,
       SUM(h.current_weight) AS weight,
       SUM(h.quantity * s.current_price) AS market_value,
       COUNT(*) AS holdings
FROM holdings h
JOIN securities s ON s.security_id = h.security_id
LEFT JOIN sectors sec ON sec.sector_id = s.sector_id
WHERE h.portfolio_id = ? AND s.asset_type = 'Stock'
GROUP BY sec.sector_id
ORDER BY weight DESC
"""
_TOTALS_SQL = """
SELECT COALESCE(SUM(h.current_weight), 0),
       COALESCE(SUM(CASE WHEN s.asset_type = 'Bond' THEN 1 ELSE 0 END), 0),
       COALESCE(SUM(CASE WHEN s.asset_type = 'Bond' THEN h.current_weight ELSE 0 END), 0)
FROM holdings h JOIN securities s ON s.security_id = h.security_id
WHERE h.portfolio_id = ?
"""
_WEIGHT_TOLERANCE = 0.001
_DRIFT_WARNING_POINTS = 5.0


class AmbiguousPortfolio(Exception):
    """The reference matches several portfolios, or none. `candidates` lists options."""

    def __init__(self, reference: str, candidates: list[str]):
        self.reference = reference
        self.candidates = candidates
        super().__init__(reference)


@dataclass
class SectorExposure:
    sector: str
    exposure_pct: float  # Share of the equity sleeve; sums to 100.
    portfolio_weight_pct: float  # Share of the whole portfolio, as recorded.
    market_value_pct: float  # Equity sleeve share implied by quantity x current_price.
    holdings: int


@dataclass
class ExposureResult:
    portfolio_name: str
    exposures: list[SectorExposure] = field(default_factory=list)
    equity_weight_pct: float = 0.0
    bond_weight_pct: float = 0.0
    bonds_excluded: int = 0
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    vm_steps: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class Tools:
    def __init__(self, settings: Settings, linker: EntityLinker):
        self._settings = settings
        self._linker = linker
        self._db: Path = settings.db_path

    def _select(self, sql: str, params: tuple = ()) -> QueryResult:
        return execute_select(
            self._db,
            sql,
            params,
            max_rows=self._settings.max_rows,
            timeout_s=self._settings.sql_timeout_s,
            max_vm_steps=self._settings.sql_max_vm_steps,
        )

    def run_sql(self, sql: str) -> QueryResult:
        """Convert-a-question tool: run model-written SQL through the guard."""
        return self._select(sql)

    def exposure_calculator(self, portfolio: str) -> ExposureResult:
        """Sector exposures of a portfolio's equity sleeve; bonds are excluded.

        Weights are normalised over equities so a mixed fund's exposures sum to 100%.
        The share of the whole portfolio and a market-value cross-check are returned too,
        because the two definitions differ and the data does not make them agree.
        """
        name, candidates = self._linker.resolve(portfolio)
        if name is None:
            raise AmbiguousPortfolio(portfolio, candidates)
        found = self._select("SELECT portfolio_id FROM portfolios WHERE portfolio_name = ?", (name,))
        portfolio_id = found.rows[0][0]
        rows = self._select(_EXPOSURE_SQL, (portfolio_id,))
        totals = self._select(_TOTALS_SQL, (portfolio_id,)).rows[0]
        total_weight, bond_count, bond_weight = totals

        result = ExposureResult(
            portfolio_name=name,
            bonds_excluded=int(bond_count),
            bond_weight_pct=round(bond_weight * 100, 4),
            elapsed_ms=rows.elapsed_ms,
            vm_steps=rows.vm_steps,
        )
        equity_weight = sum(row[1] or 0 for row in rows.rows)
        equity_value = sum(row[2] or 0 for row in rows.rows)
        result.equity_weight_pct = round(equity_weight * 100, 4)

        if not rows.rows or equity_weight <= 0:
            result.warnings.append(f"{name} holds no equities, so it has no sector exposure.")
            return result

        for sector, weight, value, holdings in rows.rows:
            result.exposures.append(
                SectorExposure(
                    sector=sector,
                    exposure_pct=round((weight or 0) / equity_weight * 100, 4),
                    portfolio_weight_pct=round((weight or 0) * 100, 4),
                    market_value_pct=round((value or 0) / equity_value * 100, 4) if equity_value else 0.0,
                    holdings=holdings,
                )
            )
        if abs(total_weight - 1) > _WEIGHT_TOLERANCE:
            result.warnings.append(
                f"Recorded weights sum to {total_weight * 100:.2f}%, not 100%. "
                "Exposures are normalised over the recorded equity weight."
            )
        if result.bonds_excluded:
            result.warnings.append(
                f"{result.bonds_excluded} bond holdings ({result.bond_weight_pct:.2f}% of the portfolio) "
                "are excluded; exposures are shares of the equity sleeve."
            )
        drift = max(abs(e.exposure_pct - e.market_value_pct) for e in result.exposures)
        if drift > _DRIFT_WARNING_POINTS:
            result.warnings.append(
                f"Recorded weights and market values disagree by up to {drift:.1f} points; "
                "the recorded weights may be stale."
            )
        return result
