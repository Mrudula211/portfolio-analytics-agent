"""Evaluation data must not reach prompts, or accuracy would only measure memorisation."""

from portfolio_agent import prompts
from portfolio_agent.config import ROOT
from portfolio_agent.evaluation import load_extended, load_ground_truth
from portfolio_agent.metadata import GLOSSARY
from portfolio_agent.sql_guard import execute_select


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _cases():
    return load_ground_truth(ROOT / "ground_truth_dataset.json") + load_extended(
        ROOT / "eval" / "extended_dataset.json"
    )


def test_no_evaluation_question_or_query_in_prompts():
    prompt_text = _normalise(prompts.build_system_prompt("") + GLOSSARY)
    for case in _cases():
        assert _normalise(case.question) not in prompt_text, case.id
        if case.sql:
            assert _normalise(case.sql.rstrip(";")) not in prompt_text, case.id


def test_agent_code_does_not_read_or_embed_evaluation_answers():
    for path in (ROOT / "portfolio_agent").glob("*.py"):
        if path.name == "evaluation.py":  # The scorer reads the answers by design.
            continue
        source = _normalise(path.read_text(encoding="utf-8"))
        assert "ground_truth" not in source, path.name
        for case in _cases():
            assert _normalise(case.question) not in source, (path.name, case.id)


def test_every_reference_query_runs(settings):
    for case in _cases():
        if case.sql:
            assert execute_select(settings.db_path, case.sql).rows is not None, case.id
