"""
Base Connector Class

Abstract base class for all data connectors.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable, List
from enum import Enum


class ConnectorStatus(Enum):
    """Connector health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    ERROR = "error"


class BaseConnector(ABC):
    """
    Base class for all data connectors.
    
    All connectors must implement:
    - fetch(): Get data synchronously
    - subscribe(): Subscribe to real-time updates
    - normalize(): Convert raw data to standard format
    - get_status(): Health check
    
    Trading methods (for exchange connectors):
    - place_order(): Submit order to exchange
    - cancel_order(): Cancel pending order
    - get_user_positions(): Fetch user positions
    - get_user_orders(): Fetch user orders
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.status = ConnectorStatus.OFFLINE
        self._callbacks = []
    
    @abstractmethod
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch data for given symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTC-USD")
            **kwargs: Additional parameters
        
        Returns:
            Normalized data dict
        """
        pass
    
    @abstractmethod
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to real-time data updates.
        
        Args:
            symbol: Trading symbol
            callback: Function to call with new data
            **kwargs: Additional parameters
        """
        pass
    
    @abstractmethod
    def normalize(self, raw_data: Any) -> Dict[str, Any]:
        """
        Normalize raw data to standard format.
        
        Args:
            raw_data: Raw data from source
        
        Returns:
            Normalized data dict with standard fields
        """
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get connector health status.
        
        Returns:
            {
                "name": connector name,
                "status": "healthy" | "degraded" | "offline" | "error",
                "last_update": timestamp,
                "error": error message if any
            }
        """
        return {
            "name": self.name,
            "status": self.status.value,
            "config": self.config
        }
    
    async def _notify_subscribers(self, data: Dict[str, Any]) -> None:
        """Internal: Notify all subscribers with new data"""
        for callback in self._callbacks:
            try:
                await callback(data)
            except Exception as e:
                print(f"Error in callback: {e}")
    
    # ===== Trading Methods (Optional for data-only connectors) =====
    
    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,  # 'buy' | 'sell'
        order_type: str,  # 'market' | 'limit' | 'stop_limit'
        size: float,
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place order on exchange.
        
        Args:
            user_address: User's wallet address
            symbol: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', or 'stop_limit'
            size: Order size in base currency
            price: Limit price (for limit/stop_limit orders)
            stop_price: Stop trigger price (for stop_limit orders)
            **kwargs: Exchange-specific parameters
        
        Returns:
            {
                'exchange': str,
                'exchange_order_id': str,
                'status': str,
                'raw_response': dict
            }
        """
        pass
    
    async def cancel_order(
        self,
        user_address: str,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Cancel pending order.
        
        Args:
            user_address: User's wallet address
            order_id: Exchange order ID
        
        Returns:
            {'status': str, 'order_id': str}
        """
        pass
    
    async def get_user_positions(
        self,
        user_address: str
    ) -> List[Dict[str, Any]]:
        """
        Get active positions for user.
        
        Args:
            user_address: User's wallet address
        
        Returns:
            List of position dicts with fields:
            - symbol: str
            - side: 'long' | 'short'
            - size: float
            - entry_price: float
            - unrealized_pnl: float
            - liquidation_price: float
            - leverage: float
        """
        pass
    
    async def get_user_orders(
        self,
        user_address: str,
        status: str = None  # 'open' | 'filled' | 'cancelled'
    ) -> List[Dict[str, Any]]:
        """
        Get user's orders.
        
        Args:
            user_address: User's wallet address
            status: Optional status filter
        
        Returns:
            List of order dicts
        """
        pass
