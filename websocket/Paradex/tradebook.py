"""
Paradex tradebook.py
====================
Orderbook and recent trades from Paradex REST API (StarkNet).
Endpoints:
  GET https://api.prod.paradex.trade/v1/orderbook?market=BTC-USD-PERP
  GET https://api.prod.paradex.trade/v1/trades?market=BTC-USD-PERP
Paradex symbol format: BTC-USD-PERP, ETH-USD-PERP
"""
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_BASE = "https://api.prod.paradex.trade/v1"


def _to_paradex_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTC-USD-PERP (Paradex format)."""
    base = symbol.split("-")[0].upper()
    return f"{base}-USD-PERP"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    Paradex format: {"bids": [["price", "size"], ...], "asks": [...]}
    """
    paradex_sym = _to_paradex_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/orderbook",
                params={"market": paradex_sym},
            )
            resp.raise_for_status()
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            return {
                "bids": [{"px": str(b[0]), "sz": str(b[1])} for b in bids[:depth]],
                "asks": [{"px": str(a[0]), "sz": str(a[1])} for a in asks[:depth]],
            }
    except Exception as e:
        logger.debug(f"[Paradex] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format.
    Paradex trades: {"results": [{"price", "size", "side", "created_at"}]}
    """
    paradex_sym = _to_paradex_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/trades",
                params={"market": paradex_sym, "page_size": limit},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            trades = []
            for t in results[:limit]:
                try:
                    price = float(t.get("price", 0))
                    size = float(t.get("size", 0))
                    if price <= 0:
                        continue
                    side_raw = t.get("side", "BUY").upper()
                    trades.append({
                        "px": str(price),
                        "sz": str(size),
                        "side": "B" if "BUY" in side_raw else "S",
                        "time": t.get("created_at"),
                        "id": str(t.get("id", "")),
                    })
                except Exception:
                    continue
            return trades
    except Exception as e:
        logger.debug(f"[Paradex] recent trades {symbol} failed: {e}")
        return []
