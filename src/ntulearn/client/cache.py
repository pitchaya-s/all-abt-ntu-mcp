"""Bounded in-memory cache for validated NTULearn JSON responses."""

import time
from collections import OrderedDict
from copy import deepcopy
from typing import Any


class ResponseCache:
    def __init__(self, ttl_seconds: int, max_entries: int = 128):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple, tuple[float, Any, Any]] = OrderedDict()

    def get(self, key: tuple, *, refresh: bool = False):
        if refresh or not self.ttl_seconds:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        created, data, retrieved_at = entry
        age = time.monotonic() - created
        if age >= self.ttl_seconds:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return deepcopy(data), {
            "retrieved_at": retrieved_at,
            "from_cache": True,
            "cache_age_seconds": int(age),
        }

    def put(self, key: tuple, data: Any, retrieved_at: Any) -> None:
        if not self.ttl_seconds:
            return
        self._entries[key] = (time.monotonic(), deepcopy(data), retrieved_at)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
