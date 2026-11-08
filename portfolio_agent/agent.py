"""The agent: route a question through the cheapest path that can answer it correctly.

cache hit          exact repeat                      no model, no database
fast path          "sector exposure of <one fund>"   no model
model plan         everything else                   one call; a second only to repair SQL
"""

from __future__ import annotations

import copy
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .cache import AnswerCache, normalize_question
from .config import Settings
from .db import ensure_database
from .llm import GeminiClient, LLMClient, LLMError, LLMResponse, ToolCall
from .metadata import EntityLinker, Links, SchemaCatalog
from .prompts import build_repair_prompt, build_system_prompt, build_user_prompt
from .render import render_exposure, render_sql
from .semantics import validate_result
from .sql_guard import QueryResult, SQLBlocked, SQLExecutionError
from .tools import AmbiguousPortfolio, Tools

log = logging.getLogger(__name__)

_EXPOSURE_INTENT = re.compile(
    r"\b(?:sector\s+(?:exposures?|breakdown|allocations?|weights?|weightings?|mix|split)"
    r"|exposures?\s+(?:by|across|per)\s+sector)\b",
    re.I,
)
# Words that mean the question asks for more than one fund's plain breakdown.
_NOT_SIMPLE = re.compile(
    r"\b(?:how many|which|compare|versus|vs|highest|lowest|largest|smallest|biggest|top|most|least|"
    r"average|more than|less than|greater|all|each|every)\b",
    re.I,
)
_MAX_FANOUT = 20
_DISCOVERY_TERMS = re.compile(
    r"\b(?:highest|lowest|largest|smallest|biggest|top|max(?:imum)?|min(?:imum)?|all|each|every|passive|active)\b",
    re.I,
)

STATUS_OK = "ok"
STATUS_DECLINED = "declined"
STATUS_CLARIFY = "clarify"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"
STATUS_INVALID = "invalid"


