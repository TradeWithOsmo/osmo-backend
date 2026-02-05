import asyncio
import sys
import os
from sqlalchemy import select, func

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import AsyncSessionLocal
from database.models import Order

async def check():
    async with AsyncSessionLocal() as db:
        stmt = select(Order.is_agent_trade, func.count(Order.id)).group_by(Order.is_agent_trade)
        result = await db.execute(stmt)
        for val, count in result.all():
            print(f"IsAgentTrade: {val}, Count: {count}")

if __name__ == "__main__":
    asyncio.run(check())
