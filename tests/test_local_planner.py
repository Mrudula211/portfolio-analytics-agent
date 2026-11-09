"""The deterministic planner, exercised through the production agent with no model.

Every positive case is checked against an independent oracle: a differently written SQL query, or the
CSV-based exposure oracle. No case maps a question to a stored answer.
"""

import pytest

from portfolio_agent import PortfolioAgent
from portfolio_agent.evaluation import ExposureOracle
from portfolio_agent.sql_guard import execute_select

NO_MODEL = {"local_deterministic", "direct_calculator"}


@pytest.fixture(scope="module")
def agent(settings):
    built = PortfolioAgent(settings)  # The shared settings carry no API key, so no model client exists.
    assert built.llm is None
    return built


def norm(rows):
    return sorted(tuple(round(v, 4) if isinstance(v, float) else v for v in row) for row in rows)


def sql_rows(reply):
    steps = [s for s in reply.steps if s.tool == "run_sql"]
    assert len(steps) == 1 and steps[0].error is None, reply.answer
    return steps[0].rows


def oracle(settings, sql):
    return execute_select(settings.db_path, sql).rows


def ask(agent, question):
    reply = agent.answer_question(question, use_cache=False)
    assert reply.status == "ok", (question, reply.status, reply.answer)
    assert reply.route in NO_MODEL and reply.llm["calls"] == 0, (question, reply.route)
    return reply


COUNT = "SELECT COUNT(*) FROM portfolios"
NAMES = "SELECT portfolio_name FROM portfolios"
AUM = "SELECT {agg}(total_aum) FROM portfolios"


def where(condition):
    return f" WHERE {condition}"


def in_sector(name):
    return f"(SELECT sector_id FROM sectors WHERE sector_name = '{name}')"


def share_oracle(sector):
    return (
        "SELECT p.portfolio_name, "
        f"SUM(CASE WHEN s.sector_id = {in_sector(sector)} THEN h.quantity * s.current_price END) AS part, "
        "SUM(h.quantity * s.current_price) AS whole, "
        f"ROUND(100.0 * SUM(CASE WHEN s.sector_id = {in_sector(sector)} THEN h.quantity * s.current_price END) "
        "/ SUM(h.quantity * s.current_price), 2) AS pct "
        "FROM portfolios p JOIN holdings h ON h.portfolio_id = p.portfolio_id "
        "JOIN securities s ON s.security_id = h.security_id GROUP BY p.portfolio_id "
        f"HAVING part IS NOT NULL"
    )


def top_oracle(portfolio, metric, direction, n):
    extra = "" if metric == "h.quantity" else f", {metric}"
    return (
        f"SELECT h.holding_id, s.symbol, s.company_name, h.quantity{extra} "
        "FROM holdings h, securities s WHERE s.security_id = h.security_id "
        f"AND h.portfolio_id = (SELECT portfolio_id FROM portfolios WHERE portfolio_name = '{portfolio}') "
        f"ORDER BY {metric.split(' AS ')[-1] if ' AS ' in metric else metric} {direction} LIMIT {n}"
    )


def diversification_oracle(threshold):
    return (
        "SELECT p.portfolio_name, "
        "(SELECT COUNT(DISTINCT s.sector_id) FROM holdings h JOIN securities s USING (security_id) "
        " WHERE h.portfolio_id = p.portfolio_id AND s.asset_type = 'Stock') AS sectors, "
        "(SELECT COUNT(*) FROM holdings h WHERE h.portfolio_id = p.portfolio_id) AS total, "
        "ROUND(1.0 * (SELECT COUNT(DISTINCT s.sector_id) FROM holdings h JOIN securities s USING (security_id) "
        " WHERE h.portfolio_id = p.portfolio_id AND s.asset_type = 'Stock') "
        "/ (SELECT COUNT(*) FROM holdings h WHERE h.portfolio_id = p.portfolio_id), 3) AS ratio "
        f"FROM portfolios p WHERE sectors > {threshold}"
    )


