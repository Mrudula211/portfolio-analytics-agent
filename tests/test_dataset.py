"""The source data and the database built from it. These read the official files; they never change them."""

import csv
import dataclasses
import sqlite3
from collections import Counter

import pytest

from portfolio_agent.config import ROOT, Settings
from portfolio_agent.db import LOAD_ORDER, build_database, connect_readonly

DATA = ROOT / "data"
SCHEMA = (ROOT / "database_schema.sql").read_text(encoding="utf-8")


def read(table):
    with (DATA / f"{table}.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def conn(settings):
    connection = connect_readonly(settings.db_path)
    yield connection
    connection.close()


def schema_columns():
    memory = sqlite3.connect(":memory:")
    memory.executescript(SCHEMA)
    return {t: [row[1] for row in memory.execute(f"PRAGMA table_info({t})")] for t in LOAD_ORDER}


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_csv_columns_match_the_schema_exactly(table):
    with (DATA / f"{table}.csv").open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == schema_columns()[table]


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_every_csv_row_is_loaded(conn, table):
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == len(read(table))


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_primary_keys_are_unique_and_present(table):
    key = schema_columns()[table][0]
    ids = [row[key] for row in read(table)]
    assert all(ids) and len(ids) == len(set(ids))


def test_foreign_keys_hold(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_declared_unique_pairs_have_no_duplicates():
    for table, pair in {
        "holdings": ("portfolio_id", "security_id"),
        "historical_prices": ("security_id", "price_date"),
        "portfolio_performance": ("portfolio_id", "performance_date"),
        "risk_metrics": ("portfolio_id", "calculation_date"),
    }.items():
        counts = Counter(tuple(row[c] for c in pair) for row in read(table))
        assert max(counts.values()) == 1, table


def test_required_fields_are_never_null(conn):
    required = {
        "portfolios": ["portfolio_name", "status", "target_risk_level", "total_aum"],
        "securities": ["symbol", "company_name", "asset_type", "current_price"],
        "holdings": ["portfolio_id", "security_id", "quantity", "current_weight", "cost_basis"],
        "sectors": ["sector_name"],
    }
    for table, columns in required.items():
        for column in columns:
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL").fetchone()[0] == 0, column


def test_numeric_fields_are_valid_and_plausible(conn):
    assert conn.execute("SELECT COUNT(*) FROM securities WHERE current_price <= 0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM holdings WHERE quantity <= 0 OR cost_basis < 0").fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM holdings WHERE current_weight < 0 OR current_weight > 1").fetchone()[0] == 0
    )
    assert conn.execute("SELECT COUNT(*) FROM portfolios WHERE total_aum <= 0").fetchone()[0] == 0
    for table, column in [("securities", "current_price"), ("holdings", "quantity"), ("portfolios", "total_aum")]:
        assert (
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE typeof({column}) NOT IN ('integer', 'real')").fetchone()[
                0
            ]
            == 0
        )


def test_stocks_have_a_sector_and_bonds_do_not(conn):
    assert (
        conn.execute("SELECT COUNT(*) FROM securities WHERE asset_type = 'Stock' AND sector_id IS NULL").fetchone()[0]
        == 0
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM securities WHERE asset_type = 'Bond' AND sector_id IS NOT NULL").fetchone()[
            0
        ]
        == 0
    )


def test_cost_basis_equals_quantity_times_purchase_price(conn):
    bad = conn.execute(
        "SELECT COUNT(*) FROM holdings WHERE ABS(quantity * purchase_price - cost_basis) > 1"
    ).fetchone()[0]
    assert bad == 0


def test_the_database_rebuilds_identically(tmp_path):
    """Two builds from the same files give the same contents: the database is reproducible."""
    dumps = []
    for name in ("a.db", "b.db"):
        path = build_database(dataclasses.replace(Settings(), db_path=tmp_path / name, gemini_api_key=""))
        connection = sqlite3.connect(path)
        dumps.append({t: sorted(connection.execute(f"SELECT * FROM {t}").fetchall(), key=repr) for t in LOAD_ORDER})
        connection.close()
    assert dumps[0] == dumps[1]


def test_known_data_limitations_are_what_the_documentation_says(conn):
    """If the data ever changes, the documented caveats must be revisited."""
    weights = dict(conn.execute("SELECT portfolio_id, ROUND(SUM(current_weight), 4) FROM holdings GROUP BY 1"))
    off = {k: v for k, v in weights.items() if abs(v - 1) > 0.001}
    assert len(off) == 1 and list(off.values()) == [0.98]  # Only the Total Stock Market Index Fund.
    assert conn.execute("SELECT COUNT(DISTINCT portfolio_id) FROM portfolio_performance").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(DISTINCT portfolio_id) FROM risk_metrics").fetchone()[0] == 4
    empty = {
        r[0]
        for r in conn.execute(
            "SELECT sector_name FROM sectors WHERE sector_id NOT IN "
            "(SELECT sector_id FROM securities WHERE sector_id IS NOT NULL)"
        )
    }
    assert empty == {"Industrials", "Real Estate", "Utilities"}
