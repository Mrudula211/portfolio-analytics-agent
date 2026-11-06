"""Sector Exposure Calculator (deterministic, parameterised SQL; no LLM involvement).

Exposure = SUM(holdings.current_weight) per sector over EQUITY holdings only (bonds excluded).
Two views are reported:
  * pct_of_equity    - normalised over the equity sleeve, sums to 100% (primary, per the brief:
                       "ignore bond holdings ... only consider the equities")
  * pct_of_portfolio - share of the whole portfolio, shows true economic exposure when bonds exist
A reconciliation footer accounts for every unit of weight (equity + bonds + unallocated = 100%).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import ReadOnlyDatabase

TOLERANCE_PP = 0.01


@dataclass
class ExposureResult:
    portfolio_id: int
    portfolio_name: str
    rows: list[tuple[str, float, float]]            # (sector, pct_of_equity, pct_of_portfolio)
    equity_weight: float
    bond_weight: float
    total_weight: float
    warnings: list[str] = field(default_factory=list)

    @property
    def unallocated_weight(self) -> float:
        return round(1.0 - self.total_weight, 6)

    def as_table(self) -> tuple[list[str], list[tuple]]:
        return ["sector", "exposure_pct_of_equity", "exposure_pct_of_portfolio"], self.rows


SECTOR_SQL = """
SELECT COALESCE(sec.sector_name, 'Unclassified') AS sector, SUM(h.current_weight) AS weight
FROM holdings h
JOIN securities s ON s.security_id = h.security_id
LEFT JOIN sectors sec ON sec.sector_id = s.sector_id
WHERE h.portfolio_id = ? AND s.asset_type = 'Stock'
GROUP BY COALESCE(sec.sector_name, 'Unclassified')
"""
TOTALS_SQL = """
SELECT
  COALESCE(SUM(CASE WHEN s.asset_type = 'Stock' THEN h.current_weight END), 0),
  COALESCE(SUM(CASE WHEN s.asset_type = 'Bond'  THEN h.current_weight END), 0),
  COALESCE(SUM(h.current_weight), 0)
FROM holdings h JOIN securities s ON s.security_id = h.security_id
WHERE h.portfolio_id = ?
"""


class ExposureError(Exception):
    pass


def calculate_sector_exposure(db: ReadOnlyDatabase, portfolio_id: int) -> ExposureResult:
    found = db.execute("SELECT portfolio_name FROM portfolios WHERE portfolio_id = ?", (portfolio_id,)).rows
    if not found:
        raise ExposureError(f"portfolio_id {portfolio_id} does not exist")
    name = found[0][0]
    equity, bonds, total = db.execute(TOTALS_SQL, (portfolio_id,)).rows[0]
    warnings: list[str] = []
    if total == 0:
        raise ExposureError(f"{name} has no holdings")
    if abs(total - 1.0) > 1e-6:
        warnings.append(f"Holding weights sum to {total * 100:.2f}% (unallocated {100 - total * 100:.2f}%); not rescaled.")
    if equity == 0:
        warnings.append(f"{name} holds no equities (bonds {bonds * 100:.2f}%); sector exposure is not applicable.")
        return ExposureResult(portfolio_id, name, [], 0.0, bonds, total, warnings)
    if bonds > 0:
        warnings.append(f"Excluded bond holdings: {bonds * 100:.2f}% of portfolio weight.")

    raw = db.execute(SECTOR_SQL, (portfolio_id,)).rows
    rows = sorted(
        ((sector, round(w / equity * 100, 4), round(w * 100, 4)) for sector, w in raw if w),
        key=lambda r: (-r[1], r[0]),
    )
    if any(r[0] == "Unclassified" for r in rows):
        warnings.append("Some equities have no sector mapping and are shown as 'Unclassified'.")

    # Self-check: the equity view must sum to 100% and reconcile with the totals.
    eq_sum = sum(r[1] for r in rows)
    if abs(eq_sum - 100) > TOLERANCE_PP * len(rows) + 1e-9:
        raise ExposureError(f"internal reconciliation failed: equity exposures sum to {eq_sum:.4f}%")
    return ExposureResult(portfolio_id, name, rows, equity, bonds, total, warnings)
