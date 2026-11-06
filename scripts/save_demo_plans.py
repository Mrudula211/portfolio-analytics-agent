"""Ask Gemini once for each demo question and store its plan in portfolio_agent/demo_plans.json.

The web app runs these stored plans against the database at start-up, so example questions
answer instantly and use none of the free tier's daily quota. Plans contain only tool calls.

    python scripts/save_demo_plans.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_agent import PortfolioAgent  # noqa: E402
from portfolio_agent.api import DEMO_PLANS  # noqa: E402
from portfolio_agent.prompts import build_user_prompt  # noqa: E402

# None of these are evaluation questions; tests/test_no_leakage.py enforces it.
QUESTIONS = [
    "Sector breakdown for the Balanced Portfolio",
    "Which portfolio has the largest AUM?",
    "Top 3 holdings by market value in the Small Cap Value Fund",
    "Average Sharpe ratio of each portfolio over the period",
    "Show sector exposures for all high risk portfolios",
    "Will NVIDIA's price go up next week?",
]


def main() -> None:
    agent = PortfolioAgent()
    demos = []
    for question in QUESTIONS:
        links = agent.linker.link(question)
        calls = []
        if not agent._is_simple_exposure(question, links):  # The fast path needs no plan.
            calls = [asdict(c) for c in agent.llm.plan(agent._system, build_user_prompt(question, links)).calls]
        demos.append({"question": question, "calls": calls})
        print(question, "->", [c["name"] for c in calls] or "fast path")
    DEMO_PLANS.write_text(json.dumps(demos, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
