from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.config import ROOT, Settings
from portfolio_agent.db import build_database
from portfolio_agent.llm import ScriptedLLM, ToolCall

# The assessment's dataset, schema and reference answers are third-party and git-ignored (see README, "Data").
PRIVATE_FILES = ("data", "database_schema.sql", "ground_truth_dataset.json")
HAS_PRIVATE_DATA = all((ROOT / name).exists() for name in PRIVATE_FILES)
SKIP_REASON = "the third-party assessment dataset is not present (see README, 'Data')"

# These modules read the dataset when imported, so they cannot even be collected without it.
collect_ignore = [] if HAS_PRIVATE_DATA else ["test_dataset.py"]


NEEDS_PRIVATE_DATA = ("test_no_leakage.py", "test_streamlit_app.py", "test_planner_never_reads_the_ground_truth")


def pytest_collection_modifyitems(items):
    if HAS_PRIVATE_DATA:
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if any(marker in item.nodeid for marker in NEEDS_PRIVATE_DATA):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    if not HAS_PRIVATE_DATA:
        pytest.skip(SKIP_REASON)
    value = dataclasses.replace(Settings(), db_path=tmp_path_factory.mktemp("db") / "test.db", gemini_api_key="")
    build_database(value)
    return value


@pytest.fixture
def make_agent(settings):
    def factory(script=None, repairs=None) -> PortfolioAgent:
        return PortfolioAgent(settings, llm=ScriptedLLM(script or {}, repairs or []))

    return factory


def sql_call(sql: str, title: str = "") -> ToolCall:
    return ToolCall("run_sql", {"sql": sql, "title": title})
