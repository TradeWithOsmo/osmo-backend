"""
TradingView Connector

Receive pre-calculated indicators from frontend TradingView widget.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable, List
import json


class TradingViewConnector(BaseConnector):
    """
    TradingView data receiver connector.
    
    This is a RECEIVE-ONLY connector. It doesn't fetch from TradingView API.
    Instead, it receives indicator data extracted by frontend from the widget.
    
    Data Flow:
    1. Frontend extracts indicators via chart.getAllStudies()
    2. Frontend POSTs to /api/tradingview/indicators
    3. This connector stores in Redis
    4. AI agent reads from Redis
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("tradingview", config)
        
        self.redis_client = config.get("redis_client")
        self.cache_ttl = config.get("cache_ttl", 60)  # 60 seconds default
        
        if self.redis_client:
            self.status = ConnectorStatus.HEALTHY
        else:
            self.status = ConnectorStatus.OFFLINE
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch cached indicators from Redis.
        
        Args:
            symbol: Trading symbol
            **kwargs: timeframe (required)
        
        Returns:
            Cached indicator data or error if not found
        """
        timeframe = kwargs.get("timeframe")
        if not timeframe:
            raise ValueError("timeframe is required")
        
        try:
            cache_key = f"indicators:{symbol}:{timeframe}"
            cached = await self.redis_client.get(cache_key)
            
            if not cached:
                raise ValueError(
                    f"No indicators cached for {symbol} {timeframe}. "
                    "Frontend needs to send data first."
                )
            
            data = json.loads(cached)
            return self.normalize(data)
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to indicator updates.
        
        Note: This monitors Redis for new data, not a WebSocket.
        """
        raise NotImplementedError(
            "TradingView subscription not implemented. Use polling."
        )
    
    async def store_indicators(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store indicator data received from frontend.
        
        Args:
            data: {
                "symbol": str,
                "timeframe": str,
                "indicators": {...},
                "chart_screenshot": str (optional),
                "timestamp": int
            }
        
        Returns:
            {"status": "stored", "symbol": str, "count": int}
        """
        symbol = data.get("symbol")
        timeframe = data.get("timeframe")
        
        if not symbol or not timeframe:
            raise ValueError("symbol and timeframe are required")
        
        # Store in Redis
        cache_key = f"indicators:{symbol}:{timeframe}"
        
        await self.redis_client.setex(
            cache_key,
            self.cache_ttl,
            json.dumps(data)
        )
        
        return {
            "status": "stored",
            "symbol": symbol,
            "timeframe": timeframe,
            "indicator_count": len(data.get("indicators", {})),
            "has_screenshot": "chart_screenshot" in data
        }
    
    async def queue_command(self, symbol: str, command: Dict[str, Any]) -> None:
        """
        Queue a command for the frontend to execute.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            command: Command dict (e.g., {"action": "set_timeframe", "params": "1h"})
        """
        if not symbol or not command:
            return
            
        key = f"commands:tradingview:{symbol}"
        # Expire commands after 60s if not picked up
        await self.redis_client.rpush(key, json.dumps(command))
        await self.redis_client.expire(key, 60)
        
    async def get_pending_commands(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get and clear pending commands for a symbol.
        """
        key = f"commands:tradingview:{symbol}"
        
        # Get all items
        # Use simple transaction logic: get all, delete key
        # Or just lpop loop. lrange + del is safer for atomicity if script, but here simple is fine.
        
        # Using pipeline for atomicity
        async with self.redis_client.pipeline() as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            result = await pipe.execute()
            
        raw_commands = result[0]
        commands = []
        for cmd_str in raw_commands:
            try:
                commands.append(json.loads(cmd_str))
            except:
                pass
                
        return commands

    def normalize(self, raw_data: Any) -> Dict[str, Any]:
        """
        Normalize TradingView data.
        
        Args:
            raw_data: Indicator data from frontend
        
        Returns:
            {
                "source": "tradingview",
                "symbol": symbol,
                "data_type": "indicators",
                "timestamp": int,
                "data": {
                    "timeframe": str,
                    "indicators": {...},
                    "screenshot": str (optional)
                }
            }
        """
        return {
            "source": "tradingview",
            "symbol": raw_data.get("symbol", "UNKNOWN"),
            "data_type": "indicators",
            "timestamp": raw_data.get("timestamp", 0),
            "data": {
                "timeframe": raw_data.get("timeframe"),
                "indicators": raw_data.get("indicators", {}),
                "screenshot": raw_data.get("chart_screenshot")
            }
        }
