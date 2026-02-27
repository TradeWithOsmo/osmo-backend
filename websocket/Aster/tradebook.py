"""
Aster tradebook.py
==================
Orderbook and recent trades from Aster Exchange (Binance fapi-compatible).
Endpoints:
  GET https://www.asterdex.com/fapi/v1/depth?symbol=BTCUSDT&limit=20
  GET https://www.asterdex.com/fapi/v1/trades?symbol=BTCUSDT&limit=50
Aster symbol format: BTCUSDT, ETHUSDT (Binance perpetuals format)
"""
import logging
from typing import List, Dict, Any, Optional
from .api_client import AsterAPIClient

logger = logging.getLogger(__name__)
_client = AsterAPIClient()


def _to_aster_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTCUSDT (Aster/Binance format)."""
    base = symbol.split("-")[0].upper()
    return f"{base}USDT"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    Binance depth format: {"bids": [["price", "qty"], ...], "asks": [...]}
    """
    aster_sym = _to_aster_symbol(symbol)
    try:
        raw = await _client.get_depth(aster_sym, limit=depth)
        if not raw:
            return None
        bids = raw.get("bids", [])
        asks = raw.get("asks", [])
        return {
            "bids": [{"px": str(b[0]), "sz": str(b[1])} for b in bids[:depth]],
            "asks": [{"px": str(a[0]), "sz": str(a[1])} for a in asks[:depth]],
        }
    except Exception as e:
        logger.debug(f"[Aster] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format.
    Binance trades format: {"id", "price", "qty", "time", "isBuyerMaker"}
    """
    aster_sym = _to_aster_symbol(symbol)
    try:
        trades = await _client.get_recent_trades(aster_sym, limit=limit)
        if not trades:
            return []
        result = []
        for t in trades[:limit]:
            try:
                price = float(t.get("price", 0))
                qty = float(t.get("qty", 0))
                if price <= 0:
                    continue
                is_buyer_maker = t.get("isBuyerMaker", False)
                result.append({
                    "px": str(price),
                    "sz": str(abs(qty)),
                    "side": "S" if is_buyer_maker else "B",
                    "time": t.get("time"),
                    "id": str(t.get("id", "")),
                })
            except Exception:
                continue
        return result
    except Exception as e:
        logger.debug(f"[Aster] recent trades {symbol} failed: {e}")
        return []
