from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
import logging
import time

from Hyperliquid.http_client import http_client as hl_client
# Example: from ..Ostium.api_client import ostium_client # If implemented

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("")
async def get_history(
    symbol: str,
    resolution: str,
    from_ts: int = Query(..., alias="from"),
    to_ts: int = Query(..., alias="to"),
    source: str = "hyperliquid"
):
    """
    Get historical k-lines (candles) for TradingView
    """
    try:
        if source.lower() == "hyperliquid":
            # Map TV resolution to HL interval
            # TV: 1, 5, 15, 60, 240, 1D
            interval_map = {
                "1": "1m",
                "5": "5m",
                "15": "15m",
                "60": "1h",
                "240": "4h",
                "1D": "1d",
                "D": "1d"
            }
            interval = interval_map.get(resolution, "1h")
            
            # HL expects coin name without -USD suffix usually, or we strip it
            coin = symbol.split("-")[0] 
            
            # Timestamps: TV sends seconds, HL wants millis
            start_ms = int(from_ts * 1000)
            end_ms = int(to_ts * 1000)
            
            candles = await hl_client.get_candles(coin, interval, start_ms, end_ms)
            
            # Format for TradingView (array of objects is implicitly expected by frontend adapter, 
            # OR standard UDF return format. 
            # Looking at marketService: `return response.data;`
            # Frontend TradingView adapter likely expects:
            # { s: "ok", t: [times], o: [opens], ... } OR array of { time, open, high, low, close, volume }
            # Let's assume array of objects based on `marketService` returning `response.data` directly
            # and generic TV adapters often taking that if custom.
            # actually `HyperliquidHTTPClient.get_candles` returns list of dicts:
            # {"timestamp": ..., "open": ...}
            # We return this list directly.
            
            return candles
            
        elif source.lower() == "ostium":
            # Stub for Ostium
            return []
            
        else:
            return []

    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        # Return empty list on error to avoid breaking chart
        return []
