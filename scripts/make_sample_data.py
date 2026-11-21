"""Generate the fictional sample dataset in sample_data/ (deterministic; every name and number is invented).

It has the same tables as the original assessment schema and reproduces the data quirks the agent must
handle: weights that do not sum to 100%, bond-only funds, performance data for a few funds only, and
total_aum far above the value of the listed holdings.

    python scripts/make_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data"
rng = random.Random(7)

SECTORS = [
    ("Technology", "Software, hardware and IT services", "Tech"),
    ("Consumer Discretionary", "Non-essential consumer goods and services", "Consumer"),
    ("Automotive", "Vehicle makers and suppliers", "Industrial"),
    ("Financials", "Banks, insurers and asset managers", "Finance"),
    ("Healthcare", "Pharmaceuticals, devices and care providers", "Health"),
    ("Consumer Staples", "Everyday essentials", "Consumer"),
    ("Energy", "Oil, gas and renewables", "Energy"),
    ("Industrials", "Machinery, aerospace and logistics", "Industrial"),
    ("Real Estate", "Property owners and developers", "Property"),
    ("Utilities", "Power, water and gas networks", "Utilities"),
]

# (symbol, company, sector_id, price, country)
STOCKS = [
    ("NWSF", "Northwind Software", 1, 142.30, "US"),
    ("QNTC", "Quanta Circuits", 1, 88.15, "US"),
    ("CLDB", "CloudBridge Systems", 1, 211.40, "US"),
    ("ARCL", "Arclight Devices", 1, 64.80, "TW"),
    ("BRKH", "Brookhaven Retail", 2, 97.25, "US"),
    ("LUMO", "Lumo Apparel", 2, 45.60, "GB"),
    ("VOLT", "Voltra Motors", 3, 178.90, "US"),
    ("AXLE", "Axle & Co", 3, 52.35, "DE"),
    ("MRDN", "Meridian Bancorp", 4, 73.10, "US"),
    ("CRST", "Crestline Insurance", 4, 121.45, "US"),
    ("HLXC", "Helix Care", 5, 156.70, "US"),
    ("PNCL", "Pinnacle Biologics", 5, 94.20, "CH"),
    ("DAWN", "Dawnfield Foods", 6, 68.55, "US"),
    ("HRTH", "Hearth & Home", 6, 39.90, "US"),
    ("SOLR", "Solaris Energy", 7, 58.40, "US"),
    ("TIDE", "Tidewater Oil", 7, 82.65, "NO"),
    ("FRGE", "Forge Industries", 8, 133.25, "US"),
    ("SKYL", "Skyline Aerospace", 8, 201.80, "FR"),
    ("BLDR", "Builder Realty Trust", 9, 47.30, "US"),
    ("GRID", "GridOne Utilities", 10, 61.15, "US"),
    ("ASIA", "AsiaPac Holdings", 4, 33.75, "HK"),
    ("ORBT", "Orbit Mobility", 3, 27.60, "KR"),
    ("MNTA", "Montana Minerals", 7, 41.05, "CA"),
    ("ZENI", "Zenith Instruments", 5, 109.90, "JP"),
]
# (symbol, issuer, coupon, maturity, price)
BONDS = [
    ("GB10", "Government Note 10Y", 4.25, "2034-05-15", 98.40),
    ("GB05", "Government Note 5Y", 3.80, "2029-05-15", 99.10),
    ("CB07", "Corporate Bond 7Y", 5.10, "2031-09-01", 101.25),
    ("CB03", "Corporate Bond 3Y", 4.60, "2027-03-01", 99.75),
    ("MB12", "Municipal Bond 12Y", 3.95, "2036-06-30", 97.60),
    ("HY05", "High Yield Bond 5Y", 7.20, "2029-11-15", 94.85),
]

PORTFOLIOS = [
    ("Harbor Growth Fund", "2023-01-15", "High", 24_000_000, "Growth", "SP500", "Active"),
    ("Steady Income Fund", "2023-02-01", "Low", 17_500_000, "Income", "AGG", "Active"),
    ("Frontier Tech Fund", "2023-03-10", "High", 12_800_000, "Sector", "QQQ", "Active"),
    ("Balanced Portfolio", "2023-04-05", "Medium", 31_000_000, "Balanced", "60/40", "Active"),
    ("Green Future Fund", "2023-05-20", "Medium", 9_600_000, "ESG", "MSCI_ESG", "Active"),
    ("Small Cap Value Fund", "2023-06-12", "High", 7_400_000, "Value", "Russell2000", "Active"),
    ("Global Equity Fund", "2023-07-01", "Medium", 21_300_000, "International", "EAFE", "Active"),
    ("Bond Plus Fund", "2023-07-25", "Low", 15_200_000, "Income", "BARC_AGG", "Active"),
    ("Dividend Leaders Fund", "2023-08-14", "Low", 13_900_000, "Dividend", "SPYD", "Active"),
    ("Emerging Markets Fund", "2023-09-02", "High", 8_700_000, "International", "VWO", "Active"),
    ("Broad Market Index Fund", "2023-10-01", "Medium", 40_500_000, "Index", "TOTAL_STOCK", "Passive"),
    ("Core Bond Index Fund", "2023-10-01", "Low", 28_000_000, "Index", "TOTAL_BOND", "Passive"),
    ("World Index Fund", "2023-10-15", "Medium", 33_200_000, "Index", "TOTAL_INTL", "Passive"),
]

BENCHMARKS = [
    ("S&P 500 Index", "SP500", "Equity", "Large-cap US equity benchmark", "1957-03-04"),
    ("Bloomberg Aggregate Bond Index", "AGG", "Fixed Income", "US investment grade bond benchmark", "1976-01-01"),
    ("Nasdaq 100 Index", "QQQ", "Equity", "Large-cap US technology-weighted benchmark", "1985-01-31"),
    ("60/40 Blend", "60/40", "Blended", "60% equity, 40% bonds", "2000-01-01"),
    ("MSCI ESG Leaders", "MSCI_ESG", "Equity", "Sustainability-screened equity benchmark", "2010-05-01"),
    ("Russell 2000 Index", "Russell2000", "Equity", "US small-cap benchmark", "1984-12-31"),
]


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (OUT / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    write(
        "sectors",
        ["sector_id", "sector_name", "sector_description", "industry_group"],
        [[i, *row] for i, row in enumerate(SECTORS, 1)],
    )
    securities = [
        [i, sym, name, "Stock", sector, rng.randint(2, 900) * 1000, price, "USD", "NYSE", country,
         f"{rng.randint(1985, 2015)}-{rng.randint(1, 12):02d}-15", None, None]
        for i, (sym, name, sector, price, country) in enumerate(STOCKS, 1)
    ]  # fmt: skip
    first_bond = len(STOCKS) + 1
    securities += [
        [first_bond + i, sym, name, "Bond", None, None, price, "USD", "OTC", "US", "2019-01-01", maturity, coupon]
        for i, (sym, name, coupon, maturity, price) in enumerate(BONDS)
    ]
    write(
        "securities",
        ["security_id", "symbol", "company_name", "asset_type", "sector_id", "market_cap", "current_price",
         "currency", "exchange", "country", "listing_date", "maturity_date", "coupon_rate"],
        securities,
    )  # fmt: skip
    write(
        "benchmarks",
        ["benchmark_id", "benchmark_name", "benchmark_symbol", "benchmark_type", "description", "inception_date"],
        [[i, *row] for i, row in enumerate(BENCHMARKS, 1)],
    )
    write(
        "portfolios",
        ["portfolio_id", "portfolio_name", "creation_date", "target_risk_level", "total_aum", "strategy_type",
         "benchmark_index", "status"],
        [[i, *row] for i, row in enumerate(PORTFOLIOS, 1)],
    )  # fmt: skip

    price = {row[0]: row[6] for row in securities}
    stock_ids, bond_ids = list(range(1, first_bond)), list(range(first_bond, first_bond + len(BONDS)))
    bond_only, mixed = {8, 12}, {2, 4}  # Bond Plus and Core Bond hold no equities; two funds mix both.
    holdings, hid = [], 1
    for pid, (_, created, *_rest) in enumerate(PORTFOLIOS, 1):
        if pid in bond_only:
            picks = rng.sample(bond_ids, 5)
        elif pid in mixed:
            picks = rng.sample(stock_ids, 4) + rng.sample(bond_ids, 3)
        else:
            picks = rng.sample(stock_ids, rng.randint(6, 9))
        raw = [rng.uniform(0.5, 2.0) for _ in picks]
        weights = [round(r / sum(raw), 2) for r in raw]
        weights[-1] = round(weights[-1] + 1 - sum(weights), 2)  # Force a sum of exactly 1.
        if pid == 11:
            weights[-1] = round(weights[-1] - 0.02, 2)  # One fund's recorded weights sum to 98%.
        for sec, weight in zip(picks, weights, strict=True):
            bought = round(price[sec] * rng.uniform(0.82, 1.1), 2)
            quantity = rng.choice([200, 400, 500, 800, 1000, 1500, 2500])
            holdings.append([hid, pid, sec, quantity, bought, created, weight, round(quantity * bought, 2)])
            hid += 1
    write(
        "holdings",
        ["holding_id", "portfolio_id", "security_id", "quantity", "purchase_price", "purchase_date",
         "current_weight", "cost_basis"],
        holdings,
    )  # fmt: skip

    transactions = []
    for tid, h in enumerate(rng.sample(holdings, 24), 1):
        when = date(2024, 1, 1) + timedelta(days=rng.randint(0, 120))
        kind = rng.choice(["BUY", "BUY", "SELL"])
        transactions.append([tid, h[1], h[2], kind, rng.choice([100, 250, 500]), round(price[h[2]] * 1.01, 2),
                             when.isoformat(), rng.choice([10, 15, 20]), (when + timedelta(days=2)).isoformat(),
                             "Rebalance" if kind == "SELL" else "Initial purchase"])  # fmt: skip
    write(
        "transactions",
        ["transaction_id", "portfolio_id", "security_id", "transaction_type", "quantity", "price",
         "transaction_date", "fees", "settlement_date", "notes"],
        transactions,
    )  # fmt: skip

    days = [date(2024, 3, 1) + timedelta(days=i) for i in range(14)]
    history, pid_ = [], 1
    for sec in rng.sample(stock_ids, 10):
        level = price[sec]
        for day in days:
            level *= 1 + rng.uniform(-0.02, 0.02)
            history.append(
                [
                    pid_,
                    sec,
                    day.isoformat(),
                    round(level * 0.995, 2),
                    round(level * 1.01, 2),
                    round(level * 0.985, 2),
                    round(level, 2),
                    rng.randint(1, 30) * 1_000_000,
                    round(level, 2),
                ]
            )
            pid_ += 1
    write(
        "historical_prices",
        ["price_id", "security_id", "price_date", "open_price", "high_price", "low_price", "close_price",
         "volume", "adjusted_close"],
        history,
    )  # fmt: skip

    def u(low: float, high: float, digits: int = 1) -> float:
        return round(rng.uniform(low, high), digits)

    performance, risk, perf_id = [], [], 1
    for pid in (1, 2, 3, 4):  # Performance and risk cover only four funds.
        nav = rng.uniform(100, 130)
        for day in days[:11]:
            nav *= 1 + rng.uniform(-0.004, 0.006)
            when = day.isoformat()
            performance.append(
                [
                    perf_id,
                    pid,
                    when,
                    round(nav, 2),
                    u(-2, 9),
                    u(-2, 9),
                    u(-2, 9),
                    u(-2, 9),
                    u(6, 20),
                    u(0.4, 1.6, 2),
                    u(-12, -3),
                ]
            )
            risk.append(
                [
                    perf_id,
                    pid,
                    when,
                    u(-5, -1.5),
                    u(-8, -3),
                    u(-6, -2),
                    u(0.5, 1.3, 2),
                    u(0.6, 0.95, 2),
                    u(1.5, 5),
                    u(0.2, 0.9, 2),
                    u(0.8, 1.9, 2),
                ]
            )
            perf_id += 1
    write(
        "portfolio_performance",
        ["performance_id", "portfolio_id", "performance_date", "nav", "total_return_1m", "total_return_3m",
         "total_return_6m", "total_return_1y", "volatility", "sharpe_ratio", "max_drawdown"],
        performance,
    )  # fmt: skip
    write(
        "risk_metrics",
        ["risk_id", "portfolio_id", "calculation_date", "var_95", "var_99", "cvar_95", "beta", "correlation_sp500",
         "tracking_error", "information_ratio", "sortino_ratio"],
        risk,
    )  # fmt: skip


if __name__ == "__main__":
    main()
