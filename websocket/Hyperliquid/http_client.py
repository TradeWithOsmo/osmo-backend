import httpx
import logging
import json
import time
from typing import Optional, Dict, List, Any
from config import settings

logger = logging.getLogger(__name__)

class HyperliquidHTTPClient:
    """HTTP Client for Hyperliquid Info API"""
    
    def __init__(self, base_url: str = "https://api.hyperliquid.xyz"):
        self.base_url = base_url
        self.rate_limit_remaining = 1200
        
    async def _post(self, payload: dict) -> Any:
        """Execute POST request to Info API"""
        url = f"{self.base_url}/info"
        headers = {"Content-Type": "application/json"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=10.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"Hyperliquid API Error: {e} - Payload: {payload}")
                raise

    async def get_candles(self, coin: str, interval: str = "1m", start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[dict]:
        """
        Fetch OHLCV candles
        Intervals: 1m, 5m, 15m, 1h, 4h, 8h, 1d
        """
        # Hyperliquid API uses start_time and end_time in millis
        if not start_time:
            start_time = int((time.time() - 3600) * 1000) # Default last 1h
        if not end_time:
            end_time = int(time.time() * 1000)
            
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time
            }
        }
        
        try:
            data = await self._post(payload)
            # Normalize data
            # HL returns: [{"t": 123, "o": "1.0", "h": "1.1", "l": "0.9", "c": "1.0", "v": "100", ...}]
            normalized = []
            for c in data:
                normalized.append({
                    "timestamp": c["t"],
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "volume": float(c["v"]),
                    "symbol": f"{coin}-USD"
                })
            return normalized
        except Exception:
            return []

    async def get_user_state(self, user_address: str) -> Dict[str, Any]:
        """
        Fetch user clearinghouse state (balances, positions)
        """
        payload = {
            "type": "clearinghouseState",
            "user": user_address
        }
        
        return await self._post(payload)

    async def get_user_open_orders(self, user_address: str) -> List[dict]:
        """Fetch open orders"""
        payload = {
            "type": "openOrders",
            "user": user_address
        }
        return await self._post(payload)

# Global Instance
http_client = HyperliquidHTTPClient()
