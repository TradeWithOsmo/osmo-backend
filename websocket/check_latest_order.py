import asyncio
import sys
sys.path.append('/app')
from database.connection import AsyncSessionLocal
from database.models import Order
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as s:
        # Check order from previous test
        res = await s.execute(select(Order).order_by(Order.created_at.desc()).limit(1))
        o = res.scalar_one_or_none()
        if o:
            print(f"Latest Order ID: {o.id}")
            print(f"Status: {o.status}")
            print(f"Tx Hash: {o.exchange_order_id}")
        else:
            print("No orders found.")

if __name__ == "__main__":
    asyncio.run(check())
