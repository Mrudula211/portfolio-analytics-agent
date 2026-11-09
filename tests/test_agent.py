import dataclasses
import threading

import pytest
from conftest import sql_call

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.llm import LLMError, ToolCall


def test_simple_exposure_uses_no_model(make_agent):
    agent = make_agent()
    reply = agent.answer_question("What are the sector exposures for the Tech Innovation Fund?")
    assert reply.route == "direct_calculator" and reply.status == "ok"
    assert reply.llm["calls"] == 0 and agent.llm.prompts == []
    assert "Technology" in reply.answer


@pytest.mark.parametrize(
    "question",
    [
        "Which fund has the highest sector exposure in Tech Innovation Fund and Balanced Portfolio?",
        "How many sector exposures does the Balanced Portfolio have?",
        "What is the Technology sector exposure of the Balanced Portfolio?",
    ],
)
def test_harder_exposure_questions_go_to_the_model(make_agent, question):
    agent = make_agent({question: [sql_call("SELECT 1")]})
    assert agent.answer_question(question).route == "gemini"


def test_one_model_call_for_sql_question(make_agent):
    question = "How many portfolios exist?"
    agent = make_agent({question: [sql_call("SELECT COUNT(*) FROM portfolios", "Portfolio count")]})
    reply = agent.answer_question(question)
    assert reply.status == "ok" and "13" in reply.answer
    assert len(agent.llm.prompts) == 1


@pytest.mark.parametrize("question", ["Which is the strongest portfolio?", "Which fund is the best-performing?"])
def test_strongest_portfolio_uses_latest_one_year_return_and_discloses_meaning(make_agent, question):
    query = """WITH latest AS (
                   SELECT portfolio_id, MAX(performance_date) AS latest_date
                   FROM portfolio_performance
                   WHERE total_return_1y IS NOT NULL
                   GROUP BY portfolio_id
               )
               SELECT p.portfolio_name, pp.total_return_1y
               FROM latest l
               JOIN portfolio_performance pp
                 ON pp.portfolio_id=l.portfolio_id AND pp.performance_date=l.latest_date
               JOIN portfolios p ON p.portfolio_id=l.portfolio_id
               ORDER BY pp.total_return_1y DESC LIMIT 1"""
    wrong = """SELECT p.portfolio_name, pp.volatility
               FROM portfolio_performance pp JOIN portfolios p ON p.portfolio_id=pp.portfolio_id
               ORDER BY pp.volatility DESC LIMIT 1"""
    agent = make_agent({question: [sql_call(wrong)]}, [query])

    reply = agent.answer_question(question, use_cache=False)

    assert reply.status == "ok"
    assert len(agent.llm.prompts) == 2
    assert "total_return_1y" in agent.llm.prompts[1]
    assert reply.steps[-1].columns == ["portfolio_name", "total_return_1y"]
    assert reply.answer.startswith("Interpreting this as the highest latest available one-year total return")


@pytest.mark.parametrize(
    "question",
    ["Which is the best portfolio?", "Which is the healthiest fund?", "Which is the highest-quality portfolio?"],
)
def test_ambiguous_portfolio_quality_question_asks_for_metric_without_model(make_agent, question):
    agent = make_agent()

    reply = agent.answer_question(question, use_cache=False)

    assert reply.status == "clarify"
    assert "which measure" in reply.answer.casefold()
    assert agent.llm.prompts == []


@pytest.mark.parametrize(
    ("question", "metric", "direction"),
    [
        ("Which is the safest portfolio?", "volatility", "ASC"),
        ("Which is the most efficient fund?", "sharpe_ratio", "DESC"),
    ],
)
def test_documented_portfolio_defaults_reach_the_planner(make_agent, question, metric, direction):
    query = f"""WITH latest AS (
                    SELECT portfolio_id, MAX(performance_date) AS latest_date
                    FROM portfolio_performance WHERE {metric} IS NOT NULL GROUP BY portfolio_id
                )
                SELECT p.portfolio_name, pp.{metric}
                FROM latest l JOIN portfolio_performance pp
                  ON pp.portfolio_id=l.portfolio_id AND pp.performance_date=l.latest_date
                JOIN portfolios p ON p.portfolio_id=l.portfolio_id
                ORDER BY pp.{metric} {direction} LIMIT 1"""
    agent = make_agent({question: [sql_call(query)]})

    reply = agent.answer_question(question, use_cache=False)

    assert reply.status == "ok"
    assert f"{metric}; {direction} order" in agent.llm.prompts[0]


