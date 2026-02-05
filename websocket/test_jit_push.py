import asyncio
import sys
import os

# Add the backend and websocket to path
sys.path.append('/app')

from services.order_service import OrderService
from connectors.init_connectors import connector_registry

async def test_jit_push():
    print("🚀 Testing Just-In-Time (JIT) Price Push")
    
    await connector_registry.initialize()
    order_service = OrderService()
    
    user_address = "0xC65870884989F6748aF9822f17b2758A48d97B79"
    symbol = "BTC-USD"
    
    print(f"Placing On-Chain order for {symbol}...")
    try:
        # This should trigger _push_price_now inside OnchainConnector
        response = await order_service.place_order(
            user_address=user_address,
            symbol=symbol,
            side='buy',
            order_type='market',
            amount_usd=11.0,
            leverage=10,
            exchange='onchain'
        )
        print(f"✅ Order Response: {response}")
        print("Check docker logs for [JIT-Oracle] messages.")
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_jit_push())