AVG_BY_SECTOR = (
    "SELECT sec.sector_name, AVG(s.current_price) FROM sectors sec JOIN securities s USING (sector_id) "
    "GROUP BY sec.sector_id"
)

SQL_CASES = [
    # Counting portfolios
    ("How many portfolios are there?", COUNT),
    ("HOW MANY PORTFOLIOS DO WE HAVE?", COUNT),
    ("What's the number of portfolios?", COUNT),
    ("count the portfolios", COUNT),
    ("How many funds do we have?", COUNT),
    ("How many portfolois do we have?", COUNT),  # A typo in the key word.
    ("How many active portfolios do we have?", COUNT + where("status = 'Active'")),
    ("How many passive funds are there?", COUNT + where("status = 'Passive'")),
    ("How many high risk portfolios are there?", COUNT + where("target_risk_level = 'High'")),
    # Listing portfolios
    ("List the active portfolios", NAMES + where("status = 'Active'")),
    ("Which portfolios are passive?", NAMES + where("status = 'Passive'")),
    ("Show me all portfolios with low target risk level", NAMES + where("target_risk_level = 'Low'")),
    ("what funds are high risk", NAMES + where("target_risk_level = 'High'")),
    ("Names of all portfolios", NAMES),
    ("display every portfolio", NAMES),
    # Assets under management
    ("What is the total AUM of low risk portfolios?", AUM.format(agg="SUM") + where("target_risk_level = 'Low'")),
    (
        "Sum of assets under management for medium risk funds",
        AUM.format(agg="SUM") + where("target_risk_level = 'Medium'"),
    ),
    ("total aum of active portfolios", AUM.format(agg="SUM") + where("status = 'Active'")),
    ("What's the combined AUM across all portfolios?", AUM.format(agg="SUM")),
    ("average AUM of high risk portfolios", AUM.format(agg="AVG") + where("target_risk_level = 'High'")),
    ("Total AUM for passive portfolios", AUM.format(agg="SUM") + where("status = 'Passive'")),
    (
        "Which portfolio has the largest AUM?",
        "SELECT portfolio_name, total_aum FROM portfolios ORDER BY 2 DESC LIMIT 1",
    ),
    ("Which fund has the smallest AUM?", "SELECT portfolio_name, total_aum FROM portfolios ORDER BY 2 LIMIT 1"),
    # Securities in a sector
    (
        "List the securities in the Healthcare sector",
        f"SELECT symbol, company_name FROM securities WHERE sector_id = {in_sector('Healthcare')}",
    ),
    (
        "Which stocks are in Energy?",
        f"SELECT symbol, company_name FROM securities WHERE sector_id = {in_sector('Energy')}",
    ),
    (
        "Show me companies in the Financials sector",
        f"SELECT symbol, company_name FROM securities WHERE sector_id = {in_sector('Financials')}",
    ),
    (
        "which securities belong to tech?",
        f"SELECT symbol, company_name FROM securities WHERE sector_id = {in_sector('Technology')}",
    ),
    (
        "Name the Consumer Staples stocks",
        f"SELECT symbol, company_name FROM securities WHERE sector_id = {in_sector('Consumer Staples')}",
    ),
    # Average price by sector
    ("Average price of securities per sector", AVG_BY_SECTOR),
    ("avg current price by sector", AVG_BY_SECTOR),
    ("What is the mean price in each sector?", AVG_BY_SECTOR),
    ("average share price across sectors", AVG_BY_SECTOR),
    # Top holdings
    (
        "Show the top 3 holdings by cost basis in the Balanced Portfolio",
        top_oracle("Balanced Portfolio", "h.cost_basis", "DESC", 3),
    ),
    (
        "4 largest positions by market value in the ESG Sustainable Fund",
        top_oracle("ESG Sustainable Fund", "h.quantity * s.current_price AS market_value", "DESC", 4),
    ),
    (
        "Bottom 2 holdings by cost basis in the Growth Equity Fund",
        top_oracle("Growth Equity Fund", "h.cost_basis", "ASC", 2),
    ),
    (
        "top five holdings by quantity in the Tech Innovation Fund",
        top_oracle("Tech Innovation Fund", "h.quantity", "DESC", 5),
    ),
    (
        "What are the top 3 positions by weight in the Dividend Aristocrats Fund",
        top_oracle("Dividend Aristocrats Fund", "h.current_weight", "DESC", 3),
    ),
    (
        "Top 3 holdings by cost basis in the Growth Equty Fund",  # A typo in the portfolio name.
        top_oracle("Growth Equity Fund", "h.cost_basis", "DESC", 3),
    ),
    # A sector's value and share of each portfolio
    ("What share of each portfolio's value is in Healthcare, in percent?", share_oracle("Healthcare")),
    (
        "For every portfolio show the value of Financials holdings and the percentage of total value",
        share_oracle("Financials"),
    ),
    ("Technology holdings value and percentage of each portfolio", share_oracle("Technology")),
    ("percentage of portfolio value in Energy per portfolio", share_oracle("Energy")),
    # Diversification
    ("Show diversification metrics for portfolios with more than 5 sectors", diversification_oracle(5)),
    (
        "diversification ratio for portfolios holding more than five different sectors",
        diversification_oracle(5),
    ),
    (
        "Find portfolios with more than 4 different sectors and give their diversification ratio",
        diversification_oracle(4),
    ),
    ("diversification metrics for portfolios in more than 3 sectors", diversification_oracle(3)),
]


