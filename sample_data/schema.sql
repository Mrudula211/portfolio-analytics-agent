-- Schema for the fictional sample dataset. Tables load in dependency order.

CREATE TABLE IF NOT EXISTS sectors (
    sector_id INTEGER PRIMARY KEY,
    sector_name TEXT NOT NULL UNIQUE,
    sector_description TEXT,
    industry_group TEXT
);

CREATE TABLE IF NOT EXISTS securities (
    security_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK(asset_type IN ('Stock', 'Bond')),
    sector_id INTEGER REFERENCES sectors(sector_id),
    market_cap REAL,
    current_price REAL,
    currency TEXT DEFAULT 'USD',
    exchange TEXT,
    country TEXT,
    listing_date DATE,
    maturity_date DATE,  -- Bonds only
    coupon_rate REAL     -- Bonds only
);

CREATE TABLE IF NOT EXISTS benchmarks (
    benchmark_id INTEGER PRIMARY KEY,
    benchmark_name TEXT NOT NULL UNIQUE,
    benchmark_symbol TEXT,
    benchmark_type TEXT,
    description TEXT,
    inception_date DATE
);

CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id INTEGER PRIMARY KEY,
    portfolio_name TEXT NOT NULL UNIQUE,
    creation_date DATE,
    target_risk_level TEXT,
    total_aum REAL,
    strategy_type TEXT,
    benchmark_index TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    holding_id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    quantity REAL NOT NULL,
    purchase_price REAL,
    purchase_date DATE,
    current_weight REAL,
    cost_basis REAL,
    UNIQUE(portfolio_id, security_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    transaction_date DATE NOT NULL,
    fees REAL DEFAULT 0,
    settlement_date DATE,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS historical_prices (
    price_id INTEGER PRIMARY KEY,
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    price_date DATE NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL NOT NULL,
    volume INTEGER,
    adjusted_close REAL,
    UNIQUE(security_id, price_date)
);

CREATE TABLE IF NOT EXISTS portfolio_performance (
    performance_id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
    performance_date DATE NOT NULL,
    nav REAL NOT NULL,
    total_return_1m REAL,
    total_return_3m REAL,
    total_return_6m REAL,
    total_return_1y REAL,
    volatility REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    UNIQUE(portfolio_id, performance_date)
);

CREATE TABLE IF NOT EXISTS risk_metrics (
    risk_id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
    calculation_date DATE NOT NULL,
    var_95 REAL,
    var_99 REAL,
    cvar_95 REAL,
    beta REAL,
    correlation_sp500 REAL,
    tracking_error REAL,
    information_ratio REAL,
    sortino_ratio REAL,
    UNIQUE(portfolio_id, calculation_date)
);

CREATE INDEX IF NOT EXISTS idx_securities_sector ON securities(sector_id);
CREATE INDEX IF NOT EXISTS idx_securities_asset_type ON securities(asset_type);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_holdings_security ON holdings(security_id);
CREATE INDEX IF NOT EXISTS idx_transactions_portfolio ON transactions(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_transactions_security ON transactions(security_id);
CREATE INDEX IF NOT EXISTS idx_historical_prices_security ON historical_prices(security_id);
