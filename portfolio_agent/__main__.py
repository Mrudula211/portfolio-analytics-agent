"""Command-line agent: `python -m portfolio_agent "question"`, or no question for a prompt."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .agent import AgentResponse, PortfolioAgent
from .db import data_quality_findings


def _print_reply(reply: AgentResponse, *, as_json: bool, trace: bool) -> None:
    if as_json:
        print(json.dumps(reply.to_dict(), indent=2, default=str))
        return
    print(reply.answer)
    for warning in reply.warnings:
        print(f"Note: {warning}")
    if trace:
        for step in reply.steps:
            print(f"[{step.tool}] {step.input.get('sql') or step.input.get('portfolio_name')}")
        print(f"[route={reply.route} status={reply.status} timings_ms={reply.timings_ms}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask questions about portfolio data.")
    parser.add_argument("question", nargs="*", help="The question. Omit it for an interactive prompt.")
    parser.add_argument("--json", action="store_true", help="Print the full response as JSON.")
    parser.add_argument("--trace", action="store_true", help="Show tools, SQL and timings.")
    parser.add_argument("--check-data", action="store_true", help="Print data quality findings and exit.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log what the agent is doing.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(levelname)s %(message)s")

    agent = PortfolioAgent()
    if args.check_data:
        for finding in data_quality_findings(agent.settings.db_path):
            print(f"- {finding}")
        return 0
    if args.question:
        reply = agent.answer_question(" ".join(args.question))
        _print_reply(reply, as_json=args.json, trace=args.trace)
        return 0 if reply.status in {"ok", "declined", "clarify"} else 1

    print("Ask about the portfolio data. Press Ctrl+C or type 'exit' to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if question.lower() in {"exit", "quit"}:
            return 0
        if question:
            _print_reply(agent.answer_question(question), as_json=args.json, trace=args.trace)


if __name__ == "__main__":
    raise SystemExit(main())
