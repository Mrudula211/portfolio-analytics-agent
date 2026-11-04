from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.config import Settings
from portfolio_agent.db import build_database
from portfolio_agent.llm import ScriptedLLM, ToolCall


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
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
