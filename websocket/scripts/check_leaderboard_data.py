import asyncio
import sys
import os
from datetime import date

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import AsyncSessionLocal
from database.models import LeaderboardSnapshot, Order
from sqlalchemy import select, func

async def check():
    async with AsyncSessionLocal() as db:
        # Check Orders
        order_count = await db.execute(select(func.count(Order.id)))
        print(f"Total Orders: {order_count.scalar()}")
        
        # Check Snapshots
        snapshot_count = await db.execute(select(func.count(LeaderboardSnapshot.id)))
        print(f"Total Snapshots: {snapshot_count.scalar()}")
        
        # Check snapshots for today
        today = date.today()
        stmt = select(LeaderboardSnapshot).where(LeaderboardSnapshot.snapshot_date == today)
        result = await db.execute(stmt)
        snapshots = result.scalars().all()
        print(f"Snapshots for today ({today}): {len(snapshots)}")
        
        for s in snapshots[:5]:
            print(f"Rank {s.rank}: {s.user_address} - PNL: {s.pnl}, Trades: {s.trade_count}")

if __name__ == "__main__":
    asyncio.run(check())
