"""Per-client rate limiting, shared by the REST API and the Streamlit app."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding window per client, protecting the API key's quota on a public demo."""

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


def proxy_client(forwarded_for: str | None, fallback: str | None) -> str:
    """The address the hosting proxy saw. The proxy appends it last to X-Forwarded-For, so the
    rightmost entry cannot be forged; anything to its left came from the client."""
    rightmost = (forwarded_for or "").split(",")[-1].strip()
    return rightmost or fallback or "unknown"
