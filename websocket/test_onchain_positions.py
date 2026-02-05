import asyncio
import os
import json
import time
from web3 import Web3
from pathlib import Path

# Setup Web3
RPC_URL = "https://lb.drpc.live/arbitrum-sepolia/Ap-mSigiUE5YpeoVD1OiMP2Wh_Av-QMR8JYggtEkfQq9"
PM_ADDRESS = "0x1bc416d400c75662ce5899e0387ffb9ae5658ffa"
USER_ADDRESS = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def load_abi(name):
    path = Path(f"d:/WorkingSpace/backend/contracts/abis/{name}.json")
    with open(path) as f:
        data = json.load(f)
        return data.get("abi", data)

async def test_tracking():
    print(f"--- On-Chain Position Tracking Demo ---")
    print(f"Connected: {w3.is_connected()}")
    
    pm_abi = load_abi("PositionManager")
    pm = w3.eth.contract(address=Web3.to_checksum_address(PM_ADDRESS), abi=pm_abi)
    
    # 1. Fetch Positions
    print(f"\n1. Fetching positions for {USER_ADDRESS}...")
    try:
        raw_positions = pm.functions.getUserPositions(Web3.to_checksum_address(USER_ADDRESS)).call()
        print(f"Found {len(raw_positions)} positions.")
        
        for i, p in enumerate(raw_positions):
            # p structure: [id, user, symbol, side, size, entryPrice, leverage, margin, openTimestamp, isOpen]
            pos_id = p[0].hex()
            symbol = p[2]
            side = "BUY" if p[3] == 0 else "SELL"
            size_usd = p[4] / 1e6
            entry_price = p[5] / 1e18
            leverage = p[6]
            margin = p[7] / 1e6
            is_open = p[9]
            
            print(f"\n[Position {i}] {symbol} {side}")
            print(f"  ID: {pos_id[:10]}...")
            print(f"  Size: ${size_usd:.2f} (Leverage: {leverage}x)")
            print(f"  Entry Price: {entry_price:.6f}")
            print(f"  Margin: ${margin:.2f}")
            print(f"  Status: {'OPEN' if is_open else 'CLOSED'}")
            
            # 2. Mock Price Tracking / PnL Calculation
            # In real backend, this comes from Hyperliquid/Ostium.
            # Here we just show the logic.
            current_price = entry_price * 1.02 # Simulate 2% profit
            
            price_diff = current_price - entry_price
            if side == "SELL":
                price_diff = -price_diff
                
            pnl = (price_diff / entry_price) * size_usd
            roe = (pnl / margin) * 100
            
            print(f"  --- Tracking Simulation ---")
            print(f"  Current Price: {current_price:.6f} (Simulated +2%)")
            print(f"  Unrealized PnL: ${pnl:.4f}")
            print(f"  ROE: {roe:.2f}%")

    except Exception as e:
        print(f"Error fetching: {e}")

if __name__ == "__main__":
    asyncio.run(test_tracking())
