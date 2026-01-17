"""
Ostium Connector

Wrapper around existing Ostium API poller.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable
import sys
import os

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../websocket'))

from Ostium.poller import OstiumPoller
from Ostium.api_client import OstiumAPIClient


class OstiumConnector(BaseConnector):
    """
    Ostium (RWA) data connector.
    
    Wraps existing poller.py and api_client.py for:
    - RWA price feeds (5-second polling)
    - Aggregated volume data
    - Funding rates
    
    Limitations:
    - No WebSocket (HTTP polling only)
    - No orderbook data
    - No individual trade data
    - 5-second latency
    
    For missing data (whale trades, orderbook), use Dune Analytics connector.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("ostium", config)
        
        self.api_url = config.get("api_url", os.getenv("OSTIUM_API_URL"))
        self.poll_interval = config.get("poll_interval", 5)  # 5 seconds
        
        # Initialize clients
        self.api_client = OstiumAPIClient(self.api_url)
        self.poller = OstiumPoller(
            self.api_client,
            self._handle_poll_data,
            self.poll_interval
        )
        
        self.status = ConnectorStatus.HEALTHY
        self._current_prices = {}  # Cache latest prices
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch current RWA price data via HTTP.
        
        Args:
            symbol: RWA symbol (e.g., "EURUSD", "GBPUSD", "GOLD")
            **kwargs: data_type ("price" | "volume" | "funding")
        
        Returns:
            Normalized data dict
        """
        data_type = kwargs.get("data_type", "price")
        
        try:
            if data_type == "price":
                # Get all latest prices from Ostium API
                raw_data = await self.api_client.get_latest_prices()
                
                if not raw_data:
                    raise ValueError(f"No data received from Ostium")
                
                # Find price for specific symbol
                # Response is LIST: [{"from": "EUR", "to": "USD", "mid": 1.15985, ...}, ...]
                symbol_data = None
                
                for item in raw_data:
                    # Construct symbol from "from" + "to"
                    item_symbol = item.get("from", "") + item.get("to", "")
                    if item_symbol == symbol:
                        symbol_data = {
                            "symbol": symbol,
                            "price": str(item.get("mid", 0)),
                            "bid": item.get("bid", 0),
                            "ask": item.get("ask", 0),
                            "timestamp": item.get("timestampSeconds", 0)
                        }
                        break
                
                if not symbol_data:
                    raise ValueError(f"Symbol {symbol} not found in Ostium response")
                
                return self.normalize(symbol_data, "price")
            
            elif data_type == "volume":
                # Ostium doesn't provide volume stats directly
                # Return placeholder
                raw_data = {"symbol": symbol, "volume24h": 0, "volumeUsd": 0}
                return self.normalize(raw_data, "volume")
            
            elif data_type == "funding":
                # Ostium doesn't provide funding rates
                # Return placeholder
                raw_data = {"symbol": symbol, "fundingRate": 0, "nextFundingTime": 0}
                return self.normalize(raw_data, "funding")
            
            else:
                raise ValueError(f"Unknown data_type: {data_type}")
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Ostium fetch error: {e}")
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to price updates via HTTP polling.
        
        Note: Ostium doesn't have WebSocket, so we use polling with 5s interval.
        
        Args:
            symbol: RWA symbol
            callback: Function to call with new data
        """
        self._callbacks.append((symbol, callback))
        
        # Start poller if not running
        if not self.poller.is_running:
            await self.poller.start()
    
    async def _handle_poll_data(self, prices: list) -> None:
        """Internal: Handle polled price data"""
        try:
            # Update cache
            # prices format: [{"from": "EUR", "to": "USD", "mid": 1.15985, ...}, ...]
            if prices and isinstance(prices, list):
                for item in prices:
                    # Construct symbol from from+to
                    symbol = item.get("from", "") + item.get("to", "")
                    if symbol:
                        price_data = {
                            "symbol": symbol,
                            "price": str(item.get("mid", 0)),
                            "bid": item.get("bid", 0),
                            "ask": item.get("ask", 0),
                            "timestamp": item.get("timestampSeconds", 0)
                        }
                        self._current_prices[symbol] = price_data
            
            # Notify subscribers
            for symbol, callback in self._callbacks:
                if symbol in self._current_prices:
                    normalized = self.normalize(self._current_prices[symbol], "price")
                    await callback(normalized)
        
        except Exception as e:
            print(f"Error handling poll data: {e}")
    
    def normalize(self, raw_data: Any, data_type: str = "price") -> Dict[str, Any]:
        """
        Normalize Ostium data to standard format.
        
        Args:
            raw_data: Raw data from Ostium API
            data_type: Type of data
        
        Returns:
            {
                "source": "ostium",
                "symbol": symbol,
                "data_type": type,
                "timestamp": int,
                "data": {...}
            }
        """
        normalized = {
            "source": "ostium",
            "data_type": data_type,
            "timestamp": raw_data.get("timestamp", 0),
            "data": {}
        }
        
        if data_type == "price":
            normalized["symbol"] = raw_data.get("symbol", "UNKNOWN")
            normalized["data"] = {
                "price": float(raw_data.get("price", 0)),
                "mark_price": float(raw_data.get("markPrice", raw_data.get("price", 0))),
                "change_24h": float(raw_data.get("change24h", 0))
            }
        
        elif data_type == "volume":
            normalized["symbol"] = raw_data.get("symbol", "UNKNOWN")
            normalized["data"] = {
                "volume_24h": float(raw_data.get("volume24h", 0)),
                "volume_usd": float(raw_data.get("volumeUsd", 0))
            }
        
        elif data_type == "funding":
            normalized["symbol"] = raw_data.get("symbol", "UNKNOWN")
            normalized["data"] = {
                "funding_rate": float(raw_data.get("fundingRate", 0)),
                "next_funding": raw_data.get("nextFundingTime", 0)
            }
        
        return normalized
    
    async def stop(self) -> None:
        """Stop the poller"""
        if self.poller.is_running:
            await self.poller.stop()
