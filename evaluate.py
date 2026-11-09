"""Evaluate the agent against the ground truth questions.

    python evaluate.py                       ground truth, live Gemini
    python evaluate.py --extended            adds the 30 extra cases: hybrid, safety, edge cases
    python evaluate.py --extended --resume   keeps scored results and reruns the rest
    python evaluate.py --local-fallback      the real agent with no model: its deterministic planner only
    python evaluate.py --self-test           replays reference plans, no model or API key

Three different things are measured, and their scores are never interchangeable:
  live            Gemini writes the plan; this is model accuracy.
  --local-fallback  the production agent's own deterministic planner answers; no model exists, and every
                  network connection is blocked and counted, so zero API calls is demonstrated, not claimed.
  --self-test     reference plans are replayed through the tools and the scorer. It checks the pipeline,
                  not any planner.
The answer cache is always off here, and stored demo plans are never loaded.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import socket
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


def block_network() -> list[int]:
    """Refuse every outgoing connection and count the attempts."""
    attempts = [0]

    def refuse(self, *args, **kwargs):
        attempts[0] += 1
        raise OSError("network access is disabled for the local evaluation")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    return attempts


def show(result: CaseResult) -> None:
    print(f"{result.id:5} {result.verdict:12} {result.route:20} {result.latency_ms:8.1f} ms  {result.question[:60]}")
    if result.verdict not in {"exact", "equivalent"}:
        print(f"      {result.detail}")
        if result.sql:
            print(f"      SQL: {result.sql}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extended", action="store_true", help="Include the 30 extra cases.")
    parser.add_argument("--self-test", action="store_true", help="Replay reference plans without a model.")
    parser.add_argument("--local-fallback", action="store_true", help="Run the real agent with its local planner only.")
    parser.add_argument("--runs", type=int, default=1, help="Repeat each case to measure stability.")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds between model calls, for rate limits.")
    parser.add_argument("--resume", action="store_true", help="Keep scored results in the report; rerun the rest.")
    parser.add_argument("--min-accuracy", type=float, default=0.0, help="Exit 1 if strict accuracy falls below this.")
    args = parser.parse_args()
    if args.self_test and args.local_fallback:
        parser.error("--self-test and --local-fallback measure different things; choose one")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.ERROR)

    cases = load_ground_truth(ROOT / "ground_truth_dataset.json")
    if args.extended:
        cases += load_extended(ROOT / "eval" / "extended_dataset.json")

    settings = Settings.from_env()
    attempts: list[int] | None = None
    if args.local_fallback:
        attempts = block_network()
        settings = dataclasses.replace(settings, gemini_api_key="")  # No client is ever built.
    agent = PortfolioAgent(settings, llm=ScriptedLLM(oracle_script(cases)) if args.self_test else None)
    if args.local_fallback and agent.llm is not None:
        raise SystemExit("A model client exists in --local-fallback mode; refusing to continue.")
    if not (args.self_test or args.local_fallback) and agent.llm is None:
        print("GEMINI_API_KEY is not set. Add it to .env, or use --local-fallback or --self-test.")
        return 2

    kind = "self_test" if args.self_test else "local_fallback" if args.local_fallback else "live"
    name = kind + ("_extended" if args.extended else "")
    finished = load_finished(ROOT / "reports" / f"{name}.json") if args.resume else []
    done = {r.id for r in finished}
    remaining = [c for c in cases if c.id not in done]
    results = finished + Evaluator(agent, settings.data_dir).run(
        remaining, runs=args.runs, delay_s=args.delay, on_result=show
    )
    order = {c.id: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r.id])
    summary = summarize(results)

    mode = {
        "self_test": "SELF-TEST: reference plans replayed, not a planner's accuracy",
        "local_fallback": "LOCAL FALLBACK: the production agent's deterministic planner, no model",
        "live": "live model",
    }[kind]
    meta = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "dataset": "ground truth + extended" if args.extended else "ground truth",
    }
    if attempts is not None:
        meta.update(
            gemini_client="none (no API key, no client built)",
            network_connection_attempts=attempts[0],
            cache="disabled",
            stored_demo_plans="not loaded",
        )
    path = write_report(results, summary, meta, ROOT / "reports", name)

    scored = f"{summary['cases_scored']} scored, {summary['infra_errors']} infra errors"
    print(f"\nMode:            {mode}")
    print(f"Strict accuracy: {summary['strict_accuracy']:.1%}  ({scored})")
    print(f"Lenient:         {summary['lenient_accuracy']:.1%}")
    print(f"Tool selection:  {summary['tool_selection_accuracy']:.1%}")
    print(f"Verdicts:        {summary['verdicts']}")
    if attempts is not None:
        print(f"Network attempts: {attempts[0]}  (Gemini client: none)")
    if summary["stability"]:
        stable = summary["stability"]
        once = f", {len(stable['scored_once'])} scored only once" if stable["scored_once"] else ""
        print(f"Stability:       {stable['consistent']} of {stable['questions']} repeated questions consistent{once}")
    print(f"SQL efficiency:  {summary['performance_adjusted_sql_score']}")
    for route, stats in summary["by_route"].items():
        print(f"Latency {route:20} n={stats['count']:<4} p50={stats['p50_ms']} ms  p95={stats['p95_ms']} ms")
    print(f"Report:          {path.relative_to(ROOT)}")
    return 1 if summary["strict_accuracy"] < args.min_accuracy or (attempts and attempts[0]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
