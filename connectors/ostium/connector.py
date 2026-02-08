"""
Ostium Connector

Wrapper around existing Ostium API poller.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable, List
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
        
        self.api_url = config.get("api_url") or os.getenv("OSTIUM_API_URL") or "https://metadata-backend.ostium.io"
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
        normalized_symbol = (symbol or "").upper().replace("-", "").replace("/", "")
        
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
                    if item_symbol == normalized_symbol:
                        symbol_data = {
                            "symbol": normalized_symbol,
                            "price": str(item.get("mid", 0)),
                            "bid": item.get("bid", 0),
                            "ask": item.get("ask", 0),
                            "timestamp": item.get("timestampSeconds", 0)
                        }
                        break
                
                if not symbol_data:
                    raise ValueError(f"Symbol {normalized_symbol} not found in Ostium response")
                
                return self.normalize(symbol_data, "price")
            
            elif data_type == "volume":
                # Ostium doesn't provide volume stats directly
                # Return placeholder
                raw_data = {"symbol": symbol, "volume24h": 0, "volumeUsd": 0}
                return self.normalize(raw_data, "volume")
            
            elif data_type == "funding":
                # Ostium doesn't provide funding rates
                # Return placeholder
                raw_data = {"symbol": normalized_symbol, "fundingRate": 0, "nextFundingTime": 0}
                return self.normalize(raw_data, "funding")
            
            elif data_type == "candles":
                # Ostium connector currently has no candles API in this adapter.
                return {
                    "source": "ostium",
                    "symbol": normalized_symbol,
                    "data_type": "candles",
                    "timestamp": 0,
                    "data": [],
                    "error": "Candle data is not available from Ostium connector yet.",
                }
            
            else:
                raise ValueError(f"Unknown data_type: {data_type}")
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Ostium fetch error: {e}")

    async def fetch_all_markets(self) -> List[Dict[str, Any]]:
        """
        Fetch data for ALL Ostium markets, enriched with Subgraph volume.
        """
        try:
            # 1. Fetch latest prices from Metadata API
            raw_data = await self.api_client.get_latest_prices()
            if not raw_data:
                return []
            
            # 2. Fetch Volume/OI from Subgraph
            subgraph_data = {}
            try:
                from Ostium.subgraph_client import OstiumSubgraphClient
                subgraph = OstiumSubgraphClient()
                pairs = await subgraph.get_formatted_pairs_details()
                subgraph_data = {p['symbol']: p for p in pairs}
            except Exception as e:
                print(f"Warning: Could not fetch Subgraph data for enrichment: {e}")

            markets = []
            for item in raw_data:
                # Construct symbol
                symbol = item.get("from", "") + "-" + item.get("to", "")
                
                # Determine Category
                category = "Stocks" 
                s = symbol.upper().replace("-", "") 
                
                # Crypto - Filter OUT
                crypto_skips = ['ADAUSD', 'BNBUSD', 'BTCUSD', 'ETHUSD', 'LINKUSD', 'SOLUSD', 'TRXUSD', 'XRPUSD', 'HYPEUSD', 'GLXYUSD', 'BMNRUSD', 'CRCLUSD', 'SBETUSD']
                if s in crypto_skips:
                    continue
                    
                # Forex
                forex_pairs = ['AUDUSD', 'EURUSD', 'GBPUSD', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'USDMXN']
                if s in forex_pairs:
                    category = "Forex"
                elif s in ['CLUSD', 'HGUSD', 'XAGUSD', 'XAUUSD', 'XPDUSD', 'XPTUSD']:
                    category = "Commodities"
                elif s in ['DAXEUR', 'DJIUSD', 'FTSEGBP', 'HSIHKD', 'NDXUSD', 'NIKJPY', 'SPXUSD']:
                    category = "index"
                
                # Get volume from Subgraph data
                stats = subgraph_data.get(symbol, {})
                volume = stats.get("totalOI", 0)
                utilization = stats.get("utilization", 0)
                
                markets.append({
                    "symbol": symbol,
                    "price": float(item.get("mid", 0)),
                    "change_24h": 0, # To be filled by real-time history or API if available
                    "change_percent_24h": 0,
                    "volume_24h": float(volume),
                    "openInterest": float(volume),
                    "utilization": float(utilization),
                    "high_24h": 0,
                    "low_24h": 0,
                    "source": "ostium",
                    "category": category
                })
            
            return markets
            
        except Exception as e:
            print(f"Ostium fetch_all error: {e}")
            return []
    
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

    # ===== Trading Methods (Stubs - Smart Contract Integration Required) =====
    
    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place order on Ostium (stub).
        
        Ostium requires smart contract interaction for order placement.
        This method is a placeholder for future implementation.
        
        TODO: Implement with smart contract integration
        - Requires Web3.py
        - Needs Ostium orderbook contract ABI
        - Session key signing for user transactions
        """
        raise NotImplementedError(
            "Ostium order placement requires smart contract integration. "
            "Use backend/connectors/ostium/contracts/ for implementation."
        )
    
    async def cancel_order(
        self,
        user_address: str,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Cancel order on Ostium (stub).
        
        TODO: Implement via smart contract
        """
        raise NotImplementedError(
            "Ostium order cancellation requires smart contract integration."
        )
    
    async def get_user_positions(
        self,
        user_address: str
    ) -> List[Dict[str, Any]]:
        """
        Get user positions from Ostium (stub).
        
        TODO: Query Ostium subgraph or contracts for user positions
        """
        raise NotImplementedError(
            "Ostium position query requires subgraph or contract integration. "
            "Consider using The Graph API or direct contract calls."
        )
    
    async def get_user_orders(
        self,
        user_address: str,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get user orders from Ostium (stub).
        
        TODO: Query Ost ium subgraph for user order history
        """
        raise NotImplementedError(
            "Ostium order history requires subgraph integration."
        )

