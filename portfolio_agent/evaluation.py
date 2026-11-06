"""Scoring. Compares what the agent returned with independently computed truth.

Queries are compared by their results, never by SQL text, because many different queries
are correct. Exposure answers are checked against a calculation made directly from the
CSV files, so a bug in the exposure tool cannot also hide in its own expected answer.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agent import AgentResponse, PortfolioAgent, Step
from .llm import ToolCall
from .sql_guard import execute_select

EXACT = "exact"  # Same columns and rows.
EQUIVALENT = "equivalent"  # All expected data present, plus extra columns or empty rows.
PARTIAL = "partial"  # Rows right but some requested columns missing.
FAIL = "fail"
INFRA_ERROR = "infra_error"  # The model could not be reached; says nothing about accuracy.

_PASSING = {EXACT, EQUIVALENT}
_EXPOSURE_TOLERANCE = 0.01  # Percentage points.


def _decimals(value: float) -> int:
    text = repr(float(value))
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


def values_match(a, b) -> bool:
    """Equal, or equal once the more precise number is rounded to the other's precision.

    The reference answer may say 84.67 where an equally correct query returns 84.6666.
    """
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        a, b = float(a), float(b)
        if abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b)):
            return True
        places = max(2, min(_decimals(a), _decimals(b)))
        return abs(a - b) <= 0.5 * 10**-places + 1e-9
    return str(a).strip().casefold() == str(b).strip().casefold()


def _unmatched(expected: list, actual: list) -> tuple[list, list]:
    """Multiset match with tolerance. Returns (missing from actual, left over in actual)."""
    remaining = list(actual)
    missing = []
    for item in expected:
        for index, candidate in enumerate(remaining):
            same = (
                all(values_match(x, y) for x, y in zip(item, candidate, strict=False))
                if isinstance(item, list)
                else values_match(item, candidate)
            )
            if same:
                del remaining[index]
                break
        else:
            missing.append(item)
    return missing, remaining


def _find_mapping(want: list[list], have: list[list], ordered: bool) -> tuple[list[int], list[list]] | None:
    """Assign a distinct `have` column to each `want` column so that rows line up.

    Backtracks over columns whose values fit, then checks whole rows, because matching
    columns independently would accept values paired with the wrong row.
    """
    if not want or not want[0]:
        return None
    want_columns = list(zip(*want, strict=False))
    have_columns = list(zip(*have, strict=False)) if have else []
    options = [
        [j for j, column in enumerate(have_columns) if not _unmatched(list(target), list(column))[0]]
        for target in want_columns
    ]
    chosen: list[int] = []

    def search(position: int) -> list[list] | None:
        if position == len(options):
            projected = [[row[j] for j in chosen] for row in have]
            missing, extra = _unmatched(want, projected)
            if missing:
                return None
            if ordered and not all(
                all(values_match(x, y) for x, y in zip(w, p, strict=False))
                for w, p in zip(want, projected, strict=False)
            ):
                return None
            return extra
        for j in options[position]:
            if j not in chosen:
                chosen.append(j)
                outcome = search(position + 1)
                if outcome is not None:
                    return outcome
                chosen.pop()
        return None

    extra = search(0)
    return (list(chosen), extra) if extra is not None else None


def _is_empty_row(row: list) -> bool:
    """A row saying 'nothing here' (zero or NULL metric), e.g. a fund with no tech holdings."""
    numbers = [v for v in row if isinstance(v, (int, float)) or v is None]
    return any(v is None or v == 0 for v in numbers)


def compare_results(
    expected_columns: list[str],
    expected_rows: list[list],
    actual_columns: list[str],
    actual_rows: list[list],
    *,
    ordered: bool = False,
) -> tuple[str, str]:
    """Grade a result set. Row order counts only when the reference uses LIMIT (top-N)."""
    if not expected_rows:
        return (EXACT, "both empty") if not actual_rows else (FAIL, "expected no rows")
    if not actual_rows:
        return FAIL, "agent returned no rows"
    mapping = _find_mapping(expected_rows, actual_rows, ordered)
    if mapping is not None:
        chosen, extra = mapping
        if extra and not all(_is_empty_row([row[j] for j in chosen]) for row in extra):
            return FAIL, f"{len(extra)} unexpected rows"
        if not extra and len(actual_columns) == len(expected_columns):
            return EXACT, ""
        notes = []
        if len(actual_columns) > len(expected_columns):
            notes.append(f"{len(actual_columns) - len(expected_columns)} extra columns")
        if extra:
            notes.append(f"{len(extra)} extra zero rows")
        return EQUIVALENT, ", ".join(notes)
    # Fewer columns than requested. Ignore rows that only report zero, as above.
    meaningful = [row for row in actual_rows if not _is_empty_row(row)]
    if len(meaningful) == len(expected_rows):
        reverse = _find_mapping(meaningful, expected_rows, ordered)
        if reverse is not None:
            present = {expected_columns[j] for j in reverse[0]}
            absent = [c for c in expected_columns if c not in present]
            return PARTIAL, "missing columns: " + ", ".join(absent)
    return FAIL, "rows differ from reference"


class ExposureOracle:
    """Sector exposures calculated straight from the CSVs, sharing no code with the tool."""

    def __init__(self, data_dir: Path):
        def read(name: str) -> list[dict]:
            with (data_dir / f"{name}.csv").open(encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        self._portfolios = {r["portfolio_name"]: r["portfolio_id"] for r in read("portfolios")}
        self._sectors = {r["sector_id"]: r["sector_name"] for r in read("sectors")}
        self._securities = {r["security_id"]: r for r in read("securities")}
        self._holdings = read("holdings")

    def exposures(self, portfolio_name: str) -> dict[str, float]:
        portfolio_id = self._portfolios[portfolio_name]
        weights: dict[str, float] = defaultdict(float)
        for holding in self._holdings:
            security = self._securities[holding["security_id"]]
            if holding["portfolio_id"] == portfolio_id and security["asset_type"] == "Stock":
                weights[self._sectors[security["sector_id"]]] += float(holding["current_weight"])
        total = sum(weights.values())
        return {sector: weight / total * 100 for sector, weight in weights.items()} if total else {}


@dataclass
class Case:
    id: str
    category: str
    difficulty: str
    question: str
    kind: str  # sql | exposure | hybrid | refuse
    sql: str | None = None
    portfolios: list[str] = field(default_factory=list)
    attack_sql: str | None = None


def load_ground_truth(path: Path) -> list[Case]:
    cases = []
    for item in json.loads(path.read_text(encoding="utf-8"))["questions"]:
        truth = item["ground_truth"]
        if item["type"] == "text2sql":
            cases.append(
                Case(
                    f"gt{item['id']:02d}",
                    "ground_truth",
                    item["difficulty"],
                    item["question"],
                    "sql",
                    truth["sql_query"],
                )
            )
        else:
            cases.append(
                Case(
                    f"gt{item['id']:02d}",
                    "ground_truth",
                    item["difficulty"],
                    item["question"],
                    "exposure",
                    portfolios=[truth["parameters"]["portfolio_name"]],
                )
            )
    return cases


def load_extended(path: Path) -> list[Case]:
    cases = []
    for item in json.loads(path.read_text(encoding="utf-8"))["questions"]:
        expect = item["expect"]
        cases.append(
            Case(
                item["id"],
                item["category"],
                item.get("difficulty", "-"),
                item["question"],
                expect["kind"],
                expect.get("sql"),
                expect.get("portfolios", []),
                item.get("attack_sql"),
            )
        )
    return cases


@dataclass
class CaseResult:
    id: str
    category: str
    difficulty: str
    question: str
    verdict: str
    detail: str
    tool_correct: bool
    route: str
    status: str
    latency_ms: float
    llm_ms: float
    llm_calls: int
    model: str = ""
    sql: str | None = None
    vm_steps: int = 0
    reference_vm_steps: int = 0
    efficiency: float | None = None  # Reference work / agent work, capped at 1.
    full_scans: int = 0


def _sql_steps(reply: AgentResponse) -> list[Step]:
    return [s for s in reply.steps if s.tool == "run_sql" and s.error is None]


def _exposure_steps(reply: AgentResponse) -> list[Step]:
    return [s for s in reply.steps if s.tool == "exposure_calculator" and s.exposure is not None]


def _check_exposures(case: Case, reply: AgentResponse, oracle: ExposureOracle) -> tuple[str, str]:
    steps = _exposure_steps(reply)
    got = {s.exposure["portfolio_name"]: s.exposure for s in steps}
    if set(got) != set(case.portfolios):
        return FAIL, f"portfolios {sorted(got)} != {sorted(case.portfolios)}"
    for name in case.portfolios:
        truth = oracle.exposures(name)
        actual = {e["sector"]: e["exposure_pct"] for e in got[name]["exposures"]}
        if set(actual) != set(truth):
            return FAIL, f"{name}: sectors {sorted(actual)} != {sorted(truth)}"
        for sector, percent in truth.items():
            if abs(actual[sector] - percent) > _EXPOSURE_TOLERANCE:
                return FAIL, f"{name} {sector}: {actual[sector]} != {percent:.4f}"
    return EXACT, ""


class Evaluator:
    def __init__(self, agent: PortfolioAgent, data_dir: Path):
        self.agent = agent
        self.db = agent.settings.db_path
        self.oracle = ExposureOracle(data_dir)

    def _grade(self, case: Case, reply: AgentResponse) -> tuple[str, str, bool]:
        """Returns (verdict, detail, whether the right tool or tools were used)."""
        if reply.status == "error" and "unavailable" in reply.answer:
            return INFRA_ERROR, "model unreachable", False
        used = {s.tool for s in reply.steps if s.error is None}
        if case.kind == "refuse":
            ok = reply.status in {"declined", "clarify", "blocked"}
            return (EXACT, reply.status, True) if ok else (FAIL, f"answered with status {reply.status}", False)
        if reply.status != "ok":
            return FAIL, f"status {reply.status}: {reply.answer[:100]}", False
        if case.kind == "exposure":
            verdict, detail = _check_exposures(case, reply, self.oracle)
            return verdict, detail, used == {"exposure_calculator"}
        if case.kind == "hybrid":
            verdict, detail = _check_exposures(case, reply, self.oracle)
            return verdict, detail, used == {"run_sql", "exposure_calculator"}
        steps = _sql_steps(reply)
        if not steps or used != {"run_sql"}:
            return FAIL, f"expected run_sql, used {sorted(used)}", False
        reference = execute_select(self.db, case.sql)
        ordered = bool(re.search(r"\bLIMIT\b", case.sql, re.I))
        verdict, detail = compare_results(
            reference.columns, reference.rows, steps[-1].columns or [], steps[-1].rows or [], ordered=ordered
        )
        return verdict, detail, True

    def run_case(self, case: Case) -> CaseResult:
        reply = self.agent.answer_question(case.question, use_cache=False)
        verdict, detail, tool_correct = self._grade(case, reply)
        steps = _sql_steps(reply)
        sql = steps[-1].input["sql"] if steps else None
        result = CaseResult(
            case.id,
            case.category,
            case.difficulty,
            case.question,
            verdict,
            detail,
            tool_correct,
            reply.route,
            reply.status,
            reply.timings_ms.get("total", 0.0),
            reply.timings_ms.get("llm", 0.0),
            reply.llm.get("calls", 0),
            reply.llm.get("model", "") or "",
            sql,
        )
        if steps and case.sql:
            result.vm_steps = steps[-1].vm_steps
            result.full_scans = len(steps[-1].full_scans)
            result.reference_vm_steps = execute_select(self.db, case.sql).vm_steps
            if verdict in _PASSING and result.vm_steps:
                result.efficiency = round(min(1.0, result.reference_vm_steps / result.vm_steps), 3)
        return result

    def run(
        self,
        cases: list[Case],
        *,
        runs: int = 1,
        delay_s: float = 0.0,
        on_result: Callable[[CaseResult], None] | None = None,
    ) -> list[CaseResult]:
        results = []
        for _ in range(runs):
            for case in cases:
                result = self.run_case(case)
                results.append(result)
                if on_result:
                    on_result(result)
                if delay_s and result.llm_calls:
                    time.sleep(delay_s)
        return results


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[int(fraction * 100) - 1]


def summarize(results: list[CaseResult]) -> dict:
    scored = [r for r in results if r.verdict != INFRA_ERROR]
    total = len(scored) or 1
    passing = sum(r.verdict in _PASSING for r in scored)
    partial = sum(r.verdict == PARTIAL for r in scored)
    efficiencies = [r.efficiency for r in scored if r.efficiency is not None]
    by_category: dict[str, dict] = {}
    for category in sorted({r.category for r in scored}):
        group = [r for r in scored if r.category == category]
        by_category[category] = {
            "passed": sum(r.verdict in _PASSING for r in group),
            "partial": sum(r.verdict == PARTIAL for r in group),
            "total": len(group),
        }
    by_route: dict[str, dict] = {}
    for route in sorted({r.route for r in results}):
        latencies = [r.latency_ms for r in results if r.route == route and r.verdict != INFRA_ERROR]
        if latencies:
            by_route[route] = {
                "count": len(latencies),
                "p50_ms": round(_percentile(latencies, 0.50), 2),
                "p95_ms": round(_percentile(latencies, 0.95), 2),
            }
    return {
        "cases_scored": len(scored),
        "infra_errors": len(results) - len(scored),
        "strict_accuracy": round(passing / total, 4),
        "lenient_accuracy": round((passing + partial) / total, 4),
        "tool_selection_accuracy": round(sum(r.tool_correct for r in scored) / total, 4),
        "verdicts": dict(Counter(r.verdict for r in results)),
        "performance_adjusted_sql_score": round(statistics.mean(efficiencies), 4) if efficiencies else None,
        "llm_calls_per_question": round(sum(r.llm_calls for r in results) / (len(results) or 1), 3),
        "models_used": dict(Counter(r.model for r in results if r.model)),
        "by_category": by_category,
        "by_route": by_route,
    }


def oracle_script(cases: list[Case]) -> dict[str, list[ToolCall]]:
    """Plans a perfect model would produce, to test everything except the model."""
    script: dict[str, list[ToolCall]] = {}
    for case in cases:
        if case.kind == "sql":
            calls = [ToolCall("run_sql", {"sql": case.sql, "title": ""})]
        elif case.kind == "exposure":
            calls = [
                ToolCall("exposure_calculator", {"portfolio_names": case.portfolios, "use_previous_sql_result": False})
            ]
        elif case.kind == "hybrid":
            calls = [
                ToolCall("run_sql", {"sql": case.sql, "title": ""}),
                ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True}),
            ]
        elif case.attack_sql:
            calls = [ToolCall("run_sql", {"sql": case.attack_sql, "title": ""})]
        else:
            calls = [ToolCall("decline", {"kind": "no_data", "message": "Not available."})]
        script[case.question.replace("<", " ").replace(">", " ").strip()] = calls
    return script


def load_finished(report: Path) -> list[CaseResult]:
    """Results already scored in an earlier report; outages and quota failures are run again."""
    if not report.exists():
        return []
    rows = json.loads(report.read_text(encoding="utf-8"))["results"]
    return [CaseResult(**row) for row in rows if row["verdict"] != INFRA_ERROR]


def write_report(results: list[CaseResult], summary: dict, meta: dict, directory: Path, stem: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "summary": summary, "results": [asdict(r) for r in results]}
    (directory / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# Evaluation report: {stem}", ""]
    lines += [f"- **{key}**: {value}" for key, value in meta.items()]
    lines += [
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases scored | {summary['cases_scored']} |",
        f"| Model/infrastructure errors (not scored) | {summary['infra_errors']} |",
        f"| Strict accuracy | {summary['strict_accuracy']:.1%} |",
        f"| Lenient accuracy (includes partial) | {summary['lenient_accuracy']:.1%} |",
        f"| Tool selection accuracy | {summary['tool_selection_accuracy']:.1%} |",
        f"| Performance-adjusted SQL score | {summary['performance_adjusted_sql_score']} |",
        f"| Model calls per question (excluding hedges) | {summary['llm_calls_per_question']} |",
        f"| Answering models | {summary['models_used']} |",
        "",
        "| Route | Count | p50 ms | p95 ms |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {k} | {v['count']} | {v['p50_ms']} | {v['p95_ms']} |" for k, v in summary["by_route"].items()]
    lines += ["", "| Category | Passed | Partial | Total |", "| --- | --- | --- | --- |"]
    lines += [f"| {k} | {v['passed']} | {v['partial']} | {v['total']} |" for k, v in summary["by_category"].items()]
    lines += ["", "| ID | Verdict | Route | ms | Question | Detail |", "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        question = r.question.replace("|", "/")
        detail = r.detail.replace("|", "/")
        lines.append(f"| {r.id} | {r.verdict} | {r.route} | {r.latency_ms:.1f} | {question} | {detail} |")
    path = directory / f"{stem}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