@dataclass
class Step:
    """One tool execution, kept for the UI, the evaluator and debugging."""

    tool: str
    input: dict
    columns: list[str] | None = None
    rows: list[list] | None = None
    truncated: bool = False
    exposure: dict | None = None
    elapsed_ms: float = 0.0
    vm_steps: int = 0
    full_scans: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class AgentResponse:
    question: str
    status: str
    answer: str
    route: str
    request_id: str = ""
    steps: list[Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    llm: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class _StopPlan(Exception):
    """Ends plan execution with a final status and message."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class PortfolioAgent:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None):
        self.settings = settings or Settings.from_env()
        ensure_database(self.settings)
        self.catalog = SchemaCatalog(self.settings.db_path)
        self.linker = EntityLinker(self.catalog.portfolio_names, self.catalog.sector_names, self.catalog.securities)
        self.tools = Tools(self.settings, self.linker)
        self.cache = AnswerCache(self.settings.cache_size)
        self._system = build_system_prompt(self.catalog.render())
        self.llm = llm if llm is not None else self._default_llm()
        self._budget = {"day": None, "used": 0}
        self._budget_lock = threading.Lock()

    def _default_llm(self) -> LLMClient | None:
        try:
            return GeminiClient(self.settings)
        except LLMError:
            log.warning("llm_disabled reason=no_api_key")
            return None

    def preload(self, question: str, calls: list[ToolCall]) -> None:
        """Cache the answer to a demo question from a stored plan, so it costs no model call.

        The plan, not the answer, is stored: it runs against the current data at start-up.
        """
        if not calls:  # Fast-path questions need no plan; answering once caches them.
            self.answer_question(question)
            return
        reply = self._answer_with_calls(question, self.linker.link(question), LLMResponse(calls), route="model")
        if reply.status in {STATUS_OK, STATUS_DECLINED}:
            self.cache.put(normalize_question(question), reply)

    def answer_question(self, question: str, *, use_cache: bool = True) -> AgentResponse:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        question = (question or "").strip()
        if not question or len(question) > self.settings.max_question_chars:
            message = f"Please ask a question of 1 to {self.settings.max_question_chars} characters."
            return AgentResponse(question, STATUS_INVALID, message, "validation", request_id)

        key = normalize_question(question)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                reply = copy.deepcopy(hit)
                reply.route = "cache"
                reply.request_id = request_id
                reply.timings_ms = {"total": round((time.perf_counter() - started) * 1000, 3)}
                return reply

        links = self.linker.link(question)
        if self._is_simple_exposure(question, links):
            reply = self._answer_with_calls(
                question,
                links,
                LLMResponse([ToolCall("exposure_calculator", {"portfolio_names": links.portfolios})]),
                route="fast_path",
            )
        else:
            reply = self._answer_with_model(question, links)

        reply.request_id = request_id
        reply.timings_ms["total"] = round((time.perf_counter() - started) * 1000, 3)
        if reply.status == STATUS_OK and use_cache:
            self.cache.put(key, copy.deepcopy(reply))
        log.info(
            "answered id=%s route=%s status=%s total_ms=%.1f llm_calls=%s",
            request_id,
            reply.route,
            reply.status,
            reply.timings_ms["total"],
            reply.llm.get("calls", 0),
        )
        return reply

    @staticmethod
    def _is_simple_exposure(question: str, links: Links) -> bool:
        return (
            len(links.portfolios) == 1
            and not links.sectors
            and bool(_EXPOSURE_INTENT.search(question))
            and not _NOT_SIMPLE.search(question)
        )

    def _take_model_budget(self) -> bool:
        """Count one question against the daily cap, shared by all users; resets at midnight UTC."""
        limit = self.settings.daily_model_questions
        if not limit:
            return True
        today = datetime.now(UTC).date()
        with self._budget_lock:
            if self._budget["day"] != today:
                self._budget = {"day": today, "used": 0}
            if self._budget["used"] >= limit:
                return False
            self._budget["used"] += 1
            return True

    def _answer_with_model(self, question: str, links: Links) -> AgentResponse:
        if self.llm is None:
            return AgentResponse(
                question,
                STATUS_ERROR,
                "This question needs the language model, and GEMINI_API_KEY is not set. "
                "Sector exposure questions for a named portfolio still work without it.",
                "model",
            )
        if not self._take_model_budget():
            return AgentResponse(
                question,
                STATUS_ERROR,
                "This demo has reached its daily limit for new questions. The example questions and sector "
                "exposure questions for a named fund still work.",
                "model",
            )
        started = time.perf_counter()
        try:
            plan = self.llm.plan(self._system, build_user_prompt(question, links))
        except LLMError as exc:
            log.warning("llm_failed reason=%s", exc)
            return AgentResponse(
                question,
                STATUS_ERROR,
                "The language model is unavailable right now. Please try again shortly.",
                "model",
                timings_ms={"llm": round((time.perf_counter() - started) * 1000, 3)},
                llm={"failure_category": exc.category},
            )
        plan.latency_ms = (time.perf_counter() - started) * 1000  # Includes retries and fallback.
        if self._requires_hybrid(question, links):
            plan = self._complete_hybrid_plan(plan)
        return self._answer_with_calls(question, links, plan, route="model")

    @staticmethod
    def _requires_hybrid(question: str, links: Links) -> bool:
        """An exposure request over a discovered set of portfolios needs SQL plus calculation."""
        return (
            bool(_EXPOSURE_INTENT.search(question))
            and not links.portfolios
            and not links.candidates
            and bool(_DISCOVERY_TERMS.search(question))
        )

    @staticmethod
    def _complete_hybrid_plan(plan: LLMResponse) -> LLMResponse:
        """Require the exposure operation to consume the SQL-selected portfolio rows."""
        if any(call.name == "decline" for call in plan.calls):
            return plan
        sql_positions = [i for i, call in enumerate(plan.calls) if call.name == "run_sql"]
        if not sql_positions:
            return plan
        last_sql = sql_positions[-1]
        calls = [call for call in plan.calls if call.name != "exposure_calculator"]
        # Removing an earlier calculator may shift the SQL index.
        last_sql = max(i for i, call in enumerate(calls) if call.name == "run_sql")
        calls.insert(
            last_sql + 1,
            ToolCall("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True}),
        )
        return LLMResponse(calls, plan.model, plan.latency_ms, plan.prompt_tokens, plan.output_tokens)

    def _answer_with_calls(self, question: str, links: Links, plan: LLMResponse, *, route: str) -> AgentResponse:
        reply = AgentResponse(question, STATUS_OK, "", route)
        llm_ms = plan.latency_ms
        usage = {"calls": 0 if route == "fast_path" else 1, "model": plan.model}
        usage.update(prompt_tokens=plan.prompt_tokens, output_tokens=plan.output_tokens)
        sections: list[str] = []
        previous: QueryResult | None = None
        tool_started = time.perf_counter()
        try:
            required_hybrid = self._requires_hybrid(question, links)
            for index, call in enumerate(plan.calls):
                if call.name == "run_sql":
                    needs_followup = (
                        required_hybrid
                        and index + 1 < len(plan.calls)
                        and plan.calls[index + 1].name == "exposure_calculator"
                        and bool(plan.calls[index + 1].args.get("use_previous_sql_result"))
                    )
                    previous, section, repair = self._run_sql_step(
                        question, links, call, reply, require_rows=needs_followup
                    )
                    sections.append(section)
                    if repair is not None:
                        llm_ms += repair.latency_ms
                        usage["calls"] += 1
                        usage["prompt_tokens"] += repair.prompt_tokens
                        usage["output_tokens"] += repair.output_tokens
                elif call.name == "exposure_calculator":
                    sections.extend(self._run_exposure_step(call, previous, reply, question, links))
                elif call.name == "decline":
                    kind = str(call.args.get("kind", ""))
                    status = STATUS_CLARIFY if kind == "ambiguous" else STATUS_DECLINED
                    message = str(call.args.get("message", "")) or "I can't answer that from this data."
                    raise _StopPlan(status, message)
                else:
                    raise _StopPlan(STATUS_ERROR, "The model requested an unknown tool.")
        except _StopPlan as stop:
            reply.status = stop.status
            sections = [stop.message]
        if reply.status == STATUS_OK and self._requires_hybrid(question, links):
            successful_tools = {step.tool for step in reply.steps if step.error is None}
            if not {"run_sql", "exposure_calculator"}.issubset(successful_tools):
                reply.status = STATUS_ERROR
                sections = ["I could not complete both portfolio selection and sector exposure calculation."]
        reply.answer = "\n\n".join(s for s in sections if s)
        reply.llm = usage
        tool_ms = (time.perf_counter() - tool_started) * 1000 - (llm_ms - plan.latency_ms)
        reply.timings_ms = {"llm": round(llm_ms, 3), "tools": round(max(tool_ms, 0.0), 3)}
        return reply

    def _run_sql_step(
        self, question: str, links: Links, call: ToolCall, reply: AgentResponse, *, require_rows: bool = False
    ) -> tuple[QueryResult, str, LLMResponse | None]:
        sql = str(call.args.get("sql", ""))
        title = str(call.args.get("title", ""))
        step = Step("run_sql", {"sql": sql, "title": title})
        reply.steps.append(step)
        repair: LLMResponse | None = None
        try:
            try:
                result = self.tools.run_sql(sql)
                issue = self._sql_result_issue(question, result, require_rows)
                if issue:
                    raise SQLExecutionError(issue)
            except SQLExecutionError as exc:  # Invalid but harmless: one repair attempt.
                if self.llm is None:  # No model to repair with, e.g. a stored plan without a key.
                    raise
                repair = self.llm.plan(self._system, build_repair_prompt(question, links, sql, str(exc)))
                declined = next((c for c in repair.calls if c.name == "decline"), None)
                if declined is not None:  # The data does not hold what was asked; better than a substitute.
                    step.error = str(exc)
                    message = str(declined.args.get("message", "")) or "That isn't in this data."
                    raise _StopPlan(STATUS_DECLINED, message) from exc
                sql = next(str(c.args.get("sql", "")) for c in repair.calls if c.name == "run_sql")
                step.input["sql"] = sql
                result = self.tools.run_sql(sql)
                issue = self._sql_result_issue(question, result, require_rows)
                if issue:
                    raise SQLExecutionError(issue) from exc
        except SQLBlocked as exc:
            step.error = str(exc)
            raise _StopPlan(STATUS_BLOCKED, f"That query was blocked: {exc}") from exc
        except (SQLExecutionError, LLMError, StopIteration) as exc:
            step.error = str(exc)
            raise _StopPlan(STATUS_ERROR, "I could not produce a valid query for that question.") from exc
        step.columns, step.rows, step.truncated = result.columns, result.rows, result.truncated
        step.elapsed_ms, step.vm_steps, step.full_scans = (
            round(result.elapsed_ms, 3),
            result.vm_steps,
            result.full_scans,
        )
        return result, render_sql(result, title, question), repair

    def _sql_result_issue(self, question: str, result: QueryResult, require_rows: bool) -> str | None:
        if require_rows and not result.rows:
            return (
                "This query returned no portfolio rows, but the request requires a follow-up exposure calculation. "
                "For latest performance or risk values, use each portfolio's latest available date rather than "
                "filtering every portfolio to one global maximum date."
            )
        return validate_result(question, result, self.settings.db_path)

    def _run_exposure_step(
        self, call: ToolCall, previous: QueryResult | None, reply: AgentResponse, question: str, links: Links
    ) -> list[str]:
        names = [str(n) for n in (call.args.get("portfolio_names") or [])]
        if call.args.get("use_previous_sql_result"):
            names = _portfolio_names_from(previous)
            if not names:
                if self._requires_hybrid(question, links):
                    raise _StopPlan(STATUS_ERROR, "The portfolio selection returned no names for exposure calculation.")
                raise _StopPlan(STATUS_OK, "No portfolios matched, so there are no exposures to calculate.")
        if not names:
            raise _StopPlan(STATUS_CLARIFY, "Which portfolio would you like the sector exposure for?")
        if len(names) > _MAX_FANOUT:
            raise _StopPlan(STATUS_CLARIFY, f"That matches {len(names)} portfolios. Please narrow it down.")
        sections = []
        for name in names:
            step = Step("exposure_calculator", {"portfolio_name": name})
            reply.steps.append(step)
            try:
                result = self.tools.exposure_calculator(name)
            except AmbiguousPortfolio as exc:
                step.error = "ambiguous portfolio"
                raise _StopPlan(STATUS_CLARIFY, _clarify_message(exc)) from exc
            step.exposure = result.to_dict()
            step.elapsed_ms = round(result.elapsed_ms, 3)
            step.vm_steps = result.vm_steps
            reply.warnings.extend(f"{result.portfolio_name}: {w}" for w in result.warnings)
            sections.append(render_exposure(result))
        return sections


def _portfolio_names_from(result: QueryResult | None) -> list[str]:
    if result is None or not result.rows:
        return []
    lowered = [c.lower() for c in result.columns]
    index = lowered.index("portfolio_name") if "portfolio_name" in lowered else 0
    return [str(row[index]) for row in result.rows if row[index] is not None]


def _clarify_message(exc: AmbiguousPortfolio) -> str:
    if exc.candidates:
        return f"'{exc.reference}' could mean: {', '.join(exc.candidates)}. Which one do you mean?"
    return f"I couldn't find a portfolio called '{exc.reference}'."
