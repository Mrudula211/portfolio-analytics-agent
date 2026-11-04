"""Thread-safe exact-match answer cache with LRU eviction.

Keys are normalised text, not embeddings, on purpose: "high risk AUM" and "low risk AUM"
are close in embedding space and have different answers. In finance a false cache hit is
worse than a slow correct answer.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any


def normalize_question(question: str) -> str:
    return " ".join(re.sub(r"[^\w\s.%-]", " ", question.lower()).split()).rstrip(".")


class AnswerCache:
    def __init__(self, max_size: int):
        self._max_size = max_size
        self._items: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            return self._items.get(key)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)
