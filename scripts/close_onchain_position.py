#!/usr/bin/env python3
"""
Close on-chain position manually for testing
"""

import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))


async def close_onchain_position(user_address: str, symbol: str = "BTC-USD"):
    """Close on-chain position for testing"""
    from connectors.init_connectors import connector_registry
    from connectors.web3_arbitrum.onchain_connector import OnchainConnector

    # Get on-chain connector
    connector = connector_registry.get_connector("onchain")
    if not connector:
        print("❌ On-chain connector not found")
        return

    print(f"🔍 Fetching on-chain positions for {user_address}...")
    positions = await connector.get_user_positions(user_address)

    if not positions:
        print("✅ No on-chain positions found")
        return

    print(f"📊 Found {len(positions)} on-chain position(s):")
    for pos in positions:
        print(
            f"  - {pos['symbol']}: {pos['side']} {pos['size']} (Value: ${pos.get('position_value', 0):.2f})"
        )

    # Close all positions
    for pos in positions:
        print(f"\n🔨 Closing {pos['symbol']} {pos['side']} position...")
        try:
            # Calculate close amount (100% of position value)
            close_amount_usd = float(pos.get("position_value", 0))

            # Determine opposite side
            side = "sell" if pos["side"].lower() == "long" else "buy"

            print(f"  Side: {side}")
            print(f"  Amount: ${close_amount_usd:.2f} USD")

            # Place close order
            result = await connector.place_order(
                user_address=user_address,
                symbol=pos["symbol"],
                side=side,
                order_type="market",
                size=close_amount_usd,  # Amount in USD for on-chain
                reduce_only=True,
            )

            print(f"✅ Close order placed: {result}")

        except Exception as e:
            print(f"❌ Failed to close: {e}")

    print("\n✅ Done!")


if __name__ == "__main__":
    user_address = "0xDCa52E7aF42c0724F72C5c222aC355C36f8aBEa2"
    if len(sys.argv) > 1:
        user_address = sys.argv[1]

    print(f"🚀 Closing on-chain positions for {user_address}")
    asyncio.run(close_onchain_position(user_address))
