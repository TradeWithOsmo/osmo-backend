"""
Integration Test Script for Data Connectors

Test all connectors independently and verify data formats.
"""

import asyncio
import os
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../websocket/.env'))

# Override Redis URL based on environment
if os.path.exists('/.dockerenv'):
    # Running inside Docker
    os.environ['REDIS_URL'] = 'redis://osmo-redis:6379/0'
else:
    # Running locally
    os.environ['REDIS_URL'] = 'redis://localhost:6379/0'

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from connectors.init_connectors import connector_registry
from connectors.manager import DataCategory, AssetType
from connectors.data.market import get_current_price


async def test_hyperliquid():
    """Test Hyperliquid connector"""
    print("\n=== Testing Hyperliquid Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("hyperliquid")
        if not connector:
            print("✗ Hyperliquid connector not registered")
            return False
        
        # Test fetch
        result = await connector.fetch("BTC", data_type="price")
        print(f"✓ Price fetch: BTC = ${result['data']['price']}")
        print(f"  Source: {result['source']}")
        print(f"  Data type: {result['data_type']}")
        
        return True
    except Exception as e:
        print(f"✗ Hyperliquid test failed: {e}")
        return False


async def test_ostium():
    """Test Ostium connector"""
    print("\n=== Testing Ostium Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("ostium")
        if not connector:
            print("✗ Ostium connector not registered")
            return False
        
        # Test fetch with EURUSD (a valid Ostium symbol)
        result = await connector.fetch("EURUSD", data_type="price")
        print(f"✓ Price fetch: EURUSD = ${result['data']['price']}")
        print(f"  Source: {result['source']}")
        
        return True
    except Exception as e:
        print(f"✗ Ostium test failed: {e}")
        return False


async def test_chainlink():
    """Test Chainlink connector"""
    print("\n=== Testing Chainlink Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("chainlink")
        if not connector:
            print("✗ Chainlink connector not registered")
            return False
        
        # Test fetch
        result = await connector.fetch("BTC-USD")
        print(f"✓ Oracle price: BTC = ${result['data']['price']}")
        print(f"  Updated at: {result['timestamp']}")
        print(f"  Decimals: {result['data']['decimals']}")
        
        return True
    except Exception as e:
        print(f"✗ Chainlink test failed: {e}")
        return False


async def test_tradingview():
    """Test TradingView connector"""
    print("\n=== Testing TradingView Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("tradingview")
        if not connector:
            print("✗ TradingView connector not registered")
            return False
        
        # Store test indicators
        test_data = {
            "symbol": "BTC",
            "timeframe": "1H",
            "indicators": {
                "RSI_14": 42.5,
                "MACD_signal": 0.15,
                "EMA_9": 43200
            },
            "timestamp": 1705417200
        }
        
        result = await connector.store_indicators(test_data)
        print(f"✓ Indicators stored: {result['indicator_count']} indicators")
        
        # Fetch stored indicators
        fetched = await connector.fetch("BTC", timeframe="1H")
        print(f"✓ Indicators retrieved: {len(fetched['data']['indicators'])} indicators")
        
        return True
    except Exception as e:
        print(f"✗ TradingView test failed: {e}")
        return False


async def test_web_search():
    """Test Web Search connector"""
    print("\n=== Testing Web Search Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("web_search")
        if not connector:
            print("✗ Web Search connector not registered")
            return False
        
        # Check status
        status = connector.get_status()
        if status['status'] == 'offline':
            print("⚠ Web Search connector offline (OPENROUTER_API_KEY not configured)")
            return True
        
        print(f"✓ Web Search connector configured")
        print(f"  Status: {status['status']}")
        
        return True
    except Exception as e:
        print(f"✗ Web Search test failed: {e}")
        return False


async def test_dune():
    """Test Dune Analytics connector"""
    print("\n=== Testing Dune Analytics Connector ===")
    
    try:
        connector = connector_registry.manager.get_connector("dune")
        if not connector:
            print("✗ Dune connector not registered")
            return False
        
        # Check status
        status = connector.get_status()
        print(f"✓ Dune connector configured")
        print(f"  API key: {'✓' if status['api_key_configured'] else '✗'}")
        print(f"  Query ID: {status['whale_query_id']}")
        
        return True
    except Exception as e:
        print(f"✗ Dune test failed: {e}")
        return False


async def test_routing():
    """Test manager routing logic"""
    print("\n=== Testing Manager Routing ===")
    
    try:
        manager = connector_registry.manager
        
        # Test crypto routing
        btc_data = await manager.fetch_data(
            category=DataCategory.MARKET,
            symbol="BTC",
            asset_type=AssetType.CRYPTO,
            use_cache=False,
            data_type="price"
        )
        print(f"✓ Crypto routing: BTC routed to {btc_data['source']}")
        
        # Test RWA routing with EURUSD (valid Ostium symbol)
        eur_data = await manager.fetch_data(
            category=DataCategory.MARKET,
            symbol="EURUSD",
            asset_type=AssetType.RWA,
            use_cache=False,
            data_type="price"
        )
        print(f"✓ RWA routing: EURUSD routed to {eur_data['source']}")
        
        return True
    except Exception as e:
        print(f"✗ Routing test failed: {e}")
        return False


async def test_connector_status():
    """Test all connector statuses"""
    print("\n=== Connector Status Overview ===")
    
    try:
        statuses = connector_registry.manager.get_all_statuses()
        
        for name, status in statuses.items():
            symbol = "✓" if status['status'] == 'healthy' else "⚠"
            print(f"{symbol} {name}: {status['status']}")
        
        return True
    except Exception as e:
        print(f"✗ Status check failed: {e}")
        return False


async def main():
    """Run all tests"""
    print("=" * 60)
    print("OSMO DATA CONNECTORS - INTEGRATION TEST")
    print("=" * 60)
    
    # Initialize connectors
    print("\nInitializing connector system...")
    await connector_registry.initialize()
    
    # Run tests
    tests = [
        ("Hyperliquid", test_hyperliquid),
        ("Ostium", test_ostium),
        ("Chainlink", test_chainlink),
        ("TradingView", test_tradingview),
        ("Web Search", test_web_search),
        ("Dune Analytics", test_dune),
        ("Routing Logic", test_routing),
        ("Status Check", test_connector_status)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    # Cleanup
    print("\nShutting down...")
    await connector_registry.shutdown()
    
    print("✓ Test complete")


if __name__ == "__main__":
    asyncio.run(main())
