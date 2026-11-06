"""Evaluate the agent against the ground truth questions.

    python evaluate.py                     ground truth, live model
    python evaluate.py --extended          adds held-out, hybrid, safety and refusal cases
    python evaluate.py --extended --resume keeps scored results and reruns the rest
    python evaluate.py --self-test         replays reference plans, no model or API key

--self-test verifies the tools, guard and scorer. Its score is not model accuracy.
The answer cache is always off here, so results are never flattered by it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from portfolio_agent import PortfolioAgent
from portfolio_agent.config import ROOT, Settings
from portfolio_agent.evaluation import (
    CaseResult,
    Evaluator,
    load_extended,
    load_finished,
    load_ground_truth,
    oracle_script,
    summarize,
    write_report,
)
from portfolio_agent.llm import ScriptedLLM


def show(result: CaseResult) -> None:
    print(f"{result.id:5} {result.verdict:12} {result.route:10} {result.latency_ms:9.1f} ms  {result.question[:70]}")
    if result.verdict not in {"exact", "equivalent"}:
        print(f"      {result.detail}")
        if result.sql:
            print(f"      SQL: {result.sql}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extended", action="store_true", help="Include the held-out dataset.")
    parser.add_argument("--self-test", action="store_true", help="Replay reference plans without a model.")
    parser.add_argument("--runs", type=int, default=1, help="Repeat each case to measure stability.")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between model calls, for rate limits.")
    parser.add_argument("--resume", action="store_true", help="Keep scored results in the report; rerun the rest.")
    parser.add_argument("--min-accuracy", type=float, default=0.0, help="Exit 1 if strict accuracy falls below this.")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.ERROR)

    cases = load_ground_truth(ROOT / "ground_truth_dataset.json")
    if args.extended:
        cases += load_extended(ROOT / "eval" / "extended_dataset.json")

    settings = Settings.from_env()
    agent = PortfolioAgent(settings, llm=ScriptedLLM(oracle_script(cases)) if args.self_test else None)
    if not args.self_test and agent.llm is None:
        print("GEMINI_API_KEY is not set. Add it to .env, or use --self-test to check everything but the model.")
        return 2

    name = ("self_test" if args.self_test else "live") + ("_extended" if args.extended else "")
    finished = load_finished(ROOT / "reports" / f"{name}.json") if args.resume else []
    done = {r.id for r in finished}
    remaining = [c for c in cases if c.id not in done]
    results = finished + Evaluator(agent, settings.data_dir).run(
        remaining, runs=args.runs, delay_s=args.delay, on_result=show
    )
    order = {c.id: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r.id])
    summary = summarize(results)

    meta = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "SELF-TEST: reference plans replayed, not model accuracy" if args.self_test else "live model",
        "dataset": "ground truth + extended" if args.extended else "ground truth",
    }
    path = write_report(results, summary, meta, ROOT / "reports", name)

    scored = f"{summary['cases_scored']} scored, {summary['infra_errors']} infra errors"
    print(f"\nStrict accuracy: {summary['strict_accuracy']:.1%}  ({scored})")
    print(f"Lenient:         {summary['lenient_accuracy']:.1%}")
    print(f"Tool selection:  {summary['tool_selection_accuracy']:.1%}")
    if summary["stability"]:
        stable = summary["stability"]
        print(f"Stability:       {stable['consistent']} of {stable['questions']} questions, same verdict every run")
    print(f"SQL efficiency:  {summary['performance_adjusted_sql_score']}")
    for route, stats in summary["by_route"].items():
        print(f"Latency {route:10} n={stats['count']:<4} p50={stats['p50_ms']} ms  p95={stats['p95_ms']} ms")
    print(f"Report:          {path.relative_to(ROOT)}")
    return 1 if summary["strict_accuracy"] < args.min_accuracy else 0


if __name__ == "__main__":
    raise SystemExit(main())
