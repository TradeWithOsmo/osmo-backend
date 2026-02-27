"""
Hyperliquid tradebook.py
========================
Orderbook and recent trades fetched from Hyperliquid REST API.
(WS l2Book / trades subscriptions are handled separately in main.py)
Public HTTP endpoints (no auth needed):
  POST https://api.hyperliquid.xyz/info  → type=l2Book / recentTrades
"""
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_BASE = "https://api.hyperliquid.xyz/info"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    """
    coin = symbol.split("-")[0].upper()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(_BASE, json={"type": "l2Book", "coin": coin, "nSigFigs": 4})
            resp.raise_for_status()
            data = resp.json()
            levels = data.get("levels", [])
            if len(levels) < 2:
                return None
            bids_raw, asks_raw = levels[0], levels[1]
            return {
                "bids": [{"px": l["px"], "sz": l["sz"]} for l in bids_raw[:depth]],
                "asks": [{"px": l["px"], "sz": l["sz"]} for l in asks_raw[:depth]],
            }
    except Exception as e:
        logger.debug(f"[Hyperliquid] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades list:
      [{"px": "...", "sz": "...", "side": "B"/"S", "time": ms_timestamp}]
    """
    coin = symbol.split("-")[0].upper()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(_BASE, json={"type": "recentTrades", "coin": coin})
            resp.raise_for_status()
            trades = resp.json()
            if not isinstance(trades, list):
                return []
            return [
                {
                    "px": str(t.get("px", 0)),
                    "sz": str(t.get("sz", 0)),
                    "side": t.get("side", "B"),
                    "time": t.get("time"),
                    "hash": t.get("hash"),
                }
                for t in trades[:limit]
            ]
    except Exception as e:
        logger.debug(f"[Hyperliquid] recent trades {symbol} failed: {e}")
        return []
