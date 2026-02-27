"""
Orderly tradebook.py
====================
Orderbook and recent trades from Orderly Network REST API.
Endpoints:
  GET https://api-evm.orderly.org/v1/public/orderbook?symbol=PERP_BTC_USDC
  GET https://api-evm.orderly.org/v1/public/trades?symbol=PERP_BTC_USDC
Orderly symbol format: PERP_BTC_USDC, PERP_ETH_USDC
"""
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_BASE = "https://api-evm.orderly.org/v1"


def _to_orderly_symbol(symbol: str) -> str:
    """Convert BTC-USD → PERP_BTC_USDC (Orderly internal format)."""
    base = symbol.split("-")[0].upper()
    return f"PERP_{base}_USDC"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    Orderly format: {"data": {"bids": [[price, qty], ...], "asks": [...]}}
    """
    orderly_sym = _to_orderly_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/public/orderbook",
                params={"symbol": orderly_sym, "max_level": depth},
            )
            resp.raise_for_status()
            book = resp.json().get("data", {})
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            return {
                "bids": [{"px": str(b[0]), "sz": str(b[1])} for b in bids[:depth]],
                "asks": [{"px": str(a[0]), "sz": str(a[1])} for a in asks[:depth]],
            }
    except Exception as e:
        logger.debug(f"[Orderly] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format.
    Orderly trades: {"data": {"rows": [{"executed_price", "executed_quantity", "side", "executed_timestamp"}]}}
    """
    orderly_sym = _to_orderly_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/public/market_trades",
                params={"symbol": orderly_sym, "limit": limit},
            )
            resp.raise_for_status()
            rows = resp.json().get("data", {}).get("rows", [])
            result = []
            for t in rows[:limit]:
                try:
                    price = float(t.get("executed_price", 0))
                    qty = float(t.get("executed_quantity", 0))
                    if price <= 0:
                        continue
                    side_raw = t.get("side", "BUY").upper()
                    result.append({
                        "px": str(price),
                        "sz": str(qty),
                        "side": "B" if "BUY" in side_raw else "S",
                        "time": t.get("executed_timestamp"),
                        "id": str(t.get("id", "")),
                    })
                except Exception:
                    continue
            return result
    except Exception as e:
        logger.debug(f"[Orderly] recent trades {symbol} failed: {e}")
        return []
