"""
Runtime Trace Store

Small in-memory store used by websocket router for session runtime diagnostics.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Tuple


class runtime_trace_store:
    """Thread-safe per-session runtime trace buffer."""

    _lock = threading.Lock()
    _buffers: Dict[Tuple[str, str], Deque[Dict[str, Any]]] = defaultdict(
        lambda: deque(maxlen=256)
    )

    @classmethod
    def add(
        cls,
        *,
        user_address: str,
        session_id: str,
        trace: Dict[str, Any],
    ) -> None:
        user_key = str(user_address or "").strip().lower()
        session_key = str(session_id or "").strip()
        if not user_key or not session_key:
            return

        payload = dict(trace or {})
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        key = (user_key, session_key)

        with cls._lock:
            cls._buffers[key].append(payload)

    @classmethod
    def list(
        cls,
        *,
        user_address: str,
        session_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        user_key = str(user_address or "").strip().lower()
        session_key = str(session_id or "").strip()
        if not user_key or not session_key:
            return []

        try:
            cap = max(1, min(int(limit), 200))
        except Exception:
            cap = 20
        key = (user_key, session_key)

        with cls._lock:
            items = list(cls._buffers.get(key, deque()))

        return items[-cap:]

    # Compatibility surface for older callers
    @classmethod
    async def log_trace(
        cls,
        *,
        user_address: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        session_id: str | None = None,
    ) -> None:
        cls.add(
            user_address=user_address,
            session_id=str(session_id or "default"),
            trace={
                "model": model,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cost": float(cost or 0.0),
            },
        )

    @classmethod
    async def get_traces(
        cls,
        user_address: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        user_key = str(user_address or "").strip().lower()
        if not user_key:
            return []
        try:
            cap = max(1, min(int(limit), 200))
        except Exception:
            cap = 50

        with cls._lock:
            merged: List[Dict[str, Any]] = []
            for (active_user, _session_id), items in cls._buffers.items():
                if active_user != user_key:
                    continue
                merged.extend(list(items))

        merged.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        return merged[:cap]


__all__ = ["runtime_trace_store"]
