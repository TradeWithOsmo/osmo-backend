import asyncio
import os
import sys

# Add the parent directory to sys.path to find 'connectors'
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from connectors.init_connectors import connector_registry
from config import settings

async def check_onchain_balance(address):
    # Initialize connectors
    await connector_registry.initialize()
    
    onchain = connector_registry.get_connector('onchain')
    if not onchain:
        print("On-chain connector not found")
        return

    balances = await onchain.get_user_balances(address)
    print(f"\n--- ON-CHAIN VAULT ({address}) ---")
    print(f"Account Value: {balances.get('account_value')}")
    print(f"Reserved (Locked): {balances.get('total_margin_used')}")
    print(f"Available: {balances.get('free_collateral')}")
    
    await connector_registry.shutdown()

if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else "0xC65870884989F6748aF9822f17b2758A48d97B79"
    asyncio.run(check_onchain_balance(addr))
