"""The evaluator must check the whole hybrid chain, not only that both tools ran.

Case x20 selects the portfolio with the highest latest beta, then calculates its sector exposure.
Each test builds an agent reply by hand with one specific defect.
"""

import pytest

from portfolio_agent.agent import AgentResponse, Step
from portfolio_agent.config import ROOT
from portfolio_agent.evaluation import FAIL, Evaluator, load_extended

SELECTED = "Tech Innovation Fund"  # What x20's reference query selects.
OTHER = "Balanced Portfolio"


@pytest.fixture
def case():
    return next(c for c in load_extended(ROOT / "eval" / "extended_dataset.json") if c.id == "x20")


@pytest.fixture
def evaluator(settings, make_agent):
    return Evaluator(make_agent(), settings.data_dir)


def selection(*names):
    return Step("run_sql", {"sql": "SELECT ..."}, ["portfolio_name"], [[name] for name in names])


def exposure(evaluator, input_name, result_name=None):
    result = evaluator.agent.tools.exposure_calculator(result_name or input_name).to_dict()
    return Step("exposure_calculator", {"portfolio_name": input_name}, exposure=result)


def grade(evaluator, case, *steps):
    reply = AgentResponse(case.question, "ok", "", "gemini", steps=list(steps))
    return evaluator._grade(case, reply)


def test_correct_selection_and_matching_calculator_passes(evaluator, case):
    verdict, detail, tool_correct = grade(evaluator, case, selection(SELECTED), exposure(evaluator, SELECTED))
    assert verdict == "exact" and tool_correct, detail


def test_calculator_run_for_the_wrong_portfolio_fails(evaluator, case):
    verdict, detail, tool_correct = grade(evaluator, case, selection(SELECTED), exposure(evaluator, OTHER))
    assert verdict == FAIL and "do not match SQL selection" in detail and not tool_correct


def test_result_with_a_forged_portfolio_label_is_caught_by_its_figures(evaluator, case):
    """The label says the selected fund, but the figures describe another: the oracle comparison fails it."""
    forged = exposure(evaluator, SELECTED, result_name=OTHER)
    forged.exposure["portfolio_name"] = SELECTED
    verdict, detail, _ = grade(evaluator, case, selection(SELECTED), forged)
    assert verdict == FAIL and ("sectors" in detail or "!=" in detail)


def test_input_that_resolves_to_a_different_portfolio_than_the_result_fails(evaluator, case):
    step = exposure(evaluator, SELECTED)
    step.input["portfolio_name"] = OTHER  # The tool was asked about one fund and answered about another.
    verdict, detail, _ = grade(evaluator, case, selection(SELECTED), step)
    assert verdict == FAIL and "calculator input" in detail and "resolved to" in detail


def test_sql_returning_no_portfolio_fails(evaluator, case):
    verdict, detail, _ = grade(evaluator, case, selection(), exposure(evaluator, SELECTED))
    assert verdict == FAIL and "no portfolios" in detail


def test_ambiguous_selection_of_several_portfolios_fails(evaluator, case):
    steps = [selection(SELECTED, OTHER), exposure(evaluator, SELECTED), exposure(evaluator, OTHER)]
    verdict, detail, _ = grade(evaluator, case, *steps)
    assert verdict == FAIL and "SQL selection failed" in detail


@pytest.mark.parametrize("bad_input", ["", "international", "Atlantis Fund"])
def test_invalid_calculator_parameters_fail(evaluator, case, bad_input):
    failed = Step("exposure_calculator", {"portfolio_name": bad_input}, error="ambiguous portfolio")
    verdict, _, tool_correct = grade(evaluator, case, selection(SELECTED), failed)
    assert verdict == FAIL and not tool_correct


def test_calculator_before_the_selection_fails(evaluator, case):
    verdict, _, _ = grade(evaluator, case, exposure(evaluator, SELECTED), selection(SELECTED))
    assert verdict == FAIL


def test_tool_category_alone_is_not_enough(evaluator, case):
    """Both tools ran and the exposure is plausible, but for the wrong portfolio: still a failure."""
    verdict, detail, tool_correct = grade(evaluator, case, selection(OTHER), exposure(evaluator, OTHER))
    assert verdict == FAIL and "SQL selection failed" in detail and not tool_correct