@pytest.mark.parametrize("question,reference", SQL_CASES, ids=[f"sql{i:02d}" for i in range(len(SQL_CASES))])
def test_paraphrases_match_an_independent_oracle(agent, settings, question, reference):
    reply = ask(agent, question)
    assert norm(sql_rows(reply)) == norm(oracle(settings, reference)), question
    assert execute_select(settings.db_path, reference).rows  # An empty oracle would prove nothing.


EXPOSURE_CASES = [
    ("Sector breakdown for the Balanced Portfolio", ["Balanced Portfolio"]),
    ("Show me the sector allocation of Conservative Income Fund", ["Conservative Income Fund"]),
    ("exposure by sector for the Emerging Markets Fund", ["Emerging Markets Fund"]),
    ("sector exposure for tech innovaton fund", ["Tech Innovation Fund"]),
    ("Calculate sector exposure for dividend aristocrats", ["Dividend Aristocrats Fund"]),
    ("What are the sector exposures for the Total Stock Market Index Fund?", ["Total Stock Market Index Fund"]),
    ("Sector exposure of Fixed Income Plus", ["Fixed Income Plus"]),
]

HYBRID_CASES = [
    (
        "sector exposures for all passive portfolios",
        "SELECT portfolio_name FROM portfolios WHERE status = 'Passive'",
    ),
    (
        "sector breakdown of all high risk portfolios",
        "SELECT portfolio_name FROM portfolios WHERE target_risk_level = 'High'",
    ),
    (
        "sector exposure of the largest portfolio by AUM",
        "SELECT portfolio_name FROM portfolios WHERE total_aum = (SELECT MAX(total_aum) FROM portfolios)",
    ),
    (
        "sector exposure of the smallest portfolio by assets",
        "SELECT portfolio_name FROM portfolios WHERE total_aum = (SELECT MIN(total_aum) FROM portfolios)",
    ),
]


def exposures(reply):
    steps = [s for s in reply.steps if s.tool == "exposure_calculator" and s.error is None]
    return {
        s.exposure["portfolio_name"]: {e["sector"]: e["exposure_pct"] for e in s.exposure["exposures"]} for s in steps
    }


def assert_exposures_match_oracle(settings, reply, names):
    truth = ExposureOracle(settings.data_dir)
    got = exposures(reply)
    assert set(got) == set(names)
    for name in names:
        expected = truth.exposures(name)
        assert set(got[name]) == set(expected), name
        for sector, percent in expected.items():
            assert got[name][sector] == pytest.approx(percent, abs=0.01), (name, sector)


