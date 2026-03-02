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


def _tick_from_prices(prices: List[float]) -> float:
    uniq = sorted(set([p for p in prices if p > 0]))
    if len(uniq) >= 2:
        diffs = [uniq[i + 1] - uniq[i] for i in range(len(uniq) - 1) if (uniq[i + 1] - uniq[i]) > 0]
        if diffs:
            return max(min(diffs), 1e-6)
    if not uniq:
        return 0.001
    p = uniq[0]
    if p >= 1000:
        return 1.0
    if p >= 100:
        return 0.1
    if p >= 1:
        return 0.001
    if p >= 0.1:
        return 0.0001
    return 0.00001


def _normalize_and_pad_book(raw_bids: List[Any], raw_asks: List[Any], depth: int) -> Dict[str, List[Dict[str, str]]]:
    bids: List[Dict[str, str]] = []
    asks: List[Dict[str, str]] = []

    for b in raw_bids or []:
        try:
            px = float(b[0])
            sz = float(b[1])
            if px > 0 and sz > 0:
                bids.append({"px": str(px), "sz": str(sz)})
        except Exception:
            continue
    for a in raw_asks or []:
        try:
            px = float(a[0])
            sz = float(a[1])
            if px > 0 and sz > 0:
                asks.append({"px": str(px), "sz": str(sz)})
        except Exception:
            continue

    bids = sorted(bids, key=lambda x: float(x["px"]), reverse=True)[:depth]
    asks = sorted(asks, key=lambda x: float(x["px"]))[:depth]

    all_prices = [float(x["px"]) for x in bids] + [float(x["px"]) for x in asks]
    tick = _tick_from_prices(all_prices)

    if bids:
        last_bid_px = float(bids[-1]["px"])
        last_bid_sz = max(float(bids[-1]["sz"]), 1e-9)
        while len(bids) < depth:
            last_bid_px = max(last_bid_px - tick, tick)
            bids.append({"px": str(last_bid_px), "sz": str(last_bid_sz)})

    if asks:
        last_ask_px = float(asks[-1]["px"])
        last_ask_sz = max(float(asks[-1]["sz"]), 1e-9)
        while len(asks) < depth:
            last_ask_px = last_ask_px + tick
            asks.append({"px": str(last_ask_px), "sz": str(last_ask_sz)})

    return {"bids": bids, "asks": asks}


async def get_orderbook(symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
    """
    Returns orderbook in unified format:
      {"bids": [{"px": "...", "sz": "..."}], "asks": [...]}
    Paradex format: {"bids": [["price", "size"], ...], "asks": [...]}
    """
    paradex_sym = _to_paradex_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=8, verify=False) as client:
            resp = await client.get(f"{_BASE}/orderbook/{paradex_sym}")
            resp.raise_for_status()
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            return _normalize_and_pad_book(bids, asks, depth)
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
