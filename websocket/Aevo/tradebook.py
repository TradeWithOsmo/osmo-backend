"""
Aevo tradebook.py
=================
Orderbook and recent trades from Aevo REST API (Ethereum, options+perps).
Endpoints:
  GET https://api.aevo.xyz/orderbook?instrument_name=BTC-PERP
  GET https://api.aevo.xyz/trades?instrument_name=BTC-PERP
Aevo instrument format: BTC-PERP, ETH-PERP
"""
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_BASE = "https://api.aevo.xyz"


def _to_aevo_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTC-PERP (Aevo instrument format)."""
    base = symbol.split("-")[0].upper()
    return f"{base}-PERP"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    Aevo format: {"bids": [["price", "qty", ...], ...], "asks": [...]}
    """
    aevo_sym = _to_aevo_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/orderbook",
                params={"instrument_name": aevo_sym},
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
        logger.debug(f"[Aevo] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format.
    Aevo trades: [{"instrument_name", "price", "amount", "side", "timestamp"}]
    """
    aevo_sym = _to_aevo_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(
                f"{_BASE}/trades",
                params={"instrument_name": aevo_sym, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            trades_raw = data if isinstance(data, list) else data.get("trades", [])
            result = []
            for t in trades_raw[:limit]:
                try:
                    price = float(t.get("price", 0))
                    amt = float(t.get("amount", 0))
                    if price <= 0:
                        continue
                    side_raw = t.get("side", "buy").lower()
                    result.append({
                        "px": str(price),
                        "sz": str(amt),
                        "side": "B" if side_raw == "buy" else "S",
                        "time": t.get("timestamp"),
                        "id": str(t.get("trade_id", "")),
                    })
                except Exception:
                    continue
            return result
    except Exception as e:
        logger.debug(f"[Aevo] recent trades {symbol} failed: {e}")
        return []
