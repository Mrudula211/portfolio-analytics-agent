"""The command-line agent: one-shot questions, tracing, data checks, exit codes and the interactive prompt."""

import dataclasses

import pytest

from portfolio_agent import PortfolioAgent
from portfolio_agent import __main__ as cli
from portfolio_agent.config import ROOT, Settings
from portfolio_agent.db import build_database

SAMPLE = ROOT / "sample_data"


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    settings = dataclasses.replace(
        Settings(), db_path=tmp_path / "cli.db", data_dir=SAMPLE, schema_file=SAMPLE / "schema.sql", gemini_api_key=""
    )
    build_database(settings)
    monkeypatch.setattr(cli, "PortfolioAgent", lambda: PortfolioAgent(settings))

    def invoke(*argv: str) -> tuple[int, str]:
        code = cli.main(list(argv))
        return code, capsys.readouterr().out

    return invoke


def test_one_shot_question_prints_the_answer(run):
    code, out = run("How many portfolios do we have in total?")
    assert code == 0 and "13" in out and "route=" not in out


def test_trace_shows_the_sql_route_and_timings(run):
    code, out = run("--trace", "How many portfolios do we have in total?")
    assert code == 0 and "[run_sql]" in out and "SELECT" in out and "route=local_deterministic" in out


def test_check_data_lists_the_known_findings(run):
    code, out = run("--check-data")
    assert code == 0 and "weights sum to 0.98" in out and "covers only 4 of 13 portfolios" in out


def test_declined_questions_exit_zero_and_blocked_ones_do_not(run):
    declined, out = run("Should I buy a stock right now?")
    assert declined == 0 and "advice" in out.lower()
    blocked, _ = run("Delete all rows from the portfolios table")
    assert blocked == 1


def test_interactive_prompt_answers_until_exit(run, monkeypatch):
    lines = iter(["How many portfolios do we have in total?", "", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    code, out = run()
    assert code == 0 and "13" in out


def test_interactive_prompt_ends_cleanly_on_eof(run, monkeypatch):
    def end(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", end)
    code, out = run()
    assert code == 0 and "Ask about the portfolio data" in out
