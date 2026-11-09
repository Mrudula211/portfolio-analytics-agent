from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import sql_call
from fastapi.testclient import TestClient

from portfolio_agent.api import RateLimiter, create_app


@pytest.fixture
def client(make_agent):
    agent = make_agent({"How many portfolios exist?": [sql_call("SELECT COUNT(*) FROM portfolios")]})
    with TestClient(create_app(agent)) as test_client:
        yield test_client


def test_ask_returns_answer_and_trace(client):
    body = client.post("/api/ask", json={"question": "How many portfolios exist?"}).json()
    assert body["status"] == "ok" and body["route"] == "gemini" and "13" in body["answer"]
    assert body["steps"][0]["input"]["sql"].startswith("SELECT")
    assert body["timings_ms"]["total"] > 0


def test_repeat_question_is_served_from_cache(client):
    client.post("/api/ask", json={"question": "How many portfolios exist?"})
    assert client.post("/api/ask", json={"question": "how many portfolios exist"}).json()["route"] == "cache"


def test_empty_and_oversized_questions_rejected(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 3000}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 600}).json()["status"] == "invalid"


def test_rate_limit_returns_429(client):
    client.app.state.limiter = RateLimiter(limit=2)
    payload = {"question": "How many portfolios exist?"}
    codes = [client.post("/api/ask", json=payload).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_rate_limiter_window_recovers():
    limiter = RateLimiter(limit=1, window_s=0.0)
    assert limiter.allow("a") and limiter.allow("a")


def test_rate_limit_is_per_client():
    limiter = RateLimiter(limit=1)
    assert limiter.allow("a") and limiter.allow("b") and not limiter.allow("a")


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["model_configured"] is True
    assert body["gemini"]["state"] == "configured"  # A client exists; no request has proved it works.


def test_concurrent_requests_succeed(client):
    client.app.state.limiter = RateLimiter(limit=1000)

    def call(index):
        payload = {"question": "sector exposure of Balanced Portfolio" if index % 2 else "How many portfolios exist?"}
        return client.post("/api/ask", json=payload).json()["status"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert set(pool.map(call, range(100))) == {"ok"}


def test_stored_plan_answers_without_a_model_call(make_agent):
    from portfolio_agent.llm import ToolCall

    agent = make_agent()
    question = "Total AUM of the high risk funds"
    agent.preload(
        question,
        [ToolCall("run_sql", {"sql": "SELECT SUM(total_aum) FROM portfolios WHERE target_risk_level = 'High'"})],
    )
    reply = agent.answer_question(question)
    assert reply.route == "cache" and "85,000,000" in reply.answer and agent.llm.prompts == []


def test_demo_password_protects_everything_but_health(settings, make_agent):
    import base64
    import dataclasses

    agent = make_agent()
    agent.settings = dataclasses.replace(settings, demo_password="s3cret")
    with TestClient(create_app(agent)) as protected:
        payload = {"question": "sector exposure of Balanced Portfolio"}
        assert protected.post("/api/ask", json=payload).status_code == 401
        assert protected.get("/api/health").status_code == 200
        wrong = {"Authorization": "Basic " + base64.b64encode(b"x:nope").decode()}
        right = {"Authorization": "Basic " + base64.b64encode(b"reviewer:s3cret").decode()}
        assert protected.post("/api/ask", json=payload, headers=wrong).status_code == 401
        assert protected.post("/api/ask", json=payload, headers=right).status_code == 200


def test_rate_limit_ignores_forged_forwarded_addresses(client):
    client.app.state.limiter = RateLimiter(limit=2)
    payload = {"question": "How many portfolios exist?"}
    codes = []
    for i in range(3):
        headers = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"}  # Forged left entry, real right entry.
        codes.append(client.post("/api/ask", json=payload, headers=headers).status_code)
    assert codes == [200, 200, 429]
