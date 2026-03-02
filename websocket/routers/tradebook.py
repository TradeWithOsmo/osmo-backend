"""
routers/tradebook.py
====================
Unified WebSocket + REST endpoints for orderbook and recent trades.

WS endpoints:
  /ws/orderbook/{symbol}?exchange=vest
  /ws/trades/{symbol}?exchange=vest

REST endpoints (for debugging / REST polling clients):
  GET /api/tradebook/{symbol}/orderbook?exchange=vest
  GET /api/tradebook/{symbol}/trades?exchange=vest

Each exchange has its own tradebook.py module (isolated, easy to maintain):
  Hyperliquid/tradebook.py
  Vest/tradebook.py
  Aster/tradebook.py
  Avantis/tradebook.py   ← no orderbook (AMM), trades from subgraph
  Ostium/tradebook.py    ← no orderbook or trades (oracle-based)
  Orderly/tradebook.py
  Paradex/tradebook.py
  Aevo/tradebook.py
  dYdX/tradebook.py

Message format for WS orderbook:
  {"type": "orderbook", "exchange": "vest", "symbol": "BTC-USD",
   "data": {"bids": [{"px":"65000","sz":"0.5"},...], "asks": [...]}}

Message format for WS trades:
  {"type": "trades", "exchange": "vest", "symbol": "BTC-USD",
   "data": [{"px":"65000","sz":"0.01","side":"B","time":1709000000000},...]}
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

# Exchanges that do not expose public recent-trades endpoints.
_TRADES_UNAVAILABLE_EXCHANGES = {"ostium"}
_ORDERBOOK_UNAVAILABLE_EXCHANGES = {"ostium", "avantis"}

# ── Exchange → module map ──────────────────────────────────────────────────────
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
    """Lazy-import tradebook module for the given exchange."""
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

@router.get("/{symbol}/orderbook")
async def rest_orderbook(
    symbol: str,
    exchange: str = Query("hyperliquid", description="Exchange name"),
    depth: int = Query(20, description="Max levels per side"),
):
    """REST: Fetch current orderbook snapshot."""
    mod = _get_tradebook(exchange)
    if not mod:
        return {"error": f"Unknown exchange: {exchange}", "bids": [], "asks": []}
    try:
        book = await mod.get_orderbook(symbol.upper(), depth=depth)
        if book is None:
            return {"exchange": exchange, "symbol": symbol, "available": False, "bids": [], "asks": []}
        return {"exchange": exchange, "symbol": symbol, "available": True, **book}
    except Exception as e:
        logger.error(f"[Tradebook] REST orderbook error for {exchange}/{symbol}: {e}")
        return {"error": str(e), "bids": [], "asks": []}


@router.get("/{symbol}/trades")
async def rest_trades(
    symbol: str,
    exchange: str = Query("hyperliquid", description="Exchange name"),
    limit: int = Query(30, description="Number of recent trades"),
):
    """REST: Fetch recent trades."""
    mod = _get_tradebook(exchange)
    if not mod:
        return {"error": f"Unknown exchange: {exchange}", "trades": []}
    try:
        trades = await mod.get_recent_trades(symbol.upper(), limit=limit)
        return {"exchange": exchange, "symbol": symbol, "trades": trades or []}
    except Exception as e:
        logger.error(f"[Tradebook] REST trades error for {exchange}/{symbol}: {e}")
        return {"error": str(e), "trades": []}


# ── WebSocket: Orderbook ────────────────────────────────────────────────────────

@router.websocket("/ws/orderbook/{symbol}")
async def ws_orderbook(
    websocket: WebSocket,
    symbol: str,
    exchange: str = Query("hyperliquid"),
    interval: float = Query(1.5, description="Poll interval in seconds"),
):
    """
    WebSocket: streams orderbook updates for any exchange.
    Polls the exchange-specific tradebook module at `interval` seconds.
    Sends: {"type": "orderbook", "exchange": "...", "symbol": "...", "data": {...}}
    If exchange has no orderbook (Ostium/Avantis), sends {"type": "orderbook_unavailable"}.
    """
    await websocket.accept()
    exchange = exchange.lower()
    symbol = symbol.upper()
    mod = _get_tradebook(exchange)

    if not mod:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Unknown exchange: {exchange}",
        }))
        await websocket.close()
        return

    logger.info(f"[Tradebook WS] Orderbook connected: {exchange}/{symbol}")

    first_payload_sent = False

    # Immediate first payload to avoid client-side timeout skeletons on slow upstream responses.
    try:
        if exchange in _ORDERBOOK_UNAVAILABLE_EXCHANGES:
            await websocket.send_text(json.dumps({
                "type": "orderbook_unavailable",
                "exchange": exchange,
                "symbol": symbol,
            }))
        else:
            await websocket.send_text(json.dumps({
                "type": "orderbook",
                "exchange": exchange,
                "symbol": symbol,
                "data": {"bids": [], "asks": []},
            }))
        first_payload_sent = True
    except Exception:
        await websocket.close()
        return

    async def _poll():
        nonlocal first_payload_sent
        while True:
            try:
                book = await mod.get_orderbook(symbol)
                if book is None:
                    payload = json.dumps({
                        "type": "orderbook_unavailable",
                        "exchange": exchange,
                        "symbol": symbol,
                    })
                else:
                    payload = json.dumps({
                        "type": "orderbook",
                        "exchange": exchange,
                        "symbol": symbol,
                        "data": book,
                    })
                await websocket.send_text(payload)
                first_payload_sent = True
            except Exception as e:
                logger.debug(f"[Tradebook WS] Orderbook poll error {exchange}/{symbol}: {e}")
                # Keep socket alive on transient upstream failures.
                if not first_payload_sent:
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "orderbook",
                            "exchange": exchange,
                            "symbol": symbol,
                            "data": {"bids": [], "asks": []},
                        }))
                        first_payload_sent = True
                    except Exception:
                        break
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
    interval: float = Query(2.0, description="Poll interval in seconds"),
):
    """
    WebSocket: streams recent trades for any exchange.
    Polls the exchange-specific tradebook module at `interval` seconds.
    Sends: {"type": "trades", "exchange": "...", "symbol": "...", "data": [...]}
    """
    await websocket.accept()
    exchange = exchange.lower()
    symbol = symbol.upper()
    mod = _get_tradebook(exchange)

    if not mod:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Unknown exchange: {exchange}",
        }))
        await websocket.close()
        return

    logger.info(f"[Tradebook WS] Trades connected: {exchange}/{symbol}")

    seen_ids: set = set()
    first_payload_sent = False
    last_emit_ts = 0.0

    # Immediate first payload so client gets deterministic WS response quickly.
    try:
        initial_payload = {
            "type": "trades",
            "exchange": exchange,
            "symbol": symbol,
            "data": [],
        }
        if exchange in _TRADES_UNAVAILABLE_EXCHANGES:
            initial_payload["available"] = False
        await websocket.send_text(json.dumps(initial_payload))
        first_payload_sent = True
        last_emit_ts = time.time()
    except Exception:
        await websocket.close()
        return

    async def _poll():
        nonlocal seen_ids, first_payload_sent, last_emit_ts
        while True:
            try:
                trades = await mod.get_recent_trades(symbol, limit=30)
                # Only send NEW trades (de-duplicate by id or px+time).
                new_trades = []
                if trades:
                    for t in trades:
                        tid = t.get("id") or f"{t.get('px')}-{t.get('time')}"
                        if tid not in seen_ids:
                            seen_ids.add(tid)
                            new_trades.append(t)

                # Keep seen_ids from growing unbounded
                if len(seen_ids) > 500:
                    seen_ids = set(list(seen_ids)[-200:])

                now = time.time()
                should_emit_empty = (
                    not first_payload_sent
                    or (now - last_emit_ts) >= 10.0
                )

                # Always emit at least one payload soon after connect.
                # This prevents frontend from waiting forever on quiet/unavailable feeds.
                if new_trades or should_emit_empty:
                    payload = {
                        "type": "trades",
                        "exchange": exchange,
                        "symbol": symbol,
                        "data": new_trades if new_trades else [],
                    }
                    if exchange in _TRADES_UNAVAILABLE_EXCHANGES:
                        payload["available"] = False
                    await websocket.send_text(json.dumps(payload))
                    first_payload_sent = True
                    last_emit_ts = now
            except Exception as e:
                logger.debug(f"[Tradebook WS] Trades poll error {exchange}/{symbol}: {e}")
                # Keep socket alive on transient upstream failures.
                if not first_payload_sent:
                    try:
                        payload = {
                            "type": "trades",
                            "exchange": exchange,
                            "symbol": symbol,
                            "data": [],
                            "available": exchange not in _TRADES_UNAVAILABLE_EXCHANGES,
                        }
                        await websocket.send_text(json.dumps(payload))
                        first_payload_sent = True
                        last_emit_ts = time.time()
                    except Exception:
                        break
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
