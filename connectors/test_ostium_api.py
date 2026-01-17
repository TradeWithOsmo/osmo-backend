"""
Direct test of Ostium connector without integration framework
"""

import asyncio
import sys
import os

# Add parent to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from connectors.ostium import OstiumConnector

async def test_direct():
    print("=== Direct Ostium Connector Test ===\n")
    
    config = {
        "api_url": "https://metadata-backend.ostium.io",
        "poll_interval": 5
    }
    
    connector = OstiumConnector(config)
    
    try:
        # Test EURUSD (we know this exists from API response)
        print("Testing EURUSD...")
        result = await connector.fetch("EURUSD", data_type="price")
        print(f"✓ EURUSD = ${result['data']['price']}")
        print(f"  Source: {result['source']}")
        print(f"  Timestamp: {result['timestamp']}")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_direct())
    print(f"\nResult: {'✓ SUCCESS' if success else '✗ FAILED'}")
