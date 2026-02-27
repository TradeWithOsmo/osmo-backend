"""Normalize Vest Exchange price data to unified schema"""
from typing import Any, Dict
from datetime import datetime
from services.canonical_source_registry import canonical_registry


def normalize_vest_prices(data: Any) -> Dict[str, Any]:
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
            "timestamp": ts,
            "source": "vest",
            "category": canonical_registry.get_category_sync(symbol),
            "funding_rate": item.get("funding_rate") or 0,
            "open_interest": item.get("open_interest") or 0,
            "volume_24h": item.get("volume_24h") or 0,
            "high_24h": item.get("high_24h") or 0,
            "low_24h": item.get("low_24h") or 0,
            "change_24h": item.get("change_24h") or 0,
            "change_percent_24h": item.get("change_percent_24h") or 0,
            "is_stale": False,
        }
    return normalized
