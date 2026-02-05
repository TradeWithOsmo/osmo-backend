import asyncio
import sys
import os
import uuid
from typing import Dict, Any

# Add the backend and websocket to path
sys.path.append('/app')

from config import settings
from services.order_service import OrderService
from database.connection import init_db, AsyncSessionLocal
from database.models import Order, Position
from sqlalchemy import select

async def test_onchain_order():
    print("🚀 Starting On-Chain Order Flow Test")
    
    # Initialize DB (Connectors are initialized in lifespan, but if running standalone we might need to do it)
    from connectors.init_connectors import connector_registry
    await connector_registry.initialize()
    
    order_service = OrderService()
    
    user_address = "0xC65870884989F6748aF9822f17b2758A48d97B79" # Tertiary
    symbol = "BTC-USD"
    amount_usd = 11.0 # $11
    leverage = 10
    
    print(f"1. Placing Market Buy Order for ${amount_usd} on {symbol}...")
    
    try:
        response = await order_service.place_order(
            user_address=user_address,
            symbol=symbol,
            side='buy',
            order_type='market',
            amount_usd=amount_usd,
            leverage=leverage,
            exchange='onchain'
        )
        
        print(f"✅ Order response: {response}")
        tx_hash = response.get('exchange_order_id')
        
        if not tx_hash:
            print("❌ No TX hash in response!")
            return

        print(f"2. Waiting for Indexer to pick up transaction {tx_hash}...")
        
        # Wait for up to 60 seconds
        found = False
        for i in range(60):
            await asyncio.sleep(2)
            async with AsyncSessionLocal() as session:
                stmt = select(Order).where(Order.exchange_order_id == tx_hash)
                result = await session.execute(stmt)
                order = result.scalar_one_or_none()
                
                if order:
                    print(f"   Block {i*2}s: Order found in DB with status: {order.status}")
                    if order.status == 'FILLED' or order.status == 'filled':
                        found = True
                        print("✅ Order picked up and marked as FILLED by Indexer!")
                        break
                else:
                    print(f"   Block {i*2}s: Order not yet in DB...")

        if not found:
            print("❌ Timeout: Indexer did not pick up the order within 60s.")
            
        # 3. Check Position
        print(f"\n3. Verifying Position in DB for {user_address}...")
        async with AsyncSessionLocal() as session:
            stmt = select(Position).where(
                Position.user_address == user_address.lower(),
                Position.symbol == symbol,
                Position.status == 'OPEN'
            )
            result = await session.execute(stmt)
            position = result.scalar_one_or_none()
            
            if position:
                print(f"✅ Position found! Size: {position.size}, Entry Price: {position.entry_price}")
            else:
                print("❌ No active position found in DB.")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_onchain_order())
