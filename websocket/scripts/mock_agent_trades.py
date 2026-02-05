import asyncio
import sys
import os
from sqlalchemy import update

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import AsyncSessionLocal
from database.models import Order

async def mock_agent_trades():
    async with AsyncSessionLocal() as db:
        # Mock some orders as agent trades
        # Pick orders from a specific user
        user = "0xc65870884989f6748af9822f17b2758a48d97b79"
        stmt = update(Order).where(Order.user_address == user).values(
            is_agent_trade=True,
            agent_model="gpt-4o"
        )
        await db.execute(stmt)
        
        # Mock some other orders for another model
        user2 = "0xtest_54e66395"
        stmt2 = update(Order).where(Order.user_address == user2).values(
            is_agent_trade=True,
            agent_model="claude-3.5-sonnet"
        )
        await db.execute(stmt2)
        
        await db.commit()
        print("Mocked some agent trades!")

if __name__ == "__main__":
    asyncio.run(mock_agent_trades())
