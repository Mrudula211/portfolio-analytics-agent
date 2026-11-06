"""Agent Evaluator.

  python evaluate.py                      official 10 ground-truth questions
  python evaluate.py --suite all          official + supplementary (financial, robustness, security)
  python evaluate.py --no-cache           force fresh model calls (honest latency numbers)
  python evaluate.py --repeat 3           repeatability: run the official suite k times

Correctness is judged by EXECUTION, never by SQL text:
  text2sql  -> candidate and reference SQL are both executed; result sets compared with column
               mapping by values (names/order ignored, extra columns allowed), multiset rows,
               ordered comparison only for top-N (ORDER BY + LIMIT) references, numeric tolerance.
  exposure  -> tool choice, resolved portfolio and every sector value compared with an
               independent SQL oracle (written separately from the calculator).
Efficiency (optional enhancement): deterministic SQLite VM-step counts, candidate vs reference.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config
from .agent import PortfolioAgent

SUITES_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "suites"
ANSWERED = ("VERIFIED", "ANSWERED_WITH_WARNINGS")


# --------------------------------------------------------------------------- result comparison
def _norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 2) + 0.0
    if isinstance(v, str):
        s = v.strip()
        try:
            return round(float(s), 2) + 0.0
        except ValueError:
            return s
    return v


def compare_results(ref_cols, ref_rows, cand_cols, cand_rows, ordered: bool = False) -> tuple[str, str]:
    ref = [tuple(_norm(v) for v in r) for r in ref_rows]
    cand = [tuple(_norm(v) for v in r) for r in cand_rows]
    if len(ref) != len(cand):
        return "FAIL_ROW_COUNT", f"expected {len(ref)} rows, got {len(cand)}"
    if not ref:
        return "PASS", "both empty"
    n_ref, n_cand = len(ref[0]), len(cand[0])
    ref_col_ms = [Counter(r[j] for r in ref) for j in range(n_ref)]
    cand_col_ms = [Counter(r[k] for r in cand) for k in range(n_cand)]
    options = [[k for k in range(n_cand) if cand_col_ms[k] == ref_col_ms[j]] for j in range(n_ref)]
    missing = [ref_cols[j] for j, o in enumerate(options) if not o]
    if missing:
        return "FAIL_MISSING_COLUMN", f"no candidate column matches reference column(s): {missing}"

    target_multiset = Counter(ref)
    order_ok_seen = False

    def search(j, used, mapping):
        nonlocal order_ok_seen
        if j == n_ref:
            projected = [tuple(r[k] for k in mapping) for r in cand]
            if Counter(projected) != target_multiset:
                return False
            if ordered and projected != ref:
                order_ok_seen = True  # rows right, order wrong
                return False
            return True
        return any(search(j + 1, used | {k}, mapping + [k]) for k in options[j] if k not in used)

    if search(0, frozenset(), []):
        return ("PASS_WITH_EXTRA_COLUMNS" if n_cand > n_ref else "PASS"), "result sets match"
    if order_ok_seen:
        return "FAIL_ORDER", "correct rows in wrong order"
    return "FAIL_ROW_MISMATCH", "columns match individually but rows do not align"


def is_ordered_reference(sql: str) -> bool:
    s = sql.upper()
    return "ORDER BY" in s and "LIMIT" in s


# --------------------------------------------------------------------------- exposure oracle
ORACLE_SQL = """
SELECT sec.sector_name,
       100.0 * SUM(h.current_weight) /
       (SELECT SUM(h2.current_weight) FROM holdings h2
          JOIN securities s2 ON s2.security_id = h2.security_id
         WHERE h2.portfolio_id = h.portfolio_id AND s2.asset_type = 'Stock')
