"""Normalize Aevo price data to unified schema"""
from typing import Any, Dict
from datetime import datetime
from services.canonical_source_registry import canonical_registry


def normalize_aevo_prices(data: Any) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    ts = int(datetime.now().timestamp() * 1000)

    items = data if isinstance(data, list) else []
    for item in items:
        # Aevo instruments look like ETH-PERP → normalize to ETH-USD
        instrument_name = item.get("instrument_name", "")
        underlying = item.get("underlying_asset", "") or instrument_name.replace("-PERP", "")
        if not underlying:
            continue
        symbol = f"{underlying.upper()}-USD"
        normalized[symbol] = {
            "symbol": symbol,
            "price": str(item.get("mark_price") or item.get("index_price") or 0),
            "timestamp": ts,
            "source": "aevo",
            "category": canonical_registry.get_category_sync(symbol),
            "funding_rate": item.get("funding_rate") or 0,
            "open_interest": item.get("open_interest") or 0,
            "volume_24h": item.get("volume") or 0,
            "is_stale": False,
        }
    return normalized
