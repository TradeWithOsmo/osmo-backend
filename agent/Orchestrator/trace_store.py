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

    def _normalize_key(self, user_address: Any, session_id: Any) -> Tuple[str, str]:
        user = str(user_address or "").strip().lower() or "anonymous"
        session = str(session_id or "").strip() or "default"
        return user, session

    def add(self, user_address: str, session_id: str, trace: Dict[str, Any]) -> None:
        key = self._normalize_key(user_address, session_id)
        payload = dict(trace or {})
        payload["created_at"] = datetime.utcnow().isoformat()
        self._store[key].append(payload)

    def list(self, user_address: str, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        key = self._normalize_key(user_address, session_id)
        values = list(self._store.get(key, []))
        if limit <= 0:
            return values
        return values[-limit:]


runtime_trace_store = RuntimeTraceStore()
