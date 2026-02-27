"""
Vest tradebook.py
=================
Orderbook and recent trades from Vest Exchange REST API.
Endpoints:
  GET /depth?symbol=BTC-PERP&limit=20
  GET /trades?symbol=BTC-PERP&limit=50
Vest symbol format: BTC-PERP, ETH-PERP, BTC-USD-PERP (forex)
"""
import logging
from typing import List, Dict, Any, Optional
from .api_client import VestAPIClient

logger = logging.getLogger(__name__)
_client = VestAPIClient()


def _to_vest_symbol(symbol: str) -> str:
    """Convert BTC-USD → BTC-PERP (Vest internal format)."""
    base = symbol.split("-")[0].upper()
    return f"{base}-PERP"


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    """
    vest_sym = _to_vest_symbol(symbol)
    try:
        raw = await _client.get_depth(vest_sym, limit=depth)
        if not raw:
            return None
        bids = raw.get("bids", [])
        asks = raw.get("asks", [])
        return {
            "bids": [{"px": str(b[0]), "sz": str(b[1])} for b in bids[:depth]],
            "asks": [{"px": str(a[0]), "sz": str(a[1])} for a in asks[:depth]],
        }
    except Exception as e:
        logger.debug(f"[Vest] orderbook {symbol} failed: {e}")
        return None


async def get_recent_trades(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Returns trades in unified format:
      [{"px": ..., "sz": ..., "side": "B"/"S", "time": ms_timestamp}]
    """
    vest_sym = _to_vest_symbol(symbol)
    try:
        trades = await _client.get_recent_trades(vest_sym, limit=limit)
        if not trades:
            return []
        return [
            {
                "px": str(t.get("px", 0)),
                "sz": str(t.get("sz", 0)),
                "side": t.get("side", "B"),
                "time": t.get("time"),
                "id": t.get("id"),
            }
            for t in trades
        ]
    except Exception as e:
        logger.debug(f"[Vest] recent trades {symbol} failed: {e}")
        return []
