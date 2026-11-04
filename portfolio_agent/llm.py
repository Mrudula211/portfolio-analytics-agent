"""Model access. One request returns the complete plan, so most questions cost one call."""

from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Protocol

from google import genai
from google.genai import types

from .config import Settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not be reached or returned nothing usable."""


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class LLMResponse:
    calls: list[ToolCall]
    model: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def plan(self, system: str, prompt: str) -> LLMResponse: ...


TOOL_DECLARATIONS = [
    {
        "name": "run_sql",
        "description": "Run one read-only SQLite SELECT against the portfolio database.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT or WITH query."},
                "title": {"type": "string", "description": "Short label for the result, under 10 words."},
            },
            "required": ["sql", "title"],
        },
    },
    {
        "name": "exposure_calculator",
        "description": (
            "Compute sector exposures for portfolios from their equity holdings, excluding bonds. "
            "Use for any request for a portfolio's sector exposure, breakdown or allocation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "portfolio_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Portfolio names. Leave empty when use_previous_sql_result is true.",
                },
                "use_previous_sql_result": {
                    "type": "boolean",
                    "description": (
                        "True to compute exposures for every portfolio_name returned by the "
                        "run_sql call placed immediately before this one."
                    ),
                },
            },
            "required": ["portfolio_names", "use_previous_sql_result"],
        },
    },
    {
        "name": "decline",
        "description": "Do not answer: out of scope, not in the data, unsafe, or ambiguous.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["out_of_scope", "no_data", "unsafe", "ambiguous", "advice"]},
                "message": {"type": "string", "description": "One short sentence for the user."},
            },
            "required": ["kind", "message"],
        },
    },
]


class GeminiClient:
    """Calls Gemini with forced function calling, minimal thinking and hedged requests."""

    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set.")
        self._models = [settings.gemini_model, *settings.gemini_fallback_models]
        self._hedge_delay_s = settings.llm_hedge_delay_s
        self._deadline_s = settings.llm_timeout_s
        self._pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="gemini")
        # SDK retries are off: waiting to retry a congested model is slower than asking the next one.
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=int(settings.llm_timeout_s * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self._tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=item["name"],
                        description=item["description"],
                        parameters_json_schema=item["parameters"],
                    )
                    for item in TOOL_DECLARATIONS
                ]
            )
        ]

    def _call(self, model: str, system: str, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        response = self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                max_output_tokens=1024,
                tools=self._tools,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
                ),
                # Generating one query needs little deliberation, and this is the largest
                # controllable part of latency.
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            ),
        )
        calls = [ToolCall(c.name, dict(c.args or {})) for c in (response.function_calls or [])]
        if not calls:
            raise LLMError("Model returned no tool call.")
        usage = response.usage_metadata
        return LLMResponse(
            calls=calls,
            model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
            prompt_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
        )

    def plan(self, system: str, prompt: str) -> LLMResponse:
        """Hedged request: start the next model on failure or after a delay; first answer wins.

        Shared-tier latency is bimodal (about 1 s or over 10 s for identical requests), so
        waiting on one slow request dominates tail latency. A hedge costs an extra call only
        when the first is already late.
        """
        deadline = time.monotonic() + self._deadline_s
        waiting = list(self._models)
        running: dict[Future, str] = {}
        last_error: Exception | None = None
        hedge_due = False
        while waiting or running:
            if waiting and (not running or hedge_due):
                model = waiting.pop(0)
                running[self._pool.submit(self._call, model, system, prompt)] = model
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_error = last_error or TimeoutError("deadline")
                break
            timeout = min(self._hedge_delay_s, remaining) if waiting else remaining
            done, _ = wait(running, timeout=timeout, return_when=FIRST_COMPLETED)
            hedge_due = not done
            for future in done:
                model = running.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # The SDK raises many error types; each means use another model.
                    last_error = exc
                    log.warning("llm_call_failed model=%s error=%s", model, type(exc).__name__)
                    continue
                for other in running:
                    other.cancel()  # Only stops calls not yet started; others end at their timeout.
                return result
        for other in running:
            other.cancel()
        raise LLMError(f"All models failed: {type(last_error).__name__}") from last_error


@dataclass
class ScriptedLLM:
    """Replays prepared plans. Used by tests and the evaluator's self-test; never by users."""

    script: dict[str, list[ToolCall]] = field(default_factory=dict)
    repairs: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def plan(self, system: str, prompt: str) -> LLMResponse:
        self.prompts.append(prompt)
        if "<failed_sql>" in prompt and self.repairs:
            return LLMResponse([ToolCall("run_sql", {"sql": self.repairs.pop(0), "title": "Repaired"})], "scripted")
        for question, calls in self.script.items():
            if f"<question>{question}</question>" in prompt:
                return LLMResponse(list(calls), "scripted")
        raise LLMError("No scripted plan for this prompt.")
