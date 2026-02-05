import asyncio
import os
import sys

# Add backend and websocket to path
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_path)
sys.path.append(os.path.join(backend_path, "websocket"))

from connectors.web3_arbitrum.onchain_connector import OnchainConnector
from config import settings
from web3 import Web3

async def debug_funding(address):
    print(f"Debugging funding for {address}...")
    
    # Initialize connector
    connector = OnchainConnector(settings.dict() if hasattr(settings, 'dict') else {})
    
    # Test specific address (uses the new fallback logic internally)
    history = await connector.get_vault_transfers(address)
    
    print(f"Found {len(history)} items in history.")
    for item in history:
        print(f" - {item['type']}: {item['amount']} USDC at {item['timestamp']} (TX: {item['txHash']})")

if __name__ == "__main__":
    # Use the address identified from ALL events check
    test_address = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C" 
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(debug_funding(test_address))
