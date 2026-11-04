"""REST API and web UI. Run with: uvicorn portfolio_agent.api:app

Endpoints are plain `def`, so FastAPI runs each in its worker thread pool. The agent keeps no
per-request state and opens a read-only connection per query, so requests do not block each other.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import PortfolioAgent

STATIC = Path(__file__).parent / "static"
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors https://huggingface.co",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RateLimiter:
    """Per-client sliding window, protecting the API key's quota on a public demo."""

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:
                self._hits.clear()  # Bounded memory matters more than precision under a flood.
            hits = self._hits[client]
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def create_app(agent: PortfolioAgent | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app.state.agent = agent or PortfolioAgent()
        app.state.limiter = RateLimiter(app.state.agent.settings.rate_limit_per_minute)
        yield

    app = FastAPI(title="Portfolio Analytics Agent", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        if request.url.path == "/docs":  # Swagger UI needs its CDN assets and inline start-up script.
            del response.headers["Content-Security-Policy"]
        return response

    @app.post("/api/ask")
    def ask(body: AskRequest, request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        if not request.app.state.limiter.allow(client):
            raise HTTPException(429, "Too many questions. Please wait a minute.", {"Retry-After": "60"})
        return request.app.state.agent.answer_question(body.question).to_dict()

    @app.get("/api/health")
    def health(request: Request) -> dict:
        return {"status": "ok", "model_configured": request.app.state.agent.llm is not None}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
