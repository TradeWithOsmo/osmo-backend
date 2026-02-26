"""
price_cache.py
==============
Shared in-process cache for live price + stats data.

main.py writes to `latest_prices` via `update_price()`.
routers/markets.py reads from it to enrich market data with
24h stats (high, low, volume, change, OI, funding, etc.).
"""

from __future__ import annotations
from typing import Dict, Any

# symbol (e.g. "BTC-USD") -> dict of live stats
latest_prices: Dict[str, Dict[str, Any]] = {}


def update_price(symbol: str, data: Dict[str, Any]) -> None:
    """Merge new data into the cache for a symbol."""
    if symbol in latest_prices:
        latest_prices[symbol].update(data)
    else:
        latest_prices[symbol] = dict(data)


def get_price(symbol: str) -> Dict[str, Any]:
    """Return the cached data for a symbol, or empty dict."""
    return latest_prices.get(symbol, {})


def enrich_market(market: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge live stats from price cache into a market dict.
    Safe: only overwrites fields that are missing or zero.
    """
    sym = market.get("symbol", "")
    cached = latest_prices.get(sym, {})
    if not cached:
        return market

    STAT_FIELDS = [
        "price", "change_24h", "change_percent_24h",
        "high_24h", "low_24h", "volume_24h",
        "openInterest", "funding", "markPrice",
    ]
    for field in STAT_FIELDS:
        if field in cached:
            cache_val = cached[field]
            current_val = market.get(field)
            # Only overwrite if the current value is missing or zero
            if current_val is None or current_val == 0:
                market[field] = cache_val
    return market
