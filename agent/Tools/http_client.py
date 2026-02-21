from __future__ import annotations

import asyncio
from typing import Dict

import httpx


_CLIENTS: Dict[float, httpx.AsyncClient] = {}
_LOCK = asyncio.Lock()


async def get_http_client(timeout_sec: float = 10.0) -> httpx.AsyncClient:
    timeout_key = float(timeout_sec)
    existing = _CLIENTS.get(timeout_key)
    if existing is not None:
        return existing

    async with _LOCK:
        existing = _CLIENTS.get(timeout_key)
        if existing is not None:
            return existing
        client = httpx.AsyncClient(timeout=timeout_key)
        _CLIENTS[timeout_key] = client
        return client


async def close_http_clients() -> None:
    async with _LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            continue

