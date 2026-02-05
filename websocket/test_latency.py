import asyncio
import sys
import time
import uuid
from typing import Dict, Any

# Add the backend and websocket to path
sys.path.append('/app')

from config import settings
from services.order_service import OrderService
from database.connection import init_db, AsyncSessionLocal
from database.models import Order, Position
from sqlalchemy import select

async def run_latency_test(iterations=1):
    print(f"🚀 Starting On-Chain Latency Test ({iterations} iterations)")
    
    from connectors.init_connectors import connector_registry
    await connector_registry.initialize()
    
    order_service = OrderService()
    user_address = "0xC65870884989F6748aF9822f17b2758A48d97B79"
    symbol = "BTC-USD"
    
    results = []

    for i in range(iterations):
        print(f"\n--- Iteration {i+1} ---")
        start_time = time.time()
        
        try:
            # 1. Place Order
            response = await order_service.place_order(
                user_address=user_address,
                symbol=symbol,
                side='buy' if i % 2 == 0 else 'sell', # Alternate to net out somewhat
                order_type='market',
                amount_usd=11.0,
                leverage=10,
                exchange='onchain'
            )
            
            tx_hash = response.get('exchange_order_id')
            place_time = time.time()
            print(f"✅ Order placed in {place_time - start_time:.2f}s. TX: {tx_hash}")
            
            # 2. Poll for FILLED status
            found = False
            for attempt in range(60): # 120 seconds max
                await asyncio.sleep(2)
                async with AsyncSessionLocal() as session:
                    stmt = select(Order).where(Order.exchange_order_id == tx_hash)
                    result = await session.execute(stmt)
                    order = result.scalar_one_or_none()
                    
                    if order and (order.status.upper() == 'FILLED'):
                        filled_time = time.time()
                        latency = filled_time - place_time
                        print(f"✅ Order FILLED! Total latency from placement: {latency:.2f}s")
                        results.append(latency)
                        found = True
                        break
                    elif order:
                        pass # Still pending
                
            if not found:
                print("❌ Timeout: Order stayed pending for >120s")
                results.append(None)
                
        except Exception as e:
            print(f"❌ Error in iteration {i+1}: {e}")
            results.append(False)

    print("\n--- Summary ---")
    valid_results = [r for r in results if isinstance(r, (int, float))]
    if valid_results:
        avg = sum(valid_results) / len(valid_results)
        print(f"Average Fill Latency: {avg:.2f}s")
        print(f"Min Latency: {min(valid_results):.2f}s")
        print(f"Max Latency: {max(valid_results):.2f}s")
    else:
        print("No successful fills to average.")

if __name__ == "__main__":
    # Run 2 iterations to check consistency
    asyncio.run(run_latency_test(2))
