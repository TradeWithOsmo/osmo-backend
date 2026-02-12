from __future__ import annotations

import time
from typing import Any, Dict, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_items: int = 256) -> None:
        self.ttl_seconds = int(ttl_seconds)
        self.max_items = int(max_items)
        self._store: Dict[str, tuple[float, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < self._now():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.max_items:
            # Drop oldest by expiry
            oldest_key = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(oldest_key, None)
        self._store[key] = (self._now() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()
