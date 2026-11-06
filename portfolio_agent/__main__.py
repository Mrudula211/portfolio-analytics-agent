"""Command-line Portfolio Agent.

  python agent.py "How many portfolios do we have?"     one question
  python agent.py                                       interactive REPL
  python agent.py --trace "..."                         also print SQL, timings, decisions
  python agent.py --json "..."                          machine-readable output
  python agent.py --build-db                            (re)build portfolio_database.db from CSVs
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent import AgentResponse, PortfolioAgent, _fmt, response_to_dict
from .db import build_database


def render_table(columns, rows, limit: int = 50) -> str:
    if not columns:
        return ""
    cells = [[_fmt(v) for v in r] for r in rows[:limit]]
    widths = [max(len(str(c)), *(len(r[i]) for r in cells)) if cells else len(str(c)) for i, c in enumerate(columns)]
    line = "  ".join(str(c).ljust(w) for c, w in zip(columns, widths))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(v.rjust(w) if v[:1].isdigit() or v[:1] == "-" else v.ljust(w) for v, w in zip(r, widths)) for r in cells]
    if len(rows) > limit:
        out.append(f"... {len(rows) - limit} more rows")
    return "\n".join(out)


def render(resp: AgentResponse, trace: bool) -> str:
    parts = [f"[{resp.status}] {resp.text}"]
    if resp.columns and resp.rows:
        parts.append(render_table(resp.columns, resp.rows))
    parts += [f"warning: {w}" for w in resp.warnings]
    if trace:
        t = resp.trace
        if resp.sql:
            parts.append(f"sql: {resp.sql}")
        parts.append(f"trace: route={t.get('route')} resolver={t.get('resolver')} cache_hit={t.get('cache_hit')} "
                     f"llm_calls={t.get('llm_calls')} sql_attempts={len(t.get('sql_attempts', []))} "
                     f"llm_ms={t.get('llm_ms', 0):.0f} db_ms={t.get('db_ms', 0):.2f} total_ms={t.get('total_ms')}")
    return "\n".join(parts)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agent", description="Portfolio analytics agent (Gemini + SQLite)")
    p.add_argument("question", nargs="*")
    p.add_argument("--trace", action="store_true", help="show SQL, routing and timings")
    p.add_argument("--json", action="store_true", help="print JSON response")
    p.add_argument("--no-cache", action="store_true", help="bypass the decision cache")
    p.add_argument("--build-db", action="store_true", help="rebuild the SQLite database from CSVs")
    args = p.parse_args(argv)

    if args.build_db:
        print(f"Database built at {build_database(force=True)}")
        if not args.question:
            return 0
    agent = PortfolioAgent(use_cache=not args.no_cache)
    if agent.llm is None:
        print(f"note: {agent.llm_error}; running in offline mode (exposure questions only).", file=sys.stderr)

    def ask(q: str) -> AgentResponse:
        resp = agent.answer_question(q)
        print(json.dumps(response_to_dict(resp), indent=2, default=str) if args.json else render(resp, args.trace))
        return resp

    if args.question:
        resp = ask(" ".join(args.question))
        return 0 if resp.status in ("VERIFIED", "ANSWERED_WITH_WARNINGS") else 1
    print("Portfolio agent. Type a question, or 'exit'.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if q.lower() in ("exit", "quit"):
            return 0
        if q:
            ask(q)


if __name__ == "__main__":
    sys.exit(main())
