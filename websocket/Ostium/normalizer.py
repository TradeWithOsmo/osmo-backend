"""Data normalization for Ostium API responses"""
from typing import Dict, Any
from datetime import datetime


def normalize_symbol(asset: str) -> str:
    """
    Normalize Ostium asset symbol to unified format
    
    Examples:
        EURUSD → EUR-USD
        GBPUSD → GBP-USD
        XAUUSD → XAU-USD (Gold)
    """
    if "-" in asset:
        return asset  # Already normalized
    
    # Insert hyphen between base and quote (assuming 6-char format like EURUSD)
    if len(asset) == 6:
        return f"{asset[:3]}-{asset[3:]}"
    
    # Special cases for metals
    if asset.startswith("XAU"):
        return "XAU-USD"  # Gold
    if asset.startswith("XAG"):
        return "XAG-USD"  # Silver
    
    return asset  # Return as-is if we can't parse


def normalize_ostium_prices(data: Any) -> Dict[str, Any]:
    """
    Normalize Ostium price data to unified schema
    
    Input format: Ostium API response (list of price objects)
    Example: {"from": "EUR", "to": "USD", "mid": 1.095, "timestampSeconds": 1768329828}
    Output: {"EUR-USD": {"price": "1.095", "timestamp": ..., "source": "ostium"}, ...}
    """
    normalized = {}
    current_timestamp = int(datetime.now().timestamp() * 1000)
    
    # Handle list format (actual Ostium API response)
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            
            # Ostium API format: {"from": "EUR", "to": "USD", "mid": 1.095}
            from_curr = item.get('from')
            to_curr = item.get('to')
            mid_price = item.get('mid')
            
            if not from_curr or not to_curr or mid_price is None:
                continue
            
            # Build symbol (EUR + USD → EUR-USD)
            symbol = f"{from_curr}-{to_curr}"
            
            # Extract timestamp (convert to milliseconds if needed)
            timestamp = item.get('timestamp') or item.get('timestampSeconds')
            if timestamp:
                # If timestamp is in seconds, convert to milliseconds
                if timestamp < 10000000000:  # Likely seconds
                    timestamp = timestamp * 1000
            else:
                timestamp = current_timestamp
            
            normalized[symbol] = {
                "symbol": symbol,
                "price": str(mid_price),
                "timestamp": int(timestamp),
                "source": "ostium",
                "is_stale": False,  # TODO: Check based on isMarketOpen
                "market_open": item.get('isMarketOpen', True)
            }
    
    # Handle dict format (for compatibility/legacy)
    elif isinstance(data, dict):
        for asset, price_data in data.items():
            symbol = normalize_symbol(asset)
            
            # Extract price (handle different formats)
            if isinstance(price_data, dict):
                price = str(price_data.get("price", price_data.get("value", "0")))
                price_timestamp = price_data.get("timestamp", current_timestamp)
            else:
                price = str(price_data)
                price_timestamp = current_timestamp
            
            normalized[symbol] = {
                "symbol": symbol,
                "price": price,
                "timestamp": price_timestamp,
                "source": "ostium",
                "is_stale": False
            }
    
    return normalized


def check_market_hours(symbol: str, trading_hours: Dict[str, Any]) -> bool:
    """
    Check if market is currently open based on trading hours
    
    Args:
        symbol: Trading symbol
        trading_hours: Response from /trading-hours/asset-schedule
    
    Returns:
        True if market is open, False otherwise
    """
    if not trading_hours:
        return True  # Default to open if we can't determine
    
    return trading_hours.get("isOpenNow", True)
