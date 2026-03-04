"""
Aster tradebook.py
==================
Orderbook and recent trades from Aster Exchange (Binance fapi-compatible).
"""
import logging
from typing import List, Dict, Any, Optional
from .api_client import AsterAPIClient

logger = logging.getLogger(__name__)

# Single shared client — satu httpx.AsyncClient + satu semaphore
_client = AsterAPIClient()


def _to_aster_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTCUSDT, atau pass-through kalau sudah BTCUSDT."""
    if "-" in symbol:
        base = symbol.split("-")[0].upper()
        return f"{base}USDT"
    return symbol.upper()


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    aster_sym = _to_aster_symbol(symbol)
    try:
        raw = await _client.get_depth(aster_sym, limit=depth)
        if not raw:
            return None
        bids = raw.get("bids", [])
        asks = raw.get("asks", [])

        def _parse(entries, n):
            result = []
            for e in entries[:n]:
                try:
                    result.append({"px": str(e[0]), "sz": str(e[1])})
                except (IndexError, TypeError):
                    continue
            return result

        return {
            "bids": _parse(bids, depth),
            "asks": _parse(asks, depth),
        }
    except Exception as e:
        logger.debug(f"[Aster] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    aster_sym = _to_aster_symbol(symbol)
    try:
        trades = await _client.get_recent_trades(aster_sym, limit=limit)
        if not trades:
            return []

        result = []
        for t in trades[:limit]:
            try:
                price = float(t.get("price", 0) or 0)
                qty = float(t.get("qty", 0) or 0)
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