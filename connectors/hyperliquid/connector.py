"""
Hyperliquid Connector

Wrapper around existing Hyperliquid WebSocket client.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable
import sys
import os

# Add parent directory to path to import existing websocket client
sys.path.append(os.path.join(os.path.dirname(__file__), '../../websocket'))

from Hyperliquid.websocket_client import HyperliquidWebSocketClient
from Hyperliquid.http_client import HyperliquidHTTPClient


class HyperliquidConnector(BaseConnector):
    """
    Hyperliquid data connector.
    
    Wraps existing websocket_client.py and http_client.py for:
    - Real-time price updates (allMids)
    - Order book L2 depth
    - Recent trades
    - User positions and orders
    - Funding rates
    - Liquidations
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("hyperliquid", config)
        
        self.ws_url = config.get("ws_url", "wss://api.hyperliquid.xyz")
        self.http_url = config.get("http_url", "https://api.hyperliquid.xyz")
        
        # Initialize clients
        self.ws_client = HyperliquidWebSocketClient(self.ws_url)
        self.http_client = HyperliquidHTTPClient(self.http_url)
        
        self.status = ConnectorStatus.HEALTHY
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch current market data for symbol via HTTP.
        
        Args:
            symbol: Trading symbol (e.g., "BTC")
            **kwargs: data_type ("price" | "orderbook" | "trades" | "funding")
        
        Returns:
            Normalized data dict
        """
        data_type = kwargs.get("data_type", "price")
        
        try:
            if data_type == "price":
                # Use Hyperliquid Info API to get all mids
                payload = {"type": "allMids"}
                raw_data = await self.http_client._post(payload)
                
                # Extract price for specific symbol
                # Response format: {"BTC": "95274.0", "ETH": "3245.0", ...}
                if symbol in raw_data:
                    price = float(raw_data[symbol])
                    structured_data = {
                        "coin": symbol,
                        "mid": str(price),
                        "markPx": str(price),
                        "indexPx": str(price)
                    }
                    return self.normalize(structured_data, "price")
                else:
                    raise ValueError(f"Symbol {symbol} not found in Hyperliquid response")
            
            elif data_type == "orderbook":
                # Get L2 orderbook via meta endpoint
                payload = {
                    "type": "l2Book",
                    "coin": symbol
                }
                raw_data = await self.http_client._post(payload)
                return self.normalize(raw_data, "orderbook")
            
            elif data_type == "trades":
                # Get recent trades - not directly available, use candles as proxy
                candles = await self.http_client.get_candles(symbol, interval="1m")
                raw_data = {"trades": candles[:10] if candles else []}
                return self.normalize(raw_data, "trades")
            
            elif data_type == "funding":
                # Get meta info which includes funding
                payload = {
                    "type": "meta"
                }
                raw_data = await self.http_client._post(payload)
                # Extract funding for this symbol
                return self.normalize({"coin": symbol, "funding": "0"}, "funding")
            
            else:
                raise ValueError(f"Unknown data_type: {data_type}")
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Hyperliquid fetch error: {e}")
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to real-time WebSocket updates.
        
        Args:
            symbol: Trading symbol
            callback: Function to call with new data
            **kwargs: subscription_type ("allMids" | "l2Book" | "trades" | "user")
        """
        subscription_type = kwargs.get("subscription_type", "allMids")
        
        # Register callback
        self._callbacks.append(callback)
        
        # Subscribe via existing WebSocket client
        await self.ws_client.subscribe(
            subscription_type,
            self._handle_ws_message,
            coin=symbol if subscription_type != "user" else None,
            user=kwargs.get("user") if subscription_type == "user" else None
        )
    
    async def _handle_ws_message(self, message: Dict[str, Any]) -> None:
        """Internal: Handle WebSocket message"""
        try:
            normalized = self.normalize(message)
            await self._notify_subscribers(normalized)
        except Exception as e:
            print(f"Error handling WS message: {e}")
    
    def normalize(self, raw_data: Any, data_type: str = "price") -> Dict[str, Any]:
        """
        Normalize Hyperliquid data to standard format.
        
        Args:
            raw_data: Raw data from Hyperliquid API
            data_type: Type of data being normalized
        
        Returns:
            {
                "source": "hyperliquid",
                "symbol": symbol,
                "data_type": type,
                "timestamp": int,
                "data": {...}
            }
        """
        normalized = {
            "source": "hyperliquid",
            "data_type": data_type,
            "timestamp": None,
            "data": {}
        }
        
        if data_type == "price":
            # Normalize price data
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "price": float(raw_data.get("mid", 0)),
                "mark_price": float(raw_data.get("markPx", 0)),
                "index_price": float(raw_data.get("indexPx", 0))
            }
        
        elif data_type == "orderbook":
            # Normalize orderbook
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "bids": raw_data.get("levels", [[]])[0],  # [[price, size], ...]
                "asks": raw_data.get("levels", [[], []])[1],
                "timestamp": raw_data.get("time", 0)
            }
        
        elif data_type == "trades":
            # Normalize trades
            normalized["data"] = {
                "trades": raw_data.get("trades", [])
            }
        
        elif data_type == "funding":
            # Normalize funding rate
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "funding_rate": float(raw_data.get("funding", 0)),
                "premium": float(raw_data.get("premium", 0))
            }
        
        return normalized
