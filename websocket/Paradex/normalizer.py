"""Normalize Paradex price data to unified schema"""
from typing import Any, Dict
from datetime import datetime
from services.canonical_source_registry import canonical_registry


def normalize_paradex_prices(data: Any) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    ts = int(datetime.now().timestamp() * 1000)

    items = data if isinstance(data, list) else []
    for item in items:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        # Paradex symbols look like BTC-USD-PERP → normalize to BTC-USD
        display_sym = symbol.replace("-USD-PERP", "-USD").replace("-PERP", "-USD")
        normalized[display_sym] = {
            "symbol": display_sym,
            "price": str(item.get("mark_price") or item.get("last_traded_price") or 0),
            "timestamp": ts,
            "source": "paradex",
            "category": canonical_registry.get_category_sync(display_sym),
            "funding_rate": item.get("funding_rate") or 0,
            "open_interest": item.get("open_interest") or 0,
            "volume_24h": item.get("volume_24h") or 0,
            "is_stale": False,
        }
    return normalized
