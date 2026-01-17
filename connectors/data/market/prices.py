"""
Market Data - Price Module

Unified price data interface across all sources.
"""

from typing import Dict, Any, Optional


async def get_current_price(
    manager,
    symbol: str,
    asset_type: str = "crypto"
) -> Dict[str, Any]:
    """
    Get current price for symbol from appropriate source.
    
    Args:
        manager: ConnectorManager instance
        symbol: Trading symbol (e.g., "BTC" for crypto, "GOLD" for RWA)
        asset_type: "crypto" or "rwa"
    
    Returns:
        {
            "symbol": str,
            "price": float,
            "mark_price": float,
            "index_price": float,  # Crypto only
            "source": str,
            "timestamp": int
        }
    """
    from ...manager import DataCategory, AssetType
    
    asset_enum = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
    
    result = await manager.fetch_data(
        category=DataCategory.MARKET,
        symbol=symbol,
        asset_type=asset_enum,
        data_type="price"
    )
    
    return {
        "symbol": result.get("symbol", symbol),
        "price": result["data"].get("price", 0),
        "mark_price": result["data"].get("mark_price", 0),
        "index_price": result["data"].get("index_price"),  # None for RWA
        "source": result.get("source"),
        "timestamp": result.get("timestamp")
    }


async def subscribe_to_price_updates(
    manager,
    symbol: str,
    callback,
    asset_type: str = "crypto"
) -> None:
    """
    Subscribe to real-time price updates.
    
    Args:
        manager: ConnectorManager instance
        symbol: Trading symbol
        callback: Async function to call with price updates
        asset_type: "crypto" or "rwa"
    """
    from ...manager import AssetType
    
    asset_enum = AssetType.CRYPTO if asset_type == "crypto" else AssetType.RWA
    connector_id = "hyperliquid" if asset_enum == AssetType.CRYPTO else "ostium"
    
    connector = manager.get_connector(connector_id)
    if connector:
        await connector.subscribe(
            symbol,
            callback,
            subscription_type="allMids" if asset_enum == AssetType.CRYPTO else "polling"
        )
