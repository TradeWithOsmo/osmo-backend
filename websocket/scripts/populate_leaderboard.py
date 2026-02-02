import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import async_session
from services.leaderboard_service import LeaderboardService

async def main():
    print("Connecting to database...")
    async with async_session() as db:
        print("Initializing Leaderboard Service...")
        service = LeaderboardService(db)
        
        print("Triggering Leaderboard Snapshot Calculation...")
        try:
            await service.save_snapshots()
            print("\n✅ Success! Leaderboard snapshots have been generated.")
            print("You can now refresh the Leaderboard page to see the data.")
        except Exception as e:
            print(f"\n❌ Error generating snapshots: {e}")

if __name__ == "__main__":
    asyncio.run(main())
