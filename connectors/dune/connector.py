"""
Dune Analytics Connector

On-chain data query for whale tracking and historical analytics.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable
import os
import asyncio

class DuneConnector(BaseConnector):
    """
    Dune Analytics connector for on-chain data.
    
    Purpose:
    - RWA whale tracking (Ostium trades >$100k)
    - Historical trading analytics
    - Volume trends and user behavior
    - Custom SQL queries
    
    Cost: $99/month (Plus plan)
    Data delay: 10-30 seconds (on-chain indexing)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("dune", config)
        
        self.api_key = config.get("api_key", os.getenv("DUNE_API_KEY"))
        self.whale_query_id = config.get(
            "whale_query_id",
            os.getenv("DUNE_QUERY_WHALE_TRADES", "")
        )
        
        if self.api_key:
            try:
                from dune_client.client import DuneClient
                self.client = DuneClient(self.api_key)
                self.status = ConnectorStatus.HEALTHY
            except ImportError:
                print("dune-client not installed. Run: pip install dune-client")
                self.status = ConnectorStatus.OFFLINE
        else:
            self.status = ConnectorStatus.OFFLINE
            print("DUNE_API_KEY not configured in .env")
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch whale trades for symbol from Dune.
        
        Args:
            symbol: Trading symbol (e.g., "GOLD", "EURUSD" for RWA)
            **kwargs: 
                - min_size_usd: Minimum trade size (default 100000)
                - hours: Lookback period in hours (default 24)
        
        Returns:
            Normalized whale trade data
        """
        min_size = kwargs.get("min_size_usd", 100000)
        hours = kwargs.get("hours", 24)
        
        try:
            # Execute Dune query
            query_result = await self._execute_query(
                self.whale_query_id,
                {
                    "symbol": symbol,
                    "min_size": min_size,
                    "hours": hours
                }
            )
            
            return self.normalize(query_result, symbol)
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Dune query error: {e}")
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Dune doesn't support real-time subscriptions.
        
        Use polling for periodic updates.
        """
        raise NotImplementedError(
            "Dune Analytics doesn't support subscriptions. Use polling."
        )
    
    async def _execute_query(
        self,
        query_id: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute Dune query with parameters.
        
        Args:
            query_id: Dune query ID
            params: Query parameters
        
        Returns:
            Query results
        """
        # Run query in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        
        def _run_query():
            from dune_client.types import QueryParameter
            
            # Convert params to Dune format
            query_params = [
                QueryParameter.text_type(name=k, value=str(v))
                for k, v in params.items()
            ]
            
            # Execute query
            result = self.client.run_query(
                query_id=int(query_id),
                parameters=query_params
            )
            
            return result.result.rows if result.result else []
        
        result = await loop.run_in_executor(None, _run_query)
        return result
    
    def normalize(self, raw_data: Any, symbol: str = None) -> Dict[str, Any]:
        """
        Normalize Dune data to standard format.
        
        Args:
            raw_data: Query results from Dune
            symbol: Trading symbol
        
        Returns:
            {
                "source": "dune",
                "symbol": symbol,
                "data_type": "whale_trades",
                "timestamp": int,
                "data": {
                    "trades": [...],
                    "total_volume": float,
                    "trade_count": int
                }
            }
        """
        trades = raw_data if isinstance(raw_data, list) else []
        
        total_volume = sum(float(t.get("size_usd", 0)) for t in trades)
        
        return {
            "source": "dune",
            "symbol": symbol or "UNKNOWN",
            "data_type": "whale_trades",
            "timestamp": None,  # Dune doesn't provide query timestamp
            "data": {
                "trades": trades,
                "total_volume": total_volume,
                "trade_count": len(trades)
            }
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get connector health status"""
        status = super().get_status()
        status["api_key_configured"] = bool(self.api_key)
        status["whale_query_id"] = self.whale_query_id
        return status
