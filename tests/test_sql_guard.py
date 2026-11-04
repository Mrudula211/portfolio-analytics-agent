import pytest

from portfolio_agent.sql_guard import SQLBlocked, SQLExecutionError, execute_select

RUNAWAY = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE holdings",
        "DELETE FROM portfolios",
        "UPDATE portfolios SET total_aum = 0",
        "INSERT INTO sectors (sector_name) VALUES ('x')",
        "PRAGMA table_info(holdings)",
        "ATTACH 'other.db' AS other",
        "SELECT 1; DROP TABLE holdings",
        "SELECT * FROM sqlite_master",
        "SELECT COUNT(*) FROM sqlite_master",
        "SELECT * FROM SQLITE_SCHEMA",
        "SELECT * FROM pragma_table_info('holdings')",
        "SELECT load_extension('evil')",
        "SELECT zeroblob(1000000000)",
        "WITH x AS (SELECT 1) DELETE FROM portfolios",
    ],
)
def test_forbidden_queries_are_blocked(settings, sql):
    with pytest.raises(SQLBlocked):
        execute_select(settings.db_path, sql)


def test_runaway_recursive_query_stops_at_work_budget(settings):
    with pytest.raises(SQLBlocked, match="budget"):
        execute_select(settings.db_path, RUNAWAY, max_vm_steps=200_000)


def test_runaway_query_stops_at_time_budget(settings):
    with pytest.raises(SQLBlocked, match="budget"):
        execute_select(settings.db_path, RUNAWAY, timeout_s=0.05, max_vm_steps=10**12)


def test_count_over_cte_is_allowed(settings):
    result = execute_select(settings.db_path, "WITH x AS (SELECT portfolio_id FROM portfolios) SELECT COUNT(*) FROM x")
    assert result.rows == [[13]]


def test_invalid_sql_is_repairable_not_blocked(settings):
    with pytest.raises(SQLExecutionError, match="no such column"):
        execute_select(settings.db_path, "SELECT nope FROM holdings")


def test_row_cap_marks_truncation(settings):
    result = execute_select(settings.db_path, "SELECT price_id FROM historical_prices", max_rows=10)
    assert len(result.rows) == 10 and result.truncated


def test_data_is_unchanged_after_attacks(settings):
    for attack in ("DELETE FROM portfolios", "SELECT 1; DROP TABLE portfolios"):
        with pytest.raises(SQLBlocked):
            execute_select(settings.db_path, attack)
    assert execute_select(settings.db_path, "SELECT COUNT(*) FROM portfolios").rows == [[13]]


def test_vm_steps_measure_query_work_not_schema_loading(settings):
    small = execute_select(settings.db_path, "SELECT 1").vm_steps
    large = execute_select(settings.db_path, "SELECT SUM(close_price) FROM historical_prices").vm_steps
    assert small < 32 < large


def test_full_scan_reported_and_index_use_not(settings):
    scan = execute_select(settings.db_path, "SELECT * FROM holdings WHERE quantity > 0")
    seek = execute_select(settings.db_path, "SELECT * FROM holdings WHERE portfolio_id = 1")
    assert scan.full_scans == ["holdings"] and seek.full_scans == []
