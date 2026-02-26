"""Normalize Lighter price data to unified schema"""
from typing import Any, Dict
from datetime import datetime
from services.canonical_source_registry import canonical_registry


def normalize_lighter_prices(data: Any) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    ts = int(datetime.now().timestamp() * 1000)

    items = data if isinstance(data, list) else []
    for item in items:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        normalized[symbol] = {
            "symbol": symbol,
            "price": str(item.get("price") or 0),
            "best_bid": item.get("best_bid") or 0,
            "best_ask": item.get("best_ask") or 0,
            "spread": item.get("spread") or 0,
            "timestamp": ts,
            "source": "lighter",
            "category": canonical_registry.get_category_sync(symbol),
            "funding_rate": item.get("funding_rate") or 0,
            "open_interest": item.get("open_interest") or 0,
            "is_stale": False,
        }
    return normalized
