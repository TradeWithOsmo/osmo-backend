from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Tuple


class RuntimeTraceStore:
    """In-memory runtime trace store for debugging/audit in the current backend process."""

    def __init__(self, per_session_limit: int = 50):
        self._store: Dict[Tuple[str, str], Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=per_session_limit)
        )

    def add(self, user_address: str, session_id: str, trace: Dict[str, Any]) -> None:
        key = (user_address.lower(), session_id)
        payload = dict(trace or {})
        payload["created_at"] = datetime.utcnow().isoformat()
        self._store[key].append(payload)

    def list(self, user_address: str, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        key = (user_address.lower(), session_id)
        values = list(self._store.get(key, []))
        if limit <= 0:
            return values
        return values[-limit:]


runtime_trace_store = RuntimeTraceStore()