def test_hybrid_plan_needs_one_model_call(make_agent):
    question = "Exposure of the two largest funds"
    plan = [
        sql_call("SELECT portfolio_name FROM portfolios ORDER BY total_aum DESC LIMIT 2"),
        ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True}),
    ]
    agent = make_agent({question: plan})
    reply = agent.answer_question(question)
    assert [s.tool for s in reply.steps] == ["run_sql", "exposure_calculator", "exposure_calculator"]
    assert len(agent.llm.prompts) == 1
    assert "Total Stock Market Index Fund" in reply.answer


def test_hybrid_with_no_matching_portfolios_is_handled(make_agent):
    question = "Exposure of funds with negative AUM"
    plan = [
        sql_call("SELECT portfolio_name FROM portfolios WHERE total_aum < 0"),
        ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True}),
    ]
    reply = make_agent({question: plan}).answer_question(question)
    assert reply.status == "ok" and "No portfolios matched" in reply.answer


def test_invalid_sql_is_repaired_once(make_agent):
    question = "Count the portfolios please"
    agent = make_agent({question: [sql_call("SELECT nope FROM portfolios")]}, ["SELECT COUNT(*) FROM portfolios"])
    reply = agent.answer_question(question)
    assert reply.status == "ok" and reply.steps[0].rows == [[13]]
    assert reply.llm["calls"] == 2
    assert "no such column: nope" in agent.llm.prompts[1]


def test_repair_stops_after_one_attempt(make_agent):
    question = "Count again"
    agent = make_agent({question: [sql_call("SELECT nope FROM portfolios")]}, ["SELECT still_bad FROM portfolios"])
    reply = agent.answer_question(question)
    assert reply.status == "error" and len(agent.llm.prompts) == 2


def test_blocked_sql_is_never_repaired(make_agent):
    question = "Remove everything"
    agent = make_agent({question: [sql_call("DROP TABLE portfolios")]}, ["SELECT 1"])
    reply = agent.answer_question(question)
    assert reply.status == "blocked" and len(agent.llm.prompts) == 1


def test_decline_and_clarify_statuses(make_agent):
    agent = make_agent(
        {
            "Should I buy?": [ToolCall("decline", {"kind": "advice", "message": "I report data only."})],
            "the income one": [ToolCall("decline", {"kind": "ambiguous", "message": "Which fund?"})],
        }
    )
    assert agent.answer_question("Should I buy?").status == "declined"
    assert agent.answer_question("the income one").status == "clarify"


def test_unknown_tool_from_model_is_an_error(make_agent):
    question = "Do a thing"
    assert make_agent({question: [ToolCall("rm_rf", {})]}).answer_question(question).status == "error"


def test_results_are_never_sent_to_the_model(make_agent):
    question = "Which fund is first alphabetically?"
    agent = make_agent(
        {question: [sql_call("SELECT nope FROM portfolios ORDER BY 1 LIMIT 1")]},
        ["SELECT portfolio_name FROM portfolios ORDER BY 1 LIMIT 1"],
    )
    reply = agent.answer_question(question)
    assert reply.steps[0].rows == [["Balanced Portfolio"]]
    assert all("Balanced Portfolio" not in prompt for prompt in agent.llm.prompts)


def test_model_title_with_invented_number_is_dropped(make_agent):
    question = "Total AUM of high risk funds?"
    sql = "SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level='High'"
    reply = make_agent({question: [sql_call(sql, "Total is 999")]}).answer_question(question)
    assert "999" not in reply.answer and "85,000,000" in reply.answer


def test_model_outage_is_reported_cleanly(make_agent):
    class Down:
        def plan(self, system, prompt):
            raise LLMError("boom")

    agent = make_agent()
    agent.llm = Down()
    reply = agent.answer_question("How many bonds are there?")  # Not a question the local planner supports.
    assert reply.status == "error" and "unavailable" in reply.answer and "boom" not in reply.answer
    assert reply.route == "error" and reply.llm["failure_category"]


def test_no_api_key_still_serves_direct_calculator(settings):
    agent = PortfolioAgent(settings)
    assert agent.llm is None
    assert agent.answer_question("sector exposure of Balanced Portfolio").status == "ok"
    missing = agent.answer_question("How many bonds are there?")
    assert missing.status == "unsupported" and "Gemini is not configured" in missing.answer and missing.route == "error"


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_input_validation(make_agent, question):
    assert make_agent().answer_question(question).status == "invalid"


def test_cache_hit_skips_the_model_and_returns_a_copy(make_agent):
    question = "How many portfolios exist?"
    agent = make_agent({question: [sql_call("SELECT COUNT(*) FROM portfolios")]})
    first = agent.answer_question(question)
    first.steps[0].rows[0][0] = "tampered"
    second = agent.answer_question("  how many PORTFOLIOS exist? ")
    assert second.route == "cache" and second.steps[0].rows == [[13]]
    assert len(agent.llm.prompts) == 1


