import asyncio
import os
import sys

# Set up paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from websocket.services.order_service import order_service
from agent.Orchestrator.execution_adapter import ExecutionAdapter

async def test():
    user_address = "0x1234567890123456789012345678901234567890"
    print("Testing place_order...")
    
    try:
        res = await ExecutionAdapter.place_order(
            user_address=user_address,
            symbol="BTC-USD",
            side="buy",
            amount_usd=100.0,
            leverage=2,
            order_type="market",
            exchange="simulation"
        )
        print("place_order response:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

    print("\nTesting get_positions...")
    try:
        res2 = await ExecutionAdapter.get_positions(
            user_address=user_address,
            exchange="simulation"
        )
        print("get_positions response:", res2)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
