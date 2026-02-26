"""Normalize Avantis price data to unified schema"""
from typing import Any, Dict, List
from datetime import datetime
from services.canonical_source_registry import canonical_registry


def normalize_avantis_prices(data: Any) -> Dict[str, Any]:
    """Convert raw Avantis price list to {symbol: price_dict} map."""
    normalized: Dict[str, Any] = {}
    ts = int(datetime.now().timestamp() * 1000)

    items = data if isinstance(data, list) else []
    for item in items:
        symbol = item.get("symbol", "")
        if not symbol:
            from_sym = item.get("from", "")
            to_sym = item.get("to", "USD")
            symbol = f"{from_sym}-{to_sym}" if from_sym else ""
        if not symbol:
            continue

        normalized[symbol] = {
            "symbol": symbol,
            "price": str(item.get("price") or 0),
            "timestamp": ts,
            "source": "avantis",
            "category": canonical_registry.get_category_sync(symbol),
            "funding_rate": item.get("funding_rate_long") or item.get("funding_rate") or 0,
            "open_interest": item.get("open_interest") or 0,
            "is_stale": item.get("price") is None,
        }
    return normalized
