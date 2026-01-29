"""
Connector Manager

Centralized manager to route requests to appropriate connectors.
"""

from typing import Dict, Any, Optional, List
from enum import Enum
import asyncio


class DataCategory(Enum):
    """Data categories"""
    MARKET = "market"
    INDICATORS = "indicators"
    USER = "user"
    ANALYTICS = "analytics"
    CANDLES = "candles"
    MEMORY = "memory"
    WEB_SEARCH = "web_search"


class AssetType(Enum):
    """Asset types for routing"""
    CRYPTO = "crypto"  # Route to Hyperliquid
    RWA = "rwa"        # Route to Ostium


class ConnectorManager:
    """
    Centralized manager for all connectors.
    
    Responsibilities:
    - Route requests to appropriate connector
    - Handle fallback (Chainlink if primary fails)
    - Manage cache (Redis)
    - Aggregate data from multiple sources
    """
    
    def __init__(self, redis_client=None):
        self.connectors = {}
        self.redis = redis_client
        self.cache_ttl = 10  # Default 10 seconds
    
    def register_connector(self, connector_id: str, connector):
        """Register a connector"""
        self.connectors[connector_id] = connector
        print(f"Registered connector: {connector_id}")
    
    def get_connector(self, connector_id: str):
        """Get connector by ID"""
        return self.connectors.get(connector_id)
    
    async def fetch_data(
        self,
        category: DataCategory,
        symbol: str,
        asset_type: AssetType = AssetType.CRYPTO,
        use_cache: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Fetch data from appropriate connector.
        
        Args:
            category: Data category (market, indicators, etc.)
            symbol: Trading symbol
            asset_type: Crypto or RWA
            use_cache: Whether to use Redis cache
            **kwargs: Additional parameters
        
        Returns:
            Normalized data dict
        """
        # Check cache first
        if use_cache and self.redis:
            cache_key = f"{category.value}:{symbol}"
            cached_data = await self._get_from_cache(cache_key)
            if cached_data:
                return cached_data
        
        # Route to appropriate connector
        connector_id = self._route_connector(category, asset_type)
        connector = self.get_connector(connector_id)
        
        if not connector:
            raise ValueError(f"Connector not found: {connector_id}")
        
        # Fetch data
        try:
            data = await connector.fetch(symbol, **kwargs)
            
            # Cache the result
            if use_cache and self.redis:
                await self._set_cache(cache_key, data, self.cache_ttl)
            
            return data
        
        except Exception as e:
            print(f"Error fetching from {connector_id}: {e}")
            
            # Fallback to Chainlink for price data
            if category == DataCategory.MARKET and "chainlink" in self.connectors:
                print(f"Falling back to Chainlink for {symbol}")
                fallback = self.connectors["chainlink"]
                return await fallback.fetch(symbol, **kwargs)
            
            raise

    async def fetch_all_markets(self, asset_type: AssetType = AssetType.CRYPTO) -> List[Dict[str, Any]]:
        """
        Fetch ALL markets for a given asset type (Crypto/RWA).
        """
        connector_id = "hyperliquid" if asset_type == AssetType.CRYPTO else "ostium"
        connector = self.get_connector(connector_id)
        
        if not connector:
            print(f"Connector not found for fetch_all: {connector_id}")
            return []

        try:
            if hasattr(connector, 'fetch_all_markets'):
                return await connector.fetch_all_markets()
            else:
                print(f"Connector {connector_id} does not support fetch_all_markets")
                return []
        except Exception as e:
            print(f"Error in fetch_all_markets ({connector_id}): {e}")
            return []
    
    def _route_connector(
        self,
        category: DataCategory,
        asset_type: AssetType
    ) -> str:
        """
        Route request to appropriate connector.
        
        Routing logic:
        - Crypto market data → Hyperliquid
        - RWA market data → Ostium
        - Indicators → TradingView (if available) or calculation
        - Analytics → Dune (for whales) or Hyperliquid
        - Memory → mem0
        - Web search → Grok 2 / Perplexity
        """
        if category == DataCategory.MEMORY:
            return "memory"
        
        if category == DataCategory.WEB_SEARCH:
            return "web_search"
        
        if category == DataCategory.INDICATORS:
            return "tradingview"  # Primary source
        
        if category == DataCategory.ANALYTICS:
            return "dune"  # Whale tracking
        
        # Market data routing based on asset type
        if category in [DataCategory.MARKET, DataCategory.CANDLES]:
            return "hyperliquid" if asset_type == AssetType.CRYPTO else "ostium"
        
        # Default to Hyperliquid
        return "hyperliquid"
    
    async def aggregate_data(
        self,
        sources: List[str],
        symbol: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Aggregate data from multiple connectors.
        
        Args:
            sources: List of connector IDs
            symbol: Trading symbol
            **kwargs: Additional parameters
        
        Returns:
            Combined data dict
        """
        tasks = []
        for source_id in sources:
            connector = self.get_connector(source_id)
            if connector:
                tasks.append(connector.fetch(symbol, **kwargs))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine results
        combined = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Error from {sources[i]}: {result}")
                continue
            combined[sources[i]] = result
        
        return combined
    
    async def _get_from_cache(self, key: str) -> Optional[Dict]:
        """Get data from Redis cache"""
        if not self.redis:
            return None
        
        try:
            import json
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"Cache read error: {e}")
        
        return None
    
    async def _set_cache(
        self,
        key: str,
        data: Dict,
        ttl: int
    ) -> None:
        """Set data in Redis cache"""
        if not self.redis:
            return
        
        try:
            import json
            await self.redis.setex(
                key,
                ttl,
                json.dumps(data)
            )
        except Exception as e:
            print(f"Cache write error: {e}")
    
    def get_all_statuses(self) -> Dict[str, Any]:
        """Get status of all connectors"""
        statuses = {}
        for connector_id, connector in self.connectors.items():
            statuses[connector_id] = connector.get_status()
        return statuses
