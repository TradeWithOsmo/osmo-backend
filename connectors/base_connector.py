"""
Base Connector Class

Abstract base class for all data connectors.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
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
