"""Checks the request and response handling against the real SDK types, without a network call."""

import dataclasses
import threading
import time

import pytest
from google.genai import types

from portfolio_agent.llm import GeminiClient, LLMError


def _response(*function_calls):
    parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in function_calls]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20),
    )


@pytest.fixture
def client(settings):
    return GeminiClient(dataclasses.replace(settings, gemini_api_key="test-key"))


def test_requires_api_key(settings):
    with pytest.raises(LLMError):
        GeminiClient(settings)


def test_request_forces_tools_and_low_latency_settings(client, monkeypatch):
    captured = {}

    def fake(model, contents, config):
        captured.update(model=model, contents=contents, config=config)
        return _response(("run_sql", {"sql": "SELECT 1", "title": "One"}))

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    response = client.plan("system text", "user text")

    config = captured["config"]
    assert captured["model"] == "gemini-3.5-flash"
    assert config.system_instruction == "system text" and config.temperature == 0.0
    assert config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    declared = {d.name for d in config.tools[0].function_declarations}
    assert declared == {"run_sql", "exposure_calculator", "decline"}
    assert response.calls[0].name == "run_sql" and response.calls[0].args["sql"] == "SELECT 1"
    assert response.prompt_tokens == 100 and response.output_tokens == 20


def test_parallel_calls_keep_their_order(client, monkeypatch):
    plan = _response(
        ("run_sql", {"sql": "SELECT portfolio_name FROM portfolios", "title": "x"}),
        ("exposure_calculator", {"portfolio_names": [], "use_previous_sql_result": True}),
    )
    monkeypatch.setattr(client._client.models, "generate_content", lambda **_: plan)
    assert [c.name for c in client.plan("s", "u").calls] == ["run_sql", "exposure_calculator"]


def test_falls_back_to_second_model_on_failure(client, monkeypatch):
    models = []

    def fake(model, contents, config):
        models.append(model)
        if len(models) == 1:
            raise RuntimeError("overloaded")
        return _response(("decline", {"kind": "no_data", "message": "No."}))

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    assert client.plan("s", "u").model == "gemini-3.6-flash"
    assert models == ["gemini-3.5-flash", "gemini-3.6-flash"]


def test_all_models_failing_raises_without_exposing_details(client, monkeypatch):
    def fake(**_):
        raise RuntimeError("secret detail in provider error")

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    with pytest.raises(LLMError) as error:
        client.plan("s", "u")
    assert "secret detail" not in str(error.value)


def test_text_reply_without_tool_call_is_an_error(client, monkeypatch):
    text_only = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text="hello")]))]
    )
    monkeypatch.setattr(client._client.models, "generate_content", lambda **_: text_only)
    with pytest.raises(LLMError):
        client.plan("s", "u")


def test_thinking_setting_matches_each_model(client):
    assert client._thinking("gemini-2.5-flash-lite").thinking_budget == 0
    assert client._thinking("gemini-3.5-flash").thinking_level == types.ThinkingLevel.MINIMAL
    assert client._thinking("gemini-3.8-flash").thinking_level == types.ThinkingLevel.LOW


def test_slow_model_is_hedged_and_first_answer_wins(settings, monkeypatch):
    client = GeminiClient(dataclasses.replace(settings, gemini_api_key="k", llm_hedge_delay_s=0.05))
    release = threading.Event()

    def fake(model, contents, config):
        if model == "gemini-3.5-flash":
            release.wait(2)
        return _response(("decline", {"kind": "no_data", "message": model}))

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    started = time.perf_counter()
    response = client.plan("s", "u")
    release.set()
    assert response.model == "gemini-3.6-flash" and time.perf_counter() - started < 1


def test_fast_model_is_not_hedged(client, monkeypatch):
    models = []

    def fake(model, contents, config):
        models.append(model)
        return _response(("decline", {"kind": "no_data", "message": "x"}))

    monkeypatch.setattr(client._client.models, "generate_content", fake)
    client.plan("s", "u")
    assert models == ["gemini-3.5-flash"]


def test_overall_deadline_is_enforced(settings, monkeypatch):
    client = GeminiClient(dataclasses.replace(settings, gemini_api_key="k", llm_timeout_s=0.2, llm_hedge_delay_s=0.05))
    release = threading.Event()
    monkeypatch.setattr(client._client.models, "generate_content", lambda **_: release.wait(2))
    started = time.perf_counter()
    with pytest.raises(LLMError):
        client.plan("s", "u")
    release.set()
    assert time.perf_counter() - started < 1
