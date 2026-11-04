"""Compare real Gemini latency for candidate models, using the agent's actual prompt and tools.

    python scripts/model_latency_benchmark.py gemini-3.1-flash-lite gemini-3.5-flash --samples 8
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_agent.agent import PortfolioAgent
from portfolio_agent.config import Settings
from portfolio_agent.llm import GeminiClient, LLMError

QUESTIONS = [
    "Which securities are in the Energy sector?",
    "How many bonds are there?",
    "What is the average coupon of the bonds?",
    "List the portfolios with low target risk",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+")
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()
    settings = Settings.from_env()
    system = PortfolioAgent(settings)._full_system
    print(f"{'model':28} {'ok':>5} {'first s':>8} {'p50 s':>7} {'max s':>7}")
    for model in args.models:
        client = GeminiClient(replace(settings, gemini_model=model, gemini_fallback_models=()))
        times, failures = [], 0
        for index in range(args.samples):
            started = time.perf_counter()
            try:
                client.plan(system, f"<question>{QUESTIONS[index % len(QUESTIONS)]}</question>")
                times.append(time.perf_counter() - started)
            except LLMError:
                failures += 1
        if times:
            ok = f"{len(times)}/{args.samples}"
            print(f"{model:28} {ok:>5} {times[0]:8.2f} {statistics.median(times[1:] or times):7.2f} {max(times):7.2f}")
        else:
            print(f"{model:28} all {failures} calls failed")


if __name__ == "__main__":
    main()
