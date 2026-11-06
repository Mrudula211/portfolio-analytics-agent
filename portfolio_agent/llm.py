"""The only module that talks to Gemini.

The model is used for exactly two things: choosing a tool and writing SQL. It never receives
query results (privacy + no hallucinated numbers). Function calling is forced (mode=ANY) so
every reply is a structured tool call; automatic function calling is disabled so our code,
not the SDK, decides what executes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from . import config

TOOL_DECLARATIONS = [
    {
        "name": "query_database",
        "description": "Answer a factual question by running ONE read-only SQLite SELECT over the portfolio database. "
                       "Use for counts, lists, lookups, aggregations, rankings, performance and risk metrics.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SQLite SELECT statement."}},
            "required": ["sql"],
        },
    },
    {
        "name": "calculate_sector_exposure",
        "description": "Compute the sector exposure breakdown (percentage per sector, equities only, bonds excluded) "
                       "for ONE portfolio. Use whenever the user asks for sector exposure/allocation/breakdown of a portfolio.",
        "parameters": {
            "type": "object",
            "properties": {"portfolio_name": {"type": "string", "description": "Portfolio name or id as given by the user."}},
            "required": ["portfolio_name"],
        },
    },
    {
        "name": "cannot_answer",
        "description": "Use when the question cannot be answered from this database (data not present, e.g. ESG scores, "
                       "Jensen's alpha, future prices), is not about portfolios, asks to modify data, or is too ambiguous.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["unsupported", "clarification", "refused"]},
                "reason": {"type": "string"},
            },
            "required": ["kind", "reason"],
        },
    },
]


class LLMUnavailable(Exception):
    pass


@dataclass
class ToolCall:
    name: str
    args: dict
    latency_ms: float = 0.0
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    model: str

    def decide(self, system: str, prompt: str, allowed: list[str] | None = None) -> ToolCall: ...


class GeminiLLM:
    def __init__(self, model: str = config.GEMINI_MODEL, api_key: str | None = None, max_retries: int = 3):
        key = api_key or config.api_key()
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        from google import genai
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=key)
        self.model = model
        self.max_retries = max_retries
        self._tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=d["name"], description=d["description"], parameters_json_schema=d["parameters"])
            for d in TOOL_DECLARATIONS
        ])]

    def decide(self, system: str, prompt: str, allowed: list[str] | None = None) -> ToolCall:
        t = self._types
        cfg = t.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            tools=self._tools,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(
                mode="ANY", allowed_function_names=allowed or None)),
        )
        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                break
            except Exception as exc:  # SDK raises google.genai.errors.APIError subclasses
                code = getattr(exc, "code", None)
                if code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise LLMUnavailable(f"Gemini call failed ({code or type(exc).__name__}): {str(exc)[:200]}") from exc
        latency = (time.perf_counter() - start) * 1000
        calls = resp.function_calls or []
        meta = getattr(resp, "usage_metadata", None)
        usage = {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
        }
        if not calls:
            text = (resp.text or "").strip() if hasattr(resp, "text") else ""
            return ToolCall("cannot_answer", {"kind": "clarification", "reason": text or "model returned no tool call"}, latency, usage)
        return ToolCall(calls[0].name, dict(calls[0].args or {}), latency, usage)


class ScriptedLLM:
    """Deterministic stand-in for offline tests: maps question substrings to scripted tool calls.
    A list value yields successive responses (used to test the repair loop)."""

    def __init__(self, script: dict[str, ToolCall | list[ToolCall]], model: str = "scripted"):
        self.script = {k.lower(): (v if isinstance(v, list) else [v]) for k, v in script.items()}
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def decide(self, system: str, prompt: str, allowed: list[str] | None = None) -> ToolCall:
        self.calls.append((system, prompt))
        question = prompt.split("Question:", 1)[-1].split("\n", 1)[0].lower()
        for key, responses in self.script.items():
            if key in question:
                return responses.pop(0) if len(responses) > 1 else responses[0]
        raise LLMUnavailable("no scripted response")
