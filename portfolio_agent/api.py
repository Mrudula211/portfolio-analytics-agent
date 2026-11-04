"""REST API and web UI. Run with: uvicorn portfolio_agent.api:app

Endpoints are plain `def`, so FastAPI runs each in its worker thread pool. The agent keeps no
per-request state and opens a read-only connection per query, so requests do not block each other.
"""

from __future__ import annotations

import logging
import statistics
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
from .llm import GeminiClient

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors https://huggingface.co",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
EXAMPLES = [
    "What are the sector exposures for the Tech Innovation Fund?",
    "How many portfolios do we have in total?",
    "Show me the top 5 holdings by cost basis in the Growth Equity Fund",
    "For each portfolio, show the total value of Technology sector holdings and what percentage it represents of the total portfolio value",
    "Show the sector exposures of the largest portfolio by AUM",
    "Should I buy NVDA right now?",
]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RateLimiter:
    """Per-client sliding window, protecting the API key's quota on a public demo."""

    def __init__(self, limit: int, window_s: float = 60.0, max_clients: int = 10_000):
        self.limit = limit
        self.window_s = window_s
        self.max_clients = max_clients
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self.max_clients:
                self._hits.clear()  # Bounded memory matters more than precision under a flood.
            hits = self._hits[client]
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class Metrics:
    """Rolling latency by route, for a quick look at production behaviour."""

    def __init__(self, size: int = 2000):
        self._recent: deque[tuple[str, str, float]] = deque(maxlen=size)
        self._lock = threading.Lock()

    def record(self, route: str, status: str, latency_ms: float) -> None:
        with self._lock:
            self._recent.append((route, status, latency_ms))

    def snapshot(self) -> dict:
        with self._lock:
            items = list(self._recent)
        routes: dict[str, list[float]] = defaultdict(list)
        statuses: dict[str, int] = defaultdict(int)
        for route, status, latency in items:
            routes[route].append(latency)
            statuses[status] += 1
        return {
            "requests": len(items),
            "statuses": dict(statuses),
            "routes": {
                route: {
                    "count": len(values),
                    "p50_ms": round(statistics.median(values), 2),
                    "p95_ms": round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 2),
                }
                for route, values in routes.items()
            },
        }


def create_app(agent: PortfolioAgent | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app.state.agent = agent or PortfolioAgent()
        app.state.limiter = RateLimiter(app.state.agent.settings.rate_limit_per_minute)
        app.state.metrics = Metrics()
        if isinstance(app.state.agent.llm, GeminiClient):
            threading.Thread(target=app.state.agent.llm.warm_up, daemon=True).start()
        yield

    app = FastAPI(title="Portfolio Analytics Agent", version="1.0.0", lifespan=lifespan)

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
            raise HTTPException(status_code=429, detail="Too many questions. Please wait a minute.", headers={"Retry-After": "60"})
        reply = request.app.state.agent.answer_question(body.question)
        request.app.state.metrics.record(reply.route, reply.status, reply.timings_ms.get("total", 0.0))
        return reply.to_dict()

    @app.get("/api/health")
    def health(request: Request) -> dict:
        current = request.app.state.agent
        return {
            "status": "ok",
            "model_configured": current.llm is not None,
            "model": current.settings.gemini_model if current.llm is not None else None,
            "portfolios": len(current.catalog.portfolio_names),
        }

    @app.get("/api/examples")
    def examples() -> list[str]:
        return EXAMPLES

    @app.get("/api/metrics")
    def metrics(request: Request) -> dict:
        return request.app.state.metrics.snapshot()

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
