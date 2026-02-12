import asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import os
import sys

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from websocket.database.connection import engine
from websocket.database.arena_models import ArenaPick, ArenaReward, ArenaLeaderboard
from websocket.database.models import Order

async def check_db_stats():
    async with AsyncSession(engine) as session:
        # Check Picks
        picks_count = (await session.execute(select(func.count(ArenaPick.id)))).scalar()
        
        # Check Leaderboard
        lb_count = (await session.execute(select(func.count(ArenaLeaderboard.id)))).scalar()
        
        # Check Rewards
        reward_count = (await session.execute(select(func.count(ArenaReward.id)))).scalar()
        
        # Check Orders (to see if points can be generated)
        orders_count = (await session.execute(select(func.count(Order.id)))).scalar()

        print(f"\n📊 --- DB STATS ---")
        print(f"Arena Picks: {picks_count}")
        print(f"Leaderboard Entries: {lb_count}")
        print(f"Total Rewards Distributed: {reward_count}")
        print(f"Total Trading Orders: {orders_count}")
        print(f"--------------------\n")

if __name__ == "__main__":
    asyncio.run(check_db_stats())
