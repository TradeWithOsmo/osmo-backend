"""
dYdX tradebook.py
=================
Orderbook and recent trades from dYdX v4 Indexer REST API.
Endpoints:
  GET https://indexer.dydx.trade/v4/orderbooks/perpetualMarket/BTC-USD
  GET https://indexer.dydx.trade/v4/trades/perpetualMarket/BTC-USD
dYdX v4 symbol format: BTC-USD, ETH-USD (same as our canonical format)
"""
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_BASE = "https://indexer.dydx.trade/v4"


def _to_dydx_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTC-USD (already correct for dYdX v4)."""
    parts = symbol.split("-")
    base = parts[0].upper()
    return f"{base}-USD"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    dYdX format: {"bids": [{"price": "...", "size": "..."}], "asks": [...]}
    """
    dydx_sym = _to_dydx_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True) as client:
            resp = await client.get(f"{_BASE}/orderbooks/perpetualMarket/{dydx_sym}")
            resp.raise_for_status()
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            return {
                "bids": [{"px": str(b["price"]), "sz": str(b["size"])} for b in bids[:depth]],
                "asks": [{"px": str(a["price"]), "sz": str(a["size"])} for a in asks[:depth]],
            }
    except Exception as e:
        logger.debug(f"[dYdX] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format.
    dYdX trades: [{"price", "size", "side", "createdAt"}]
    """
    dydx_sym = _to_dydx_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True) as client:
            resp = await client.get(
                f"{_BASE}/trades/perpetualMarket/{dydx_sym}",
                params={"limit": limit},
            )
            resp.raise_for_status()
            trades_raw = resp.json().get("trades", [])
            result = []
            for t in trades_raw[:limit]:
                try:
                    price = float(t.get("price", 0))
                    size = float(t.get("size", 0))
                    if price <= 0:
                        continue
                    side_raw = t.get("side", "BUY").upper()
                    result.append({
                        "px": str(price),
                        "sz": str(size),
                        "side": "B" if side_raw == "BUY" else "S",
                        "time": t.get("createdAt"),
                        "id": str(t.get("id", "")),
                    })
                except Exception:
                    continue
            return result
    except Exception as e:
        logger.debug(f"[dYdX] recent trades {symbol} failed: {e}")
        return []
