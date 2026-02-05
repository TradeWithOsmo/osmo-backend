import asyncio
import os
import sys

# Add backend and websocket to path
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_path)
sys.path.append(os.path.join(backend_path, "websocket"))

from connectors.web3_arbitrum.onchain_connector import OnchainConnector
from connectors.web3_arbitrum.session_manager import session_manager
from config import settings
from web3 import Web3

async def test_order_placement_simulation():
    """Test order placement simulation via EstimateGas"""
    
    # Test address (Must have session key)
    test_address = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"
    
    print(f"Testing Order Placement Simulation for {test_address}...")
    print("=" * 60)
    
    connector = OnchainConnector(settings.dict() if hasattr(settings, 'dict') else {})
    
    # 1. Bypass Session Key - Simulate direct wallet interaction
    # We don't need a signature for estimate_gas, we just need to set 'from' correctly.
    
    # 2. Prepare Order Params
    symbol = "ETH-USD"
    amount_usd = 10.0
    leverage = 5
    
    # Try different precisions
    precisions = [6, 18] # TradingVault = 1e6 (USDC), Standard = 1e18
    
    print("\nSimulating Direct Order Placement (Wallet Sign) with different decimals:")
    
    for decimals in precisions:
        print(f"\n--- Testing 1e{decimals} ---")
        try:
            order_router = connector.w3_connector.get_contract("OrderRouter")
            
            # AmountUSD -> 1e6 is likely correct because it matches USDC (Collateral)
            amount_int = int(amount_usd * (10**decimals))
            
            # Params tuple
            # struct OrderParams {
            #     address user;
            #     string symbol;
            #     uint8 side;
            #     uint8 orderType;
            #     uint256 amountUsd;
            #     uint8 leverage;
            #     uint256 price;
            #     uint256 stopPrice;
            # }
            params = (
                Web3.to_checksum_address(test_address), # user
                symbol,
                0, # Buy
                0, # Market
                amount_int,
                leverage,
                0, # Price 0 for market
                0  # StopPrice
            )
            
            print(f"   Params: {params}")
            print(f"   Simulated Sender (msg.sender): {test_address}")
            
            # Estimate Gas simulating call from the User (Self-Trading)
            gas = order_router.functions.placeOrder(params).estimate_gas({
                'from': Web3.to_checksum_address(test_address)
            })
            print(f"   ✅ SUCCESS! Gas Estimate: {gas}")
            print(f"   Conclusion: Contract accepts direct calls from User with 1e{decimals}")
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            # Try to decode error if possible (rudimentary)
            if "e2517d3f" in str(e):
                print("   -> Error: AccessControlUnauthorizedAccount (Still failing? Then User != Authorized?)")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_order_placement_simulation())
