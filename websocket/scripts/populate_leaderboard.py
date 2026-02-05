import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import AsyncSessionLocal
from services.leaderboard_service import LeaderboardService

async def main():
    print("Connecting to database...")
    async with AsyncSessionLocal() as db:
        print("Initializing Leaderboard Service...")
        service = LeaderboardService(db)
        
        print("Clearing today's snapshots...")
        from sqlalchemy import text
        from datetime import date
        await db.execute(text("DELETE FROM leaderboard_snapshots WHERE snapshot_date = :d"), {"d": date.today()})
        await db.execute(text("DELETE FROM model_leaderboard_snapshots WHERE snapshot_date = :d"), {"d": date.today()})
        await db.commit()
        
        print("Triggering Leaderboard Snapshot Calculation...")
        try:
            await service.save_snapshots()
            print("\n✅ Success! Leaderboard snapshots have been generated.")
            print("You can now refresh the Leaderboard page to see the data.")
        except Exception as e:
            print(f"\n❌ Error generating snapshots: {e}")

if __name__ == "__main__":
    asyncio.run(main())
