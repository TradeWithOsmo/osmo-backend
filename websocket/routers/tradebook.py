"""
routers/tradebook.py
====================
Unified WebSocket + REST endpoints for orderbook and recent trades.
"""

import asyncio
import json
import logging
import importlib
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)
router = APIRouter()

_TRADES_UNAVAILABLE_EXCHANGES = {"ostium"}
_ORDERBOOK_UNAVAILABLE_EXCHANGES = {"ostium", "avantis"}

_TRADEBOOK_MODULES = {
    "hyperliquid": "Hyperliquid.tradebook",
    "vest":        "Vest.tradebook",
    "aster":       "Aster.tradebook",
    "avantis":     "Avantis.tradebook",
    "ostium":      "Ostium.tradebook",
    "orderly":     "Orderly.tradebook",
    "paradex":     "Paradex.tradebook",
    "aevo":        "Aevo.tradebook",
    "dydx":        "dYdX.tradebook",
}

_module_cache: dict = {}


def _get_tradebook(exchange: str):
    exchange = exchange.lower()
    if exchange not in _TRADEBOOK_MODULES:
        return None
    if exchange not in _module_cache:
        try:
            mod = importlib.import_module(_TRADEBOOK_MODULES[exchange])
            _module_cache[exchange] = mod
        except Exception as e:
            logger.error(f"[Tradebook] Cannot import {exchange} tradebook: {e}")
            return None
    return _module_cache[exchange]


# ── REST endpoints ─────────────────────────────────────────────────────────────

@router.get("/availability")
async def get_exchange_availability(exchange: str = Query("hyperliquid")):
    ex = exchange.lower()
    return {
        "exchange": ex,
        "orderbook": ex not in _ORDERBOOK_UNAVAILABLE_EXCHANGES,
        "trades": ex not in _TRADES_UNAVAILABLE_EXCHANGES,
    }


@router.get("/{symbol}/orderbook")
async def rest_orderbook(
    symbol: str,
    exchange: str = Query("hyperliquid"),
    depth: int = Query(20),
):
    mod = _get_tradebook(exchange)
    if not mod:
        return {"error": f"Unknown exchange: {exchange}", "bids": [], "asks": []}
    try:
        book = await mod.get_orderbook(symbol.upper(), depth=depth)
        if book is None:
            return {"exchange": exchange, "symbol": symbol, "available": False, "bids": [], "asks": []}
        return {"exchange": exchange, "symbol": symbol, "available": True, **book}
    except Exception as e:
        logger.error(f"[Tradebook] REST orderbook error {exchange}/{symbol}: {e}")
        return {"error": str(e), "bids": [], "asks": []}


@router.get("/{symbol}/trades")
async def rest_trades(
    symbol: str,
    exchange: str = Query("hyperliquid"),
    limit: int = Query(30),
):
    mod = _get_tradebook(exchange)
    if not mod:
        return {"error": f"Unknown exchange: {exchange}", "trades": []}
    try:
        trades = await mod.get_recent_trades(symbol.upper(), limit=limit)
        return {"exchange": exchange, "symbol": symbol, "trades": trades or []}
    except Exception as e:
        logger.error(f"[Tradebook] REST trades error {exchange}/{symbol}: {e}")
        return {"error": str(e), "trades": []}


# ── WebSocket: Orderbook ────────────────────────────────────────────────────────