@pytest.mark.parametrize("question,names", EXPOSURE_CASES, ids=[f"exp{i}" for i in range(len(EXPOSURE_CASES))])
def test_exposure_paraphrases_use_the_calculator_and_match_the_oracle(agent, settings, question, names):
    reply = ask(agent, question)
    assert {s.tool for s in reply.steps} == {"exposure_calculator"}
    assert_exposures_match_oracle(settings, reply, names)


@pytest.mark.parametrize("question,selection", HYBRID_CASES, ids=[f"hyb{i}" for i in range(len(HYBRID_CASES))])
def test_hybrid_paraphrases_select_then_calculate_for_the_selected_portfolios(agent, settings, question, selection):
    reply = ask(agent, question)
    assert [s.tool for s in reply.steps][0] == "run_sql"
    selected = [row[0] for row in oracle(settings, selection)]
    assert selected
    assert sorted(r[0] for r in sql_rows(reply)) == sorted(selected)
    assert_exposures_match_oracle(settings, reply, selected)


UNSUPPORTED = [
    "How many bonds are there?",
    "How many portfolios hold NVDA?",
    "What is the average price of Technology securities?",
    "Top holdings in the Growth Equity Fund",  # No measure is stated.
    "Show the top 3 holdings by beta in the Growth Equity Fund",
    "What is the Sharpe ratio of the Balanced Portfolio?",
    "How many portfolios were created in 2023?",  # Extra constraints must not be silently dropped.
    "List the portfolios managed by John",
    "What is the total AUM of portfolios in Europe?",
    "Delete all portfolios",
    "Should I buy NVIDIA?",
    "What's the weather in Mumbai?",
    "Which securities are in the Utilities sector and pay a dividend?",
    "What is the sector exposure for Technology in the Balanced Portfolio?",  # A specific sector, not a breakdown.
]


@pytest.mark.parametrize("question", UNSUPPORTED, ids=[f"neg{i:02d}" for i in range(len(UNSUPPORTED))])
def test_unsupported_wording_is_declined_not_mapped_to_a_similar_question(agent, question):
    assert agent.planner.plan(question, agent.linker.link(question)) is None
    reply = agent.answer_question(question, use_cache=False)
    assert reply.status in {"error", "declined", "blocked"} and not reply.steps, (reply.route, reply.answer)


def test_ambiguous_portfolio_asks_which_one(agent):
    question = "What is the sector exposure of the international fund?"
    reply = agent.answer_question(question, use_cache=False)
    assert reply.status == "clarify"
    assert "International Equity Fund" in reply.answer and "Total International Index Fund" in reply.answer


def test_unknown_portfolio_is_not_guessed(agent):
    reply = agent.answer_question("sector exposure of the Atlantis Fund", use_cache=False)
    assert reply.status in {"clarify", "error"} and "Atlantis" not in str(reply.steps[:0])
    assert not exposures(reply)


def test_every_plan_runs_through_the_sql_guard(agent):
    """A local plan is ordinary SQL: it is validated, read-only and limited like any model plan."""
    reply = ask(agent, "How many portfolios are there?")
    assert reply.steps[0].tool == "run_sql" and reply.steps[0].input["sql"].startswith("SELECT")


def test_planner_never_reads_the_ground_truth_or_embeds_questions():
    from portfolio_agent.config import ROOT
    from portfolio_agent.evaluation import load_extended, load_ground_truth

    source = (ROOT / "portfolio_agent" / "local_planner.py").read_text(encoding="utf-8")
    assert "ground_truth" not in source and "extended_dataset" not in source and ".json" not in source
    flat = " ".join(source.lower().split())
    cases = load_ground_truth(ROOT / "ground_truth_dataset.json") + load_extended(
        ROOT / "eval" / "extended_dataset.json"
    )
    for case in cases:
        assert " ".join(case.question.lower().split()) not in flat, case.id
