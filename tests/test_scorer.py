"""The scorer must fail wrong answers. Most of these are mutations of correct results."""

import pytest
from conftest import sql_call

from portfolio_agent.agent import AgentResponse, Step
from portfolio_agent.config import ROOT
from portfolio_agent.evaluation import (
    EQUIVALENT,
    EXACT,
    FAIL,
    PARTIAL,
    Evaluator,
    ExposureOracle,
    compare_results,
    load_ground_truth,
    summarize,
    values_match,
)

COLS = ["name", "value"]
ROWS = [["A", 1.5], ["B", 2.5], ["C", 3.5]]


def test_identical_is_exact():
    assert compare_results(COLS, ROWS, COLS, ROWS)[0] == EXACT


def test_row_order_ignored_unless_top_n():
    shuffled = ROWS[::-1]
    assert compare_results(COLS, ROWS, COLS, shuffled)[0] == EXACT
    assert compare_results(COLS, ROWS, COLS, shuffled, ordered=True)[0] == FAIL


def test_column_order_and_names_ignored():
    actual = [[1.5, "A"], [2.5, "B"], [3.5, "C"]]
    assert compare_results(COLS, ROWS, ["v", "n"], actual)[0] == EXACT


def test_values_paired_with_wrong_row_fail():
    swapped = [["A", 2.5], ["B", 1.5], ["C", 3.5]]
    assert compare_results(COLS, ROWS, COLS, swapped)[0] == FAIL


def test_wrong_value_fails():
    wrong = [["A", 1.5], ["B", 2.5], ["C", 9.9]]
    assert compare_results(COLS, ROWS, COLS, wrong)[0] == FAIL


def test_missing_row_fails():
    assert compare_results(COLS, ROWS, COLS, ROWS[:2])[0] == FAIL


def test_extra_real_row_fails():
    assert compare_results(COLS, ROWS, COLS, ROWS + [["D", 4.5]])[0] == FAIL


def test_extra_column_is_equivalent():
    actual = [row + [99] for row in ROWS]
    assert compare_results(COLS, ROWS, COLS + ["x"], actual)[0] == EQUIVALENT


def test_extra_zero_row_is_equivalent():
    """'For each portfolio' read with LEFT JOIN lists funds with no tech holdings as zero."""
    assert compare_results(COLS, ROWS, COLS, ROWS + [["D", 0.0]])[0] == EQUIVALENT
    assert compare_results(COLS, ROWS, COLS, ROWS + [["D", None]])[0] == EQUIVALENT


def test_missing_requested_column_is_partial_not_pass():
    verdict, detail = compare_results(COLS, ROWS, ["name"], [[r[0]] for r in ROWS])
    assert verdict == PARTIAL and "value" in detail


def test_missing_column_with_extra_zero_rows_is_partial():
    actual = ROWS + [["D", 0.0]]
    expected = [row + [10.0] for row in ROWS]
    verdict, detail = compare_results(COLS + ["total"], expected, COLS, actual)
    assert verdict == PARTIAL and "total" in detail


def test_empty_result_fails_when_rows_expected():
    assert compare_results(COLS, ROWS, COLS, [])[0] == FAIL


def test_rounding_tolerance_is_limited():
    assert values_match(84.67, 84.6666)
    assert values_match(0.333, 0.33333)
    assert not values_match(84.67, 84.7)
    assert not values_match(100.0, 101.0)
    assert not values_match("Active", "Passive")
    assert not values_match(None, 0)


def _ground_truth_case(case_id):
    return next(c for c in load_ground_truth(ROOT / "ground_truth_dataset.json") if c.id == case_id)


def test_wrong_filter_in_model_sql_fails_end_to_end(settings, make_agent):
    case = _ground_truth_case("gt04")
    sql = "SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level = 'Low'"
    agent = make_agent({case.question: [sql_call(sql)]})
    assert Evaluator(agent, settings.data_dir).run_case(case).verdict == FAIL


def test_left_join_reading_of_question_seven_passes(settings, make_agent):
    case = _ground_truth_case("gt07")
    tech = "COALESCE(SUM(CASE WHEN sec.sector_name = 'Technology' THEN h.quantity * s.current_price END), 0)"
    sql = f"""SELECT p.portfolio_name, {tech} AS tech_value,
                     SUM(h.quantity * s.current_price) AS total_value,
                     {tech} * 100.0 / SUM(h.quantity * s.current_price) AS tech_percentage
              FROM portfolios p JOIN holdings h ON h.portfolio_id = p.portfolio_id
              JOIN securities s ON s.security_id = h.security_id
              LEFT JOIN sectors sec ON sec.sector_id = s.sector_id GROUP BY p.portfolio_id"""
    result = Evaluator(make_agent({case.question: [sql_call(sql)]}), settings.data_dir).run_case(case)
    assert result.verdict == EQUIVALENT, result.detail


def test_using_sql_for_exposure_question_fails_tool_selection(settings, make_agent):
    case = _ground_truth_case("gt09")
    evaluator = Evaluator(make_agent(), settings.data_dir)
    reply = AgentResponse(case.question, "ok", "x", "model", steps=[Step("run_sql", {"sql": "SELECT 1"}, ["a"], [[1]])])
    verdict, _, tool_correct = evaluator._grade(case, reply)
    assert verdict == FAIL and not tool_correct


def test_tampered_exposure_fails(settings, make_agent):
    case = _ground_truth_case("gt10")
    agent = make_agent()
    evaluator = Evaluator(agent, settings.data_dir)
    reply = agent.answer_question(case.question, use_cache=False)
    assert evaluator._grade(case, reply)[0] == EXACT
    reply.steps[0].exposure["exposures"][0]["exposure_pct"] += 1
    assert evaluator._grade(case, reply)[0] == FAIL


def test_oracle_matches_tool_for_every_portfolio(settings, make_agent):
    """Two independent implementations must agree on all 13 portfolios."""
    agent = make_agent()
    oracle = ExposureOracle(settings.data_dir)
    for name in agent.catalog.portfolio_names:
        tool = {e.sector: e.exposure_pct for e in agent.tools.exposure_calculator(name).exposures}
        truth = oracle.exposures(name)
        assert set(tool) == set(truth), name
        for sector, value in truth.items():
            assert tool[sector] == pytest.approx(value, abs=0.001), (name, sector)


def test_infra_errors_are_not_counted_as_wrong_answers(settings, make_agent):
    case = _ground_truth_case("gt01")
    result = Evaluator(make_agent(), settings.data_dir).run_case(case)  # No script, so the model is "down".
    assert result.verdict == "infra_error"
    summary = summarize([result])
    assert summary["cases_scored"] == 0 and summary["infra_errors"] == 1


def test_stability_counts_questions_whose_verdict_changes():
    from portfolio_agent.evaluation import CaseResult

    def result(case_id, verdict):
        return CaseResult(case_id, "c", "-", "q", verdict, "", True, "model", "ok", 1.0, 1.0, 1)

    runs = [result("a", EXACT), result("b", EXACT), result("a", EQUIVALENT), result("b", FAIL)]
    stability = summarize(runs)["stability"]
    assert stability == {"questions": 2, "consistent": 1, "unstable": ["b"]}
    assert summarize(runs[:2])["stability"] is None
