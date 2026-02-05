import asyncio
import json
import os
import sys
from web3 import Web3
from eth_account import Account

# Setup paths
sys.path.append('/app')

async def main():
    print("Starting debug script...")
    
    # 1. Setup Connector
    try:
        from config import settings
        from connectors.web3_arbitrum.connector import web3_connector
        from connectors.web3_arbitrum.session_manager import session_manager
        from connectors.web3_arbitrum.onchain_connector import OnchainConnector
    except ImportError as e:
        print(f"Import error: {e}")
        return
    
    user_address = "0xC65870884989F6748aF9822f17b2758A48d97B79"
    symbol = "BTC-USD"
    
    # Get session key
    print(f"Fetching session key for {user_address}...")
    session_key = await session_manager.get_session_key(user_address)
    if not session_key:
        print("No session key found!")
        return
    print(f"Session key found (starts with {session_key[:6]}...)")

    connector = OnchainConnector({})
    
    print("Calling place_order...")
    try:
        res = await connector.place_order(
            user_address=user_address,
            symbol=symbol,
            side='buy',
            order_type='market',
            size=10.1, # Use non-round to be sure
            leverage=10
        )
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error during place_order: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
