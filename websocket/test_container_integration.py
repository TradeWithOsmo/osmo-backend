import asyncio
import os
import json
from web3 import Web3
from pathlib import Path

# In container, we can import from config
import sys
sys.path.append("/app")
from config import settings
from connectors.web3_arbitrum.connector import web3_connector

USER_ADDRESS = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"

async def test_backend_detection():
    print(f"--- Backend Integration Demo ---")
    print(f"PM Address: {settings.POSITION_MANAGER_ADDRESS}")
    
    pm = web3_connector.get_contract("PositionManager")
    
    print(f"Fetching positions for {USER_ADDRESS}...")
    try:
        raw_positions = pm.functions.getUserPositions(Web3.to_checksum_address(USER_ADDRESS)).call()
        print(f"Successfully connected to contract and found {len(raw_positions)} positions.")
        
        for i, p in enumerate(raw_positions):
            symbol = p[2]
            isOpen = p[9]
            print(f"Pos {i}: {symbol}, Open: {isOpen}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_backend_detection())
