"""
Indicator Data - Receiver Module

Receive pre-calculated indicators from TradingView frontend.
"""

from typing import Dict, Any, Optional
import json


async def receive_indicators(
    redis_client,
    data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Receive and store indicator data from TradingView widget.
    
    Args:
        redis_client: Redis connection
        data: {
            "symbol": str,
            "timeframe": str,
            "indicators": {
                "RSI_14": float,
                "MACD_signal": float,
                "EMA_9": float,
                ...
            },
            "chart_screenshot": str (optional base64),
            "timestamp": int
        }
    
    Returns:
        {"status": "stored", "symbol": str, "count": int}
    """
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    
    if not symbol or not timeframe:
        raise ValueError("symbol and timeframe are required")
    
    # Store in Redis with 60 second TTL
    cache_key = f"indicators:{symbol}:{timeframe}"
    
    await redis_client.setex(
        cache_key,
        60,  # 60 seconds TTL
        json.dumps(data)
    )
    
    return {
        "status": "stored",
        "symbol": symbol,
        "count": len(data.get("indicators", {}))
    }


async def get_indicators(
    redis_client,
    symbol: str,
    timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Get cached indicators from Redis.
    
    Args:
        redis_client: Redis connection
        symbol: Trading symbol
        timeframe: Chart timeframe (e.g., "1H", "4H")
    
    Returns:
        Indicator data dict or None if not found/expired
    """
    cache_key = f"indicators:{symbol}:{timeframe}"
    
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    return None
