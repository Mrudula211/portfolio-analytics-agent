"""The fictional sample dataset must build, show the documented quirks, and be answerable offline."""

import dataclasses

import pytest

from portfolio_agent import PortfolioAgent
from portfolio_agent.config import ROOT, Settings
from portfolio_agent.db import build_database, data_quality_findings

SAMPLE = ROOT / "sample_data"


@pytest.fixture(scope="module")
def sample_settings(tmp_path_factory) -> Settings:
    value = dataclasses.replace(
        Settings(),
        db_path=tmp_path_factory.mktemp("sample") / "sample.db",
        data_dir=SAMPLE,
        schema_file=SAMPLE / "schema.sql",
        gemini_api_key="",
    )
    build_database(value)
    return value


def test_sample_dataset_reproduces_the_quirks_the_agent_handles(sample_settings):
    findings = " ".join(data_quality_findings(sample_settings.db_path))
    assert "weights sum to 0.98" in findings
    assert "No equity holdings" in findings and "Bond Plus Fund" in findings
    assert "covers only 4 of 13 portfolios" in findings


def test_count_question_is_answered_without_a_model(sample_settings):
    reply = PortfolioAgent(sample_settings).answer_question("How many portfolios do we have in total?", use_cache=False)
    assert reply.status == "ok" and reply.route == "local_deterministic" and reply.steps[0].rows == [[13]]


def test_exposure_excludes_bonds_and_bond_only_funds_have_none(sample_settings):
    agent = PortfolioAgent(sample_settings)
    mixed = agent.answer_question("Sector exposure of Balanced Portfolio", use_cache=False)
    assert mixed.route == "direct_calculator" and any("3 bond holdings" in w for w in mixed.warnings)
    bonds = agent.answer_question("Sector exposure of Bond Plus Fund", use_cache=False)
    assert "no equit" in bonds.answer.lower()