FROM holdings h
JOIN securities s ON s.security_id = h.security_id AND s.asset_type = 'Stock'
JOIN sectors sec ON sec.sector_id = s.sector_id
WHERE h.portfolio_id = (SELECT portfolio_id FROM portfolios WHERE portfolio_name = ?)
GROUP BY sec.sector_name
"""


def check_exposure(agent: PortfolioAgent, resp, portfolio_name: str) -> tuple[str, str]:
    if resp.tool != "exposure_calculator":
        return "FAIL_TOOL", f"expected exposure_calculator, got {resp.tool}"
    if resp.portfolio_name != portfolio_name:
        return "FAIL_PORTFOLIO", f"expected {portfolio_name}, got {resp.portfolio_name}"
    oracle = {s: v for s, v in agent.db.execute(ORACLE_SQL, (portfolio_name,)).rows}
    got = {r[0]: r[1] for r in resp.rows}
    if set(oracle) != set(got):
        return "FAIL_SECTORS", f"sector set differs: expected {sorted(oracle)}, got {sorted(got)}"
    worst = max((abs(oracle[s] - got[s]) for s in oracle), default=0.0)
    if worst > 0.01:
        return "FAIL_VALUES", f"max deviation {worst:.4f} pp"
    if oracle and abs(sum(got.values()) - 100) > 0.01:
        return "FAIL_RECONCILE", "exposures do not sum to 100%"
    return "PASS", f"{len(oracle)} sectors match oracle (max dev {worst:.4f} pp)"


# --------------------------------------------------------------------------- runners
def run_official(agent: PortfolioAgent) -> list[dict]:
    questions = json.loads(config.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))["questions"]
    out = []
    for q in questions:
        gt = q["ground_truth"]
        resp = agent.answer_question(q["question"])
        item = {"id": q["id"], "type": q["type"], "difficulty": q["difficulty"], "question": q["question"],
                "status": resp.status, "tool": resp.tool, "sql": resp.sql, "trace": _slim(resp.trace)}
        if q["type"] == "text2sql":
            ref = agent.db.execute(gt["sql_query"])
            item["ref_vm_steps"] = ref.vm_steps
            if resp.tool != "sql_query":
                item["label"], item["detail"] = "FAIL_TOOL", f"expected sql_query, got {resp.tool}: {resp.text}"
            elif resp.status not in ANSWERED:
                item["label"], item["detail"] = "FAIL_EXECUTION", resp.text
            else:
                item["label"], item["detail"] = compare_results(
                    ref.columns, ref.rows, resp.columns, resp.rows, is_ordered_reference(gt["sql_query"]))
                cand = agent.db.execute(resp.sql)
                item["cand_vm_steps"] = cand.vm_steps
                item["efficiency_ratio"] = round(cand.vm_steps / ref.vm_steps, 2) if ref.vm_steps else None
                item["plan_warnings"] = [p for p in agent.db.query_plan(resp.sql) if "TEMP B-TREE" in p or p.startswith("SCAN")]
        else:
            item["label"], item["detail"] = check_exposure(agent, resp, gt["parameters"]["portfolio_name"])
            item["result"] = [list(r) for r in resp.rows]
        item["passed"] = item["label"].startswith("PASS")
        out.append(item)
    return out


def run_supplementary(agent: PortfolioAgent) -> list[dict]:
    out = []
    for path in sorted(SUITES_DIR.glob("*.json")):
        suite = path.stem
        for case in json.loads(path.read_text(encoding="utf-8")):
            out.append({"suite": suite, **_run_case(agent, case)})
    return out


def _run_case(agent: PortfolioAgent, case: dict) -> dict:
    exp = case["expect"]
    base = {"id": case["id"], "description": case.get("description", "")}
    if "sql" in case:  # direct execution of untrusted SQL: simulates a compromised/malicious model output
        resp = agent.run_untrusted_sql(case["sql"])
    else:
        if case.get("needs_llm", True) and agent.llm is None and not agent.cache.get(
                agent.cache.key(agent.model, case["question"])):
            return {**base, "label": "SKIPPED_NO_LLM", "passed": None}
        resp = agent.answer_question(case["question"])
    problems = []
    if "status" in exp and resp.status not in exp["status"]:
        problems.append(f"status {resp.status} not in {exp['status']}")
    if "tool" in exp and resp.tool != exp["tool"]:
        problems.append(f"tool {resp.tool} != {exp['tool']}")
    if "portfolio_id" in exp and resp.portfolio_id != exp["portfolio_id"]:
        problems.append(f"portfolio {resp.portfolio_id} != {exp['portfolio_id']}")
    if "ref_sql" in exp and resp.status in ANSWERED:
        ref = agent.db.execute(exp["ref_sql"])
        label, detail = compare_results(ref.columns, ref.rows, resp.columns, resp.rows, is_ordered_reference(exp["ref_sql"]))
        if not label.startswith("PASS"):
            problems.append(f"{label}: {detail}")
    if "exposure" in exp:
        got = {r[0]: r[exp.get("exposure_col", 1)] for r in resp.rows}
        for sector, val in exp["exposure"].items():
            if abs(got.get(sector, -999) - val) > 0.01:
                problems.append(f"{sector}: expected {val}, got {got.get(sector)}")
        if set(got) != set(exp["exposure"]):
            problems.append(f"sector set {sorted(got)} != {sorted(exp['exposure'])}")
    if "text_contains" in exp and exp["text_contains"].lower() not in (resp.text + " ".join(resp.warnings)).lower():
        problems.append(f"text does not mention '{exp['text_contains']}'")
    return {**base, "status": resp.status, "tool": resp.tool, "label": "PASS" if not problems else "FAIL",
            "detail": "; ".join(problems) or resp.text[:120], "passed": not problems,
            "total_ms": resp.trace.get("total_ms")}


def _slim(trace: dict) -> dict:
    keys = ("route", "resolver", "cache_hit", "llm_calls", "llm_ms", "db_ms", "total_ms", "usage")
    t = {k: trace.get(k) for k in keys}
    t["sql_attempts"] = len(trace.get("sql_attempts", []))
    t["repairs"] = max(0, t["sql_attempts"] - 1)
    return t


def _pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(q * (len(values) - 1))))], 1)


def metrics(official: list[dict], supp: list[dict]) -> dict:
    sql_items = [i for i in official if i["type"] == "text2sql"]
    exp_items = [i for i in official if i["type"] != "text2sql"]
    expected_tool = {"text2sql": "sql_query"}
    totals = [i["trace"]["total_ms"] for i in official if i["trace"]["total_ms"] is not None]
    llm = [i["trace"]["llm_ms"] for i in official if i["trace"]["llm_calls"]]
    ratios = [i["efficiency_ratio"] for i in sql_items if i.get("efficiency_ratio")]
    m = {
        "official_pass_rate": f"{sum(i['passed'] for i in official)}/{len(official)}",
        "execution_accuracy_sql": f"{sum(i['passed'] for i in sql_items)}/{len(sql_items)}",
        "exposure_accuracy": f"{sum(i['passed'] for i in exp_items)}/{len(exp_items)}",
        "tool_selection_accuracy": f"{sum(i['tool'] == expected_tool.get(i['type'], 'exposure_calculator') for i in official)}/{len(official)}",
        "sql_repairs_used": sum(i["trace"]["repairs"] for i in official),
        "llm_calls": sum(i["trace"]["llm_calls"] or 0 for i in official),
        "cache_hits": sum(bool(i["trace"]["cache_hit"]) for i in official),
        "latency_total_ms_p50": _pct(totals, 0.5), "latency_total_ms_p95": _pct(totals, 0.95),
        "latency_llm_ms_p50": _pct(llm, 0.5),
        "efficiency_ratio_median": round(statistics.median(ratios), 2) if ratios else None,
    }
    if supp:
        by_suite = {}
        for c in supp:
            s = by_suite.setdefault(c["suite"], {"pass": 0, "fail": 0, "skipped": 0})
            s["pass" if c["passed"] else "skipped" if c["passed"] is None else "fail"] += 1
        m["supplementary"] = by_suite
    return m


def write_report(official, supp, m, meta) -> Path:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {"meta": meta, "metrics": m, "official": official, "supplementary": supp}
    (config.REPORT_DIR / f"eval_{stamp}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [f"# Evaluation report ({meta['timestamp']})", "",
             f"Model: `{meta['model']}` | prompt {meta['prompt_version']} | cache {'on' if meta['cache'] else 'off'}", "",
             "## Metrics", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in m.items() if k != "supplementary"]
    lines += ["", "## Official ground truth (10)", "", "| id | type | label | tool | repairs | VM steps cand/ref | ms | detail |",
              "|---|---|---|---|---|---|---|---|"]
    for i in official:
        steps = f"{i.get('cand_vm_steps', '-')}/{i.get('ref_vm_steps', '-')}" if i["type"] == "text2sql" else "-"
        lines.append(f"| {i['id']} | {i['type']} | {i['label']} | {i['tool']} | {i['trace']['repairs']} | {steps} | "
                     f"{i['trace']['total_ms']} | {str(i['detail']).replace('|', '/')[:90]} |")
    if supp:
        lines += ["", "## Supplementary suites", "", "| suite | id | label | status | detail |", "|---|---|---|---|---|"]
        lines += [f"| {c['suite']} | {c['id']} | {c['label']} | {c.get('status', '-')} | {str(c.get('detail', '')).replace('|', '/')[:90]} |" for c in supp]
    md = "\n".join(lines) + "\n"
    (config.REPORT_DIR / f"eval_{stamp}.md").write_text(md, encoding="utf-8")
    (config.REPORT_DIR / "latest.md").write_text(md, encoding="utf-8")
    return config.REPORT_DIR / f"eval_{stamp}.md"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="evaluate", description="Evaluate the portfolio agent")
    p.add_argument("--suite", choices=["official", "all"], default="official")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--no-report", action="store_true")
    args = p.parse_args(argv)

    agent = PortfolioAgent(use_cache=not args.no_cache)
    if agent.llm is None:
        print(f"WARNING: {agent.llm_error}. Text-to-SQL items can only pass from the decision cache.", file=sys.stderr)
    runs = []
    for k in range(args.repeat):
        official = run_official(agent)
        runs.append(sum(i["passed"] for i in official))
        print(f"\nRun {k + 1}/{args.repeat}")
        for i in official:
            print(f"  Q{i['id']:<2} {'PASS' if i['passed'] else 'FAIL'}  {i['label']:<24} {i['type']:<20} {str(i['detail'])[:70]}")
    supp = run_supplementary(agent) if args.suite == "all" else []
    if supp:
        print("\nSupplementary")
        for c in supp:
            print(f"  {c['suite']:<11} {c['id']:<8} {c['label']:<15} {str(c.get('detail', ''))[:70]}")
    m = metrics(official, supp)
    if args.repeat > 1:
        m["repeatability_passes_per_run"] = runs
    print("\nMetrics:\n" + "\n".join(f"  {k}: {v}" for k, v in m.items()))
    if not args.no_report:
        meta = {"timestamp": datetime.now().isoformat(timespec="seconds"), "model": agent.model,
                "prompt_version": config.PROMPT_VERSION, "cache": not args.no_cache}
        print(f"\nReport: {write_report(official, supp, m, meta)}")
    return 0 if all(i["passed"] for i in official) else 1


if __name__ == "__main__":
    sys.exit(main())
