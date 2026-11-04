"""Thread-safe exact-match answer cache with LRU eviction and a TTL.

Keys are normalised text, not embeddings, on purpose: "high risk AUM" and "low risk AUM"
are close in embedding space and have different answers. In finance a false cache hit is
worse than a slow correct answer.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from typing import Any


def normalize_question(question: str) -> str:
    return " ".join(re.sub(r"[^\w\s.%-]", " ", question.lower()).split()).rstrip(".")


class AnswerCache:
    def __init__(self, max_size: int, ttl_s: float):
        self._max_size = max_size
        self._ttl_s = ttl_s
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored_at, value = item
            if time.monotonic() - stored_at > self._ttl_s:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)
