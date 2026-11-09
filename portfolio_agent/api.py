"""REST API. Run with: uvicorn portfolio_agent.api:app  (the web UI is streamlit_app.py)

Endpoints are plain `def`, so FastAPI runs each in its worker thread pool. The agent keeps no
per-request state and opens a read-only connection per query, so requests do not block each other.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .agent import PortfolioAgent
from .ratelimit import RateLimiter, proxy_client

__all__ = ["RateLimiter", "app", "create_app"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def create_app(agent: PortfolioAgent | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app.state.agent = agent or PortfolioAgent()
        app.state.limiter = RateLimiter(app.state.agent.settings.rate_limit_per_minute)
        yield

    app = FastAPI(title="Portfolio Analytics Agent", lifespan=lifespan)

    @app.post("/api/ask")
    def ask(body: AskRequest, request: Request) -> dict:
        client = proxy_client(request.headers.get("x-forwarded-for"), request.client.host if request.client else None)
        if not request.app.state.limiter.allow(client):
            raise HTTPException(429, "Too many questions. Please wait a minute.", {"Retry-After": "60"})
        return request.app.state.agent.answer_question(body.question).to_dict()

    @app.get("/api/health")
    def health(request: Request) -> dict:
        agent = request.app.state.agent
        return {"status": "ok", "model_configured": agent.llm is not None, "gemini": agent.gemini_status}

    return app


app = create_app()
