import asyncio
import sys
import os
from sqlalchemy import select, func

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import AsyncSessionLocal
from database.models import Order

async def check_orders():
    async with AsyncSessionLocal() as db:
        stmt = select(Order.status, func.count(Order.id)).group_by(Order.status)
        result = await db.execute(stmt)
        for status, count in result.all():
            print(f"Status: {status}, Count: {count}")

if __name__ == "__main__":
    asyncio.run(check_orders())
