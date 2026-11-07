import dataclasses
import threading

import pytest
from conftest import sql_call

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.llm import LLMError, ToolCall


def test_simple_exposure_uses_no_model(make_agent):
    agent = make_agent()
    reply = agent.answer_question("What are the sector exposures for the Tech Innovation Fund?")
    assert reply.route == "fast_path" and reply.status == "ok"
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
    assert agent.answer_question(question).route == "model"


def test_one_model_call_for_sql_question(make_agent):
    question = "How many portfolios exist?"
    agent = make_agent({question: [sql_call("SELECT COUNT(*) FROM portfolios", "Portfolio count")]})
    reply = agent.answer_question(question)
    assert reply.status == "ok" and "13" in reply.answer
    assert len(agent.llm.prompts) == 1


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
    reply = agent.answer_question("How many funds?")
    assert reply.status == "error" and "unavailable" in reply.answer and "boom" not in reply.answer


def test_no_api_key_still_serves_fast_path(settings):
    agent = PortfolioAgent(settings)
    assert agent.llm is None
    assert agent.answer_question("sector exposure of Balanced Portfolio").status == "ok"
    missing = agent.answer_question("How many funds?")
    assert missing.status == "error" and "GEMINI_API_KEY" in missing.answer


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


def test_daily_model_cap_is_shared_but_spares_cache_and_fast_path(settings):
    from portfolio_agent.llm import ScriptedLLM

    questions = ["Count the portfolios", "Count the bonds", "Count the stocks"]
    script = {q: [sql_call("SELECT 1")] for q in questions}
    agent = PortfolioAgent(dataclasses.replace(settings, daily_model_questions=2), llm=ScriptedLLM(script))
    assert agent.answer_question(questions[0]).status == "ok"
    assert agent.answer_question(questions[1]).status == "ok"
    limited = agent.answer_question(questions[2])
    assert limited.status == "error" and "daily limit" in limited.answer
    assert agent.answer_question(questions[0]).route == "cache"
    assert agent.answer_question("sector exposure of Balanced Portfolio").route == "fast_path"
