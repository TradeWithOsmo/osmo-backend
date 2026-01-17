"""
Example Usage: Osmo Data Connectors

This demonstrates how to use the connector system.
"""

import asyncio
from connectors.manager import ConnectorManager, DataCategory, AssetType
from connectors.hyperliquid import HyperliquidConnector
from connectors.ostium import OstiumConnector
from connectors.data.market import get_current_price
from connectors.data.indicators import get_indicators


async def example_basic_usage():
    """Basic usage: Get current price"""
    
    # Initialize manager
    manager = ConnectorManager()
    
    # Register connectors
    hl_connector = HyperliquidConnector({
        "ws_url": "wss://api.hyperliquid.xyz",
        "http_url": "https://api.hyperliquid.xyz"
    })
    manager.register_connector("hyperliquid", hl_connector)
    
    ostium_connector = OstiumConnector({
        "api_url": "https://api.ostium.io",
        "poll_interval": 5
    })
    manager.register_connector("ostium", ostium_connector)
    
    # Get crypto price (routed to Hyperliquid)
    btc_price = await get_current_price(manager, "BTC", asset_type="crypto")
    print(f"BTC Price: ${btc_price['price']}")
    
    # Get RWA price (routed to Ostium)
    gold_price = await get_current_price(manager, "GOLD", asset_type="rwa")
    print(f"GOLD Price: ${gold_price['price']}")


async def example_realtime_subscription():
    """Subscribe to real-time price updates"""
    
    manager = ConnectorManager()
    
    hl_connector = HyperliquidConnector({"ws_url": "wss://api.hyperliquid.xyz"})
    manager.register_connector("hyperliquid", hl_connector)
    
    # Define callback
    async def on_price_update(data):
        print(f"Price Update: {data['symbol']} = ${data['data']['price']}")
    
    # Subscribe
    connector = manager.get_connector("hyperliquid")
    await connector.subscribe("BTC", on_price_update, subscription_type="allMids")
    
    # Keep running
    await asyncio.sleep(60)


async def example_multi_source_aggregation():
    """Aggregate data from multiple sources"""
    
    manager = ConnectorManager()
    
    # Register all connectors
    manager.register_connector("hyperliquid", HyperliquidConnector({}))
    manager.register_connector("ostium", OstiumConnector({}))
    
    # Aggregate BTC data from both sources (if available)
    combined = await manager.aggregate_data(
        sources=["hyperliquid", "ostium"],
        symbol="BTC"
    )
    
    print(f"Hyperliquid: {combined.get('hyperliquid')}")
    print(f"Ostium: {combined.get('ostium')}")


async def example_with_indicators():
    """Using TradingView indicators"""
    
    import redis.asyncio as redis
    
    # Assume indicators are sent from frontend to Redis
    redis_client = await redis.from_url("redis://localhost")
    
    # Get cached indicators
    indicators = await get_indicators(redis_client, "BTC", "1H")
    
    if indicators:
        print(f"RSI: {indicators['indicators']['RSI_14']}")
        print(f"MACD: {indicators['indicators']['MACD_signal']}")
    else:
        print("No indicators cached - frontend needs to send data")


if __name__ == "__main__":
    # Run example
    print("=== Osmo Data Connectors Example ===\n")
    
    # Choose one to run:
    asyncio.run(example_basic_usage())
    # asyncio.run(example_realtime_subscription())
    # asyncio.run(example_multi_source_aggregation())
    # asyncio.run(example_with_indicators())