def test_cache_does_not_confuse_high_and_low(make_agent):
    high, low = "Total AUM for high risk funds", "Total AUM for low risk funds"
    agent = make_agent(
        {
            high: [sql_call("SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level='High'")],
            low: [sql_call("SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level='Low'")],
        }
    )
    assert agent.answer_question(high).answer != agent.answer_question(low).answer


def test_failures_are_not_cached(make_agent):
    question = "A flaky question"
    agent = make_agent()
    assert agent.answer_question(question).status == "error"
    agent.llm.script[question] = [sql_call("SELECT 1")]
    assert agent.answer_question(question).status == "ok"


def test_concurrent_questions_all_answer_correctly(make_agent):
    questions = {f"How many holdings in fund {i}?": i for i in range(1, 14)}
    script = {q: [sql_call(f"SELECT COUNT(*) FROM holdings WHERE portfolio_id = {i}")] for q, i in questions.items()}
    agent = make_agent(script)
    truth = {q: agent.answer_question(q, use_cache=False).steps[0].rows for q in questions}
    errors = []

    def worker(question):
        for _ in range(20):
            if agent.answer_question(question, use_cache=False).steps[0].rows != truth[question]:
                errors.append(question)

    threads = [threading.Thread(target=worker, args=(q,)) for q in questions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_repair_can_decline_instead_of_substituting_a_metric(make_agent):
    question = "Highest Sharpe ratio in risk metrics?"
    agent = make_agent({question: [sql_call("SELECT sharpe_ratio FROM risk_metrics")]})
    agent.llm.repairs = []
    original = agent.llm.plan

    def plan(system, prompt):
        if "<failed_sql>" in prompt:
            from portfolio_agent.llm import LLMResponse

            return LLMResponse(
                [ToolCall("decline", {"kind": "no_data", "message": "Not in risk_metrics."})], "scripted"
            )
        return original(system, prompt)

    agent.llm.plan = plan
    reply = agent.answer_question(question)
    assert reply.status == "declined" and reply.answer == "Not in risk_metrics."


def test_stored_plan_with_invalid_sql_and_no_model_does_not_crash(settings):
    agent = PortfolioAgent(settings)
    assert agent.llm is None
    agent.preload("A stored question", [sql_call("SELECT nope FROM portfolios")])
    assert agent.cache.get("a stored question") is None


def test_daily_model_cap_is_shared_but_spares_cache_and_direct_calculator(settings):
    from portfolio_agent.llm import ScriptedLLM

    questions = ["Count the portfolios", "Count the bonds", "Count the stocks"]
    script = {q: [sql_call("SELECT 1")] for q in questions}
    agent = PortfolioAgent(dataclasses.replace(settings, daily_model_questions=2), llm=ScriptedLLM(script))
    assert agent.answer_question(questions[0]).status == "ok"
    assert agent.answer_question(questions[1]).status == "ok"
    limited = agent.answer_question(questions[2])
    assert limited.status == "error" and "daily limit" in limited.answer
    assert agent.answer_question(questions[0]).route == "cache"
    assert agent.answer_question("sector exposure of Balanced Portfolio").route == "direct_calculator"


@pytest.mark.parametrize(
    "question",
    [
        "Show me the top 5 holdings by cost basis in the Growth Equity Fund",
        "List the five Growth Equity Fund positions ranked by cost basis",
    ],
)
def test_holding_row_projection_is_validated_and_repaired(make_agent, question):
    from portfolio_agent.evaluation import Evaluator, load_ground_truth

    incomplete = """SELECT s.symbol, s.company_name, h.cost_basis
                    FROM holdings h JOIN securities s ON s.security_id=h.security_id
                    JOIN portfolios p ON p.portfolio_id=h.portfolio_id
                    WHERE p.portfolio_name='Growth Equity Fund'
                    ORDER BY h.cost_basis DESC LIMIT 5"""
    complete = """SELECT h.holding_id, s.symbol, s.company_name, h.quantity, h.cost_basis
                   FROM holdings h JOIN securities s ON s.security_id=h.security_id
                   JOIN portfolios p ON p.portfolio_id=h.portfolio_id
                   WHERE p.portfolio_name='Growth Equity Fund'
                   ORDER BY h.cost_basis DESC LIMIT 5"""
    agent = make_agent({question: [sql_call(incomplete)]}, [complete])
    reply = agent.answer_question(question, use_cache=False)
    assert reply.status == "ok"
    assert reply.llm["calls"] == 2
    assert reply.steps[-1].columns == ["holding_id", "symbol", "company_name", "quantity", "cost_basis"]
    assert len(reply.steps[-1].rows) == 5
    assert "holding-level output is missing" in agent.llm.prompts[-1]
    ground_truth = load_ground_truth(agent.settings.data_dir.parent / "ground_truth_dataset.json")
    case = next(c for c in ground_truth if c.id == "gt05")
    if question == case.question:
        assert Evaluator(agent, agent.settings.data_dir)._grade(case, reply)[0] == "exact"


@pytest.mark.parametrize(
    "question",
    [
        "Find portfolios that have holdings in more than 5 different sectors and show their diversification metrics",
        "Which portfolios have more than five stock sectors, and what is their sector diversification ratio?",
    ],
)
def test_assessment_diversification_definition_is_independently_verified(make_agent, question):
    from portfolio_agent.evaluation import Evaluator, load_ground_truth

    wrong = """SELECT p.portfolio_name,
                      COUNT(DISTINCT s.sector_id) AS sector_count,
                      COUNT(h.holding_id) AS total_holdings,
                      ROUND(1.0 / COUNT(h.holding_id), 3) AS diversification_ratio
               FROM portfolios p JOIN holdings h ON h.portfolio_id=p.portfolio_id
               JOIN securities s ON s.security_id=h.security_id
               GROUP BY p.portfolio_id HAVING sector_count > 5"""
    correct = """SELECT p.portfolio_name,
                        COUNT(DISTINCT CASE WHEN s.asset_type='Stock' THEN s.sector_id END) AS sector_count,
                        COUNT(h.holding_id) AS total_holdings,
                        ROUND(CAST(COUNT(DISTINCT CASE WHEN s.asset_type='Stock' THEN s.sector_id END) AS REAL)
                              / COUNT(h.holding_id), 3) AS diversification_ratio
                 FROM portfolios p JOIN holdings h ON h.portfolio_id=p.portfolio_id
                 JOIN securities s ON s.security_id=h.security_id
                 GROUP BY p.portfolio_id HAVING sector_count > 5"""
    agent = make_agent({question: [sql_call(wrong)]}, [correct])
    reply = agent.answer_question(question, use_cache=False)
    assert reply.status == "ok"
    assert reply.llm["calls"] == 2
    assert reply.steps[-1].columns == ["portfolio_name", "sector_count", "total_holdings", "diversification_ratio"]
    assert "assessment-defined diversification calculation" in agent.llm.prompts[-1]
    assert "diversification_ratio" in agent._system
    ground_truth = load_ground_truth(agent.settings.data_dir.parent / "ground_truth_dataset.json")
    case = next(c for c in ground_truth if c.id == "gt08")
    if question == case.question:
        assert Evaluator(agent, agent.settings.data_dir)._grade(case, reply)[0] == "exact"


def test_discovered_exposure_request_completes_sql_and_calculator(settings, make_agent):
    from portfolio_agent.evaluation import Evaluator, load_extended

    case = next(c for c in load_extended(settings.data_dir.parent / "eval" / "extended_dataset.json") if c.id == "x20")
    wrong_global_latest = """SELECT p.portfolio_name FROM risk_metrics r
                             JOIN portfolios p ON p.portfolio_id=r.portfolio_id
                             WHERE r.calculation_date=(SELECT MAX(calculation_date) FROM risk_metrics)
                             ORDER BY r.beta DESC LIMIT 1"""
    latest_per_portfolio = """WITH latest AS (
                                 SELECT portfolio_id, MAX(calculation_date) AS max_date
                                 FROM risk_metrics GROUP BY portfolio_id)
                             SELECT p.portfolio_name FROM risk_metrics r
                             JOIN latest l ON l.portfolio_id=r.portfolio_id AND l.max_date=r.calculation_date
                             JOIN portfolios p ON p.portfolio_id=r.portfolio_id
                             ORDER BY r.beta DESC LIMIT 1"""
    agent = make_agent({case.question: [sql_call(wrong_global_latest)]}, [latest_per_portfolio])
    evaluator = Evaluator(agent, settings.data_dir)
    paraphrase = "Show the sector mix of the portfolio with max beta"
    assert agent._requires_hybrid(paraphrase, agent.linker.link(paraphrase))
    reply = agent.answer_question(case.question, use_cache=False)
    verdict, detail, tools_correct = evaluator._grade(case, reply)
    assert verdict == "exact", detail
    assert tools_correct
    assert [step.tool for step in reply.steps] == ["run_sql", "exposure_calculator"]
