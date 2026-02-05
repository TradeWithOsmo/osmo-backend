import asyncio
from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import Order

async def check():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order.id, Order.symbol, Order.side, Order.exchange_order_id, Order.status, Order.created_at)
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        for r in result.all():
            print(f"{r.symbol} | {r.side} | {r.status} | ID: {r.id} | EX_ID: {r.exchange_order_id}")

if __name__ == "__main__":
    asyncio.run(check())
