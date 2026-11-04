"""Evaluate the agent against the ground truth questions.

    python evaluate.py                     ground truth, live model
    python evaluate.py --extended          adds held-out, hybrid, safety and refusal cases
    python evaluate.py --extended --runs 3 repeats everything to expose unstable answers
    python evaluate.py --self-test         replays reference plans, no model or API key

--self-test verifies the tools, guard and scorer. Its score is not model accuracy.
The answer cache is always off here, so latencies and accuracy are never flattered by it.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extended", action="store_true", help="Include the held-out dataset.")
    parser.add_argument("--self-test", action="store_true", help="Replay reference plans without a model.")
    parser.add_argument("--runs", type=int, default=1, help="Repeat each case to measure stability.")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between model calls, for rate limits.")
    parser.add_argument("--schema-mode", choices=["full", "retrieved"], help="Override SCHEMA_MODE for an A/B test.")
    parser.add_argument("--min-accuracy", type=float, default=0.0, help="Exit 1 if strict accuracy falls below this.")
    parser.add_argument("--output", default="", help="Report name under reports/.")
    parser.add_argument("--resume", action="store_true", help="Keep scored results in the report; rerun the rest.")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.ERROR)

    cases = load_ground_truth(ROOT / "ground_truth_dataset.json")
    if args.extended:
        cases += load_extended(ROOT / "eval" / "extended_dataset.json")

    settings = Settings.from_env()
    if args.schema_mode:
        settings = dataclasses.replace(settings, schema_mode=args.schema_mode)
    llm = ScriptedLLM(oracle_script(cases)) if args.self_test else None
    agent = PortfolioAgent(settings, llm=llm)
    if not args.self_test and agent.llm is None:
        print("GEMINI_API_KEY is not set. Add it to .env, or use --self-test to check everything but the model.")
        return 2

    def show(result: CaseResult) -> None:
        print(f"{result.id:5} {result.verdict:12} {result.route:10} {result.latency_ms:9.1f} ms  {result.question[:70]}")
        if result.verdict not in {"exact", "equivalent"}:
            print(f"      {result.detail}")
            if result.sql:
                print(f"      SQL: {result.sql}")

    evaluator = Evaluator(agent, settings.data_dir)
    default_name = ("self_test" if args.self_test else f"live_{settings.schema_mode}") + ("_extended" if args.extended else "")
    report_name = args.output or default_name
    finished = load_finished(ROOT / "reports" / f"{report_name}.json") if args.resume else []
    done_ids = {r.id for r in finished}
    remaining = [c for c in cases if c.id not in done_ids]
    results = finished + evaluator.run(remaining, runs=args.runs, delay_s=args.delay, on_result=show)
    order = {c.id: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r.id])
    summary = summarize(results)

    model = "none (self-test)" if args.self_test else settings.gemini_model
    meta = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "SELF-TEST: reference plans replayed, not model accuracy" if args.self_test else "live model",
        "model": model,
        "schema_mode": settings.schema_mode,
        "runs": args.runs,
        "dataset": "ground truth + extended" if args.extended else "ground truth",
    }
    path = write_report(results, summary, meta, ROOT / "reports", report_name)

    print()
    print(f"Mode:            {meta['mode']}")
    print(f"Strict accuracy: {summary['strict_accuracy']:.1%}  ({summary['cases_scored']} scored, {summary['infra_errors']} infra errors)")
    print(f"Lenient:         {summary['lenient_accuracy']:.1%}")
    print(f"Tool selection:  {summary['tool_selection_accuracy']:.1%}")
    print(f"SQL efficiency:  {summary['performance_adjusted_sql_score']}")
    for route, stats in summary["by_route"].items():
        print(f"Latency {route:10} n={stats['count']:<4} p50={stats['p50_ms']} ms  p95={stats['p95_ms']} ms")
    print(f"Report:          {Path(path).relative_to(ROOT)}")
    return 1 if summary["strict_accuracy"] < args.min_accuracy else 0


if __name__ == "__main__":
    raise SystemExit(main())
