"""Data normalization for Hyperliquid messages"""
from typing import Dict, Any


def normalize_symbol(coin: str) -> str:
    """
    Normalize Hyperliquid coin symbol to unified format
    
    Examples:
        BTC → BTC-USD
        ETH → ETH-USD
        SOL → SOL-USD
    """
    if "-" in coin:
        return coin  # Already normalized
    return f"{coin}-USD"


def normalize_price(price: Any) -> str:
    """Convert price to string for precision preservation"""
    return str(price)


def normalize_timestamp(timestamp: int) -> int:
    """
    Ensure timestamp is in Unix milliseconds
    
    Hyperliquid timestamps are already in milliseconds
    """
    return timestamp


def normalize_all_mids(data: Dict[str, str]) -> Dict[str, Any]:
    """
    Normalize allMids message from Hyperliquid
    
    Input: {"mids": {"BTC": "45000.5", "ETH": "2500.0"}}
    Output: {"BTC-USD": {"price": "45000.5", "timestamp": ...}, ...}
    """
    from datetime import datetime
    
    normalized = {}
    timestamp = int(datetime.now().timestamp() * 1000)
    
    for coin, price in data.get("mids", {}).items():
        symbol = normalize_symbol(coin)
        normalized[symbol] = {
            "symbol": symbol,
            "price": normalize_price(price),
            "timestamp": timestamp,
            "source": "hyperliquid",
            "is_stale": False
        }
    
    return normalized


def normalize_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize trade message from Hyperliquid
    
    Input: WsTrade format
    Output: Unified trade format
    """
    return {
        "source": "hyperliquid",
        "symbol": normalize_symbol(trade["coin"]),
        "price": normalize_price(trade["px"]),
        "size": normalize_price(trade["sz"]),
        "side": trade["side"].lower(),
        "timestamp": normalize_timestamp(trade["time"]),
        "trade_id": trade.get("tid"),
        "is_stale": False
    }


def normalize_orderbook(book: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize l2Book message from Hyperliquid
    
    Input: WsBook format
    Output: Unified orderbook format
    """
    bids, asks = book["levels"]
    
    return {
        "source": "hyperliquid",
        "symbol": normalize_symbol(book["coin"]),
        "bids": [
            {"price": normalize_price(level["px"]), "size": normalize_price(level["sz"])}
            for level in bids
        ],
        "asks": [
            {"price": normalize_price(level["px"]), "size": normalize_price(level["sz"])}
            for level in asks
        ],
        "timestamp": normalize_timestamp(book["time"]),
        "is_stale": False
    }