@router.websocket("/ws/orderbook/{symbol}")
async def ws_orderbook(
    websocket: WebSocket,
    symbol: str,
    exchange: str = Query("hyperliquid"),
    interval: float = Query(1.5),
):
    await websocket.accept()
    exchange = exchange.lower()
    symbol = symbol.upper()
    mod = _get_tradebook(exchange)

    if not mod:
        await websocket.send_text(json.dumps({"type": "error", "message": f"Unknown exchange: {exchange}"}))
        await websocket.close()
        return

    logger.info(f"[Tradebook WS] Orderbook connected: {exchange}/{symbol}")

    try:
        if exchange in _ORDERBOOK_UNAVAILABLE_EXCHANGES:
            await websocket.send_text(json.dumps({
                "type": "orderbook_unavailable", "exchange": exchange, "symbol": symbol,
            }))
        else:
            await websocket.send_text(json.dumps({
                "type": "orderbook", "exchange": exchange, "symbol": symbol,
                "data": {"bids": [], "asks": []},
            }))
    except Exception:
        await websocket.close()
        return

    async def _poll():
        await asyncio.sleep(0.1)  # jitter
        consecutive_failures = 0
        while True:
            try:
                if exchange in _ORDERBOOK_UNAVAILABLE_EXCHANGES:
                    await asyncio.sleep(interval)
                    continue

                book = await mod.get_orderbook(symbol)
                consecutive_failures = 0

                payload = json.dumps(
                    {"type": "orderbook_unavailable", "exchange": exchange, "symbol": symbol}
                    if book is None else
                    {"type": "orderbook", "exchange": exchange, "symbol": symbol, "data": book}
                )
                await websocket.send_text(payload)

            except WebSocketDisconnect:
                break
            except Exception as e:
                consecutive_failures += 1
                logger.debug(f"[Tradebook WS] Orderbook poll error {exchange}/{symbol}: {e}")
                backoff = min(interval * (2 ** consecutive_failures), 30.0)
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(interval)

    poll_task = asyncio.create_task(_poll())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        poll_task.cancel()
        logger.info(f"[Tradebook WS] Orderbook disconnected: {exchange}/{symbol}")


# ── WebSocket: Trades ───────────────────────────────────────────────────────────

@router.websocket("/ws/trades/{symbol}")
async def ws_trades(
    websocket: WebSocket,
    symbol: str,
    exchange: str = Query("hyperliquid"),
    interval: float = Query(2.0),
):
    await websocket.accept()
    exchange = exchange.lower()
    symbol = symbol.upper()
    mod = _get_tradebook(exchange)

    if not mod:
        await websocket.send_text(json.dumps({"type": "error", "message": f"Unknown exchange: {exchange}"}))
        await websocket.close()
        return

    logger.info(f"[Tradebook WS] Trades connected: {exchange}/{symbol}")

    seen_ids: set = set()
    last_emit_ts = 0.0

    try:
        payload = {"type": "trades", "exchange": exchange, "symbol": symbol, "data": []}
        if exchange in _TRADES_UNAVAILABLE_EXCHANGES:
            payload["available"] = False
        await websocket.send_text(json.dumps(payload))
        last_emit_ts = time.time()
    except Exception:
        await websocket.close()
        return

    async def _poll():
        nonlocal seen_ids, last_emit_ts

        await asyncio.sleep(0.1)  # jitter
        consecutive_failures = 0
        while True:
            try:
                trades = await mod.get_recent_trades(symbol, limit=30)
                consecutive_failures = 0

                new_trades = []
                if trades:
                    for t in trades:
                        tid = t.get("id") or f"{t.get('px')}-{t.get('time')}"
                        if tid not in seen_ids:
                            seen_ids.add(tid)
                            new_trades.append(t)

                if len(seen_ids) > 300:
                    seen_ids = set(list(seen_ids)[-150:])

                now = time.time()
                if new_trades or (now - last_emit_ts) >= 10.0:
                    out = {
                        "type": "trades",
                        "exchange": exchange,
                        "symbol": symbol,
                        "data": new_trades,
                    }
                    if exchange in _TRADES_UNAVAILABLE_EXCHANGES:
                        out["available"] = False
                    await websocket.send_text(json.dumps(out))
                    last_emit_ts = now

            except WebSocketDisconnect:
                break
            except Exception as e:
                consecutive_failures += 1
                logger.debug(f"[Tradebook WS] Trades poll error {exchange}/{symbol}: {e}")
                backoff = min(interval * (2 ** consecutive_failures), 30.0)
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(interval)

    poll_task = asyncio.create_task(_poll())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        poll_task.cancel()
        logger.info(f"[Tradebook WS] Trades disconnected: {exchange}/{symbol}")