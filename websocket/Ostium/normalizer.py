from typing import Dict, Any
from datetime import datetime
from services.canonical_source_registry import canonical_registry

def normalize_symbol(asset: str) -> str:
    """
    Normalize Ostium asset symbol to unified format
    """
    if "-" in asset:
        return asset
    
    if len(asset) == 6:
        return f"{asset[:3]}-{asset[3:]}"
    
    if asset.startswith("XAU"):
        return "XAU-USD"
    if asset.startswith("XAG"):
        return "XAG-USD"
    
    return asset

# Removed get_ostium_category since it is now centralized in canonical_source_registry

def get_ostium_max_leverage(category: str) -> int:
    """Return safe default max leverage based on category"""
    if category == "Forex":
        return 100
    if category == "Stocks":
        return 20
    if category == "Commodities":
        return 50
    if category.upper() == "INDEX" or category.lower() == "index":
        return 50
    return 50

def normalize_ostium_prices(data: Any) -> Dict[str, Any]:
    """
    Normalize Ostium price data to unified schema
    """
    normalized = {}
    current_timestamp = int(datetime.now().timestamp() * 1000)
    
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            
            from_curr = item.get('from')
            to_curr = item.get('to')
            mid_price = item.get('mid')
            
            if not from_curr or not to_curr or mid_price is None:
                continue
            
            symbol = f"{from_curr}-{to_curr}"
            
            timestamp = item.get('timestamp') or item.get('timestampSeconds')
            if timestamp:
                if timestamp < 10000000000:
                    timestamp = timestamp * 1000
            else:
                timestamp = current_timestamp
            
            cat = canonical_registry.get_category_sync(symbol)
            normalized[symbol] = {
                "symbol": symbol,
                "price": str(mid_price),
                "timestamp": int(timestamp),
                "source": "ostium",
                "category": cat,
                "maxLeverage": get_ostium_max_leverage(cat),
                "is_stale": False,
                "market_open": item.get('isMarketOpen', True),
                "canonical": canonical_registry.is_canonical_source(from_curr, "ostium")
            }
    
    elif isinstance(data, dict):
        for asset, price_data in data.items():
            symbol = normalize_symbol(asset)
            
            if isinstance(price_data, dict):
                price = str(price_data.get("price", price_data.get("value", "0")))
                price_timestamp = price_data.get("timestamp", current_timestamp)
            else:
                price = str(price_data)
                price_timestamp = current_timestamp
            
            cat = canonical_registry.get_category_sync(symbol)
            normalized[symbol] = {
                "symbol": symbol,
                "price": price,
                "timestamp": price_timestamp,
                "source": "ostium",
                "category": cat,
                "maxLeverage": get_ostium_max_leverage(cat),
                "is_stale": False,
                "canonical": canonical_registry.is_canonical_source(symbol.split("-")[0], "ostium")
            }
    
    return normalized

def check_market_hours(symbol: str, trading_hours: Dict[str, Any]) -> bool:
    """Check if market is currently open"""
    if not trading_hours:
        return True
    return trading_hours.get("isOpenNow", True)
