"""
Connector Initialization and Lifecycle Management

Initialize all connectors and integrate with FastAPI app.
"""

import os
import logging
from typing import Dict, Any
import redis.asyncio as redis


from connectors.manager import ConnectorManager
# Imports moved inside valid registration methods to prevent global crash



logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """
    Global connector registry for the application.
    
    Manages lifecycle of all connectors and provides centralized access.
    """
    
    def __init__(self):
        self.manager: ConnectorManager = None
        self.redis_client: redis.Redis = None
        self._initialized = False
    
    async def initialize(self, redis_url: str = None) -> None:
        """
        Initialize all connectors.
        
        Args:
            redis_url: Redis connection URL (default from env)
        """
        if self._initialized:
            logger.warning("Connectors already initialized")
            return
        
        logger.info("Initializing connector registry...")
        
        # Initialize Redis
        redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            self.redis_client = await redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("✓ Redis connected")
        except Exception as e:
            logger.error(f"✗ Redis connection failed: {e}")
            self.redis_client = None
        
        # Initialize connector manager
        self.manager = ConnectorManager(redis_client=self.redis_client)
        
        # Register all connectors
        await self._register_hyperliquid()
        await self._register_ostium()
        await self._register_chainlink()
        await self._register_dune()
        await self._register_tradingview()
        await self._register_web_search()
        await self._register_mem0()
        await self._register_qdrant()
        
        self._initialized = True
        logger.info("✓ All connectors initialized")
    
    async def _register_hyperliquid(self) -> None:
        """Register Hyperliquid connector"""
        try:
            config = {
                "ws_url": os.getenv("HYPERLIQUID_WS_URL", "wss://api.hyperliquid.xyz"),
                "http_url": os.getenv("HYPERLIQUID_HTTP_URL", "https://api.hyperliquid.xyz")
            }
            
            from connectors.hyperliquid import HyperliquidConnector
            connector = HyperliquidConnector(config)
            self.manager.register_connector("hyperliquid", connector)
            
            logger.info("✓ Hyperliquid connector registered")
        except Exception as e:
            logger.error(f"✗ Hyperliquid registration failed: {e}")
    
    async def _register_ostium(self) -> None:
        """Register Ostium connector"""
        try:
            config = {
                "api_url": os.getenv("OSTIUM_API_URL", "https://metadata-backend.ostium.io"),
                "poll_interval": int(os.getenv("OSTIUM_POLL_INTERVAL", "5"))
            }
            
            from connectors.ostium import OstiumConnector
            connector = OstiumConnector(config)
            self.manager.register_connector("ostium", connector)
            
            logger.info("✓ Ostium connector registered")
        except Exception as e:
            logger.error(f"✗ Ostium registration failed: {e}")
    
    async def _register_chainlink(self) -> None:
        """Register Chainlink connector"""
        try:
            config = {
                "rpc_url": os.getenv("CHAINLINK_RPC_URL", "https://arb1.arbitrum.io/rpc"),
                "backup_rpc": os.getenv("CHAINLINK_BACKUP_RPC", "https://arbitrum.llamarpc.com")
            }
            
            from connectors.chainlink import ChainlinkConnector
            connector = ChainlinkConnector(config)
            self.manager.register_connector("chainlink", connector)
            
            logger.info("✓ Chainlink connector registered")
        except Exception as e:
            logger.error(f"✗ Chainlink registration failed: {e}")
    
    async def _register_dune(self) -> None:
        """Register Dune Analytics connector"""
        try:
            config = {
                "api_key": os.getenv("DUNE_API_KEY"),
                "whale_query_id": os.getenv("DUNE_QUERY_WHALE_TRADES")
            }
            
            if not config["api_key"]:
                logger.warning("⚠ DUNE_API_KEY not configured, connector offline")
            
            from connectors.dune import DuneConnector
            connector = DuneConnector(config)
            self.manager.register_connector("dune", connector)
            
            logger.info("✓ Dune Analytics connector registered")
        except Exception as e:
            logger.error(f"✗ Dune registration failed: {e}")
    
    async def _register_tradingview(self) -> None:
        """Register TradingView connector"""
        try:
            config = {
                "redis_client": self.redis_client,
                "cache_ttl": int(os.getenv("TRADINGVIEW_CACHE_TTL", "60"))
            }
            
            from connectors.tradingview import TradingViewConnector
            connector = TradingViewConnector(config)
            self.manager.register_connector("tradingview", connector)
            
            logger.info("✓ TradingView connector registered")
        except Exception as e:
            logger.error(f"✗ TradingView registration failed: {e}")
    
    async def _register_web_search(self) -> None:
        """Register Web Search connector"""
        try:
            config = {
                "openrouter_key": os.getenv("OPENROUTER_API_KEY")
            }
            
            if not config["openrouter_key"]:
                logger.warning("⚠ OPENROUTER_API_KEY not configured, connector offline")
            
            from connectors.web_search import WebSearchConnector
            connector = WebSearchConnector(config)
            self.manager.register_connector("web_search", connector)
            
            logger.info("✓ Web Search connector registered")
        except Exception as e:
            logger.error(f"✗ Web Search registration failed: {e}")
    
    async def _register_mem0(self) -> None:
        """Register mem0 Memory connector (self-hosted)"""
        try:
            config = {
                "enabled": os.getenv("MEM0_ENABLED", "false").lower() == "true",
                "openai_api_key": os.getenv("OPENAI_API_KEY")
            }
            
            if config["enabled"] and not config["openai_api_key"]:
                logger.warning("⚠ MEM0_ENABLED but OPENAI_API_KEY not configured")
            
            from connectors.mem0 import Mem0Connector
            connector = Mem0Connector(config)
            self.manager.register_connector("mem0", connector)
            
            logger.info(f"✓ mem0 connector registered ({'enabled' if config['enabled'] else 'disabled'})")
        except Exception as e:
            logger.error(f"✗ mem0 registration failed: {e}")

    async def _register_qdrant(self) -> None:
        """Register Qdrant connector (Knowledge Base)"""
        try:
            config = {
                "enabled": os.getenv("QDRANT_ENABLED", "false").lower() == "true",
                "host": os.getenv("QDRANT_HOST", "memory"),
                "port": int(os.getenv("QDRANT_PORT", "6333")),
                "collection_name": os.getenv("QDRANT_KB_COLLECTION", "osmo_knowledge_base")
            }
            
            from connectors.qdrant import QdrantConnector
            connector = QdrantConnector(config)
            self.manager.register_connector("qdrant", connector)
            
            logger.info(f"✓ Qdrant connector registered ({'enabled' if config['enabled'] else 'disabled'})")
        except Exception as e:
            logger.error(f"✗ Qdrant registration failed: {e}")
    
    async def shutdown(self) -> None:
        """Cleanup all connectors"""
        if not self._initialized:
            return
        
        logger.info("Shutting down connectors...")
        
        # Stop Ostium poller
        try:
            ostium = self.manager.get_connector("ostium")
            if ostium and hasattr(ostium, 'stop'):
                await ostium.stop()
        except Exception as e:
            logger.error(f"Error stopping Ostium: {e}")
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        self._initialized = False
        logger.info("✓ Connectors shut down")
    
    def get_manager(self) -> ConnectorManager:
        """Get the connector manager instance"""
        if not self._initialized:
            raise RuntimeError("Connectors not initialized. Call initialize() first.")
        return self.manager


# Global registry instance
connector_registry = ConnectorRegistry()


# Dependency for FastAPI
def get_connector_manager() -> ConnectorManager:
    """FastAPI dependency to get connector manager"""
    return connector_registry.get_manager()
