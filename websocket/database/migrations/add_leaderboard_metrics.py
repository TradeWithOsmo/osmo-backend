import asyncio
import sys
import os
from sqlalchemy import text

# Add base directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.connection import engine

async def migrate():
    print("Migrating leaderboard tables...")
    async with engine.begin() as conn:
        # Add columns to leaderboard_snapshots
        try:
            await conn.execute(text("ALTER TABLE leaderboard_snapshots ADD COLUMN trade_count INTEGER DEFAULT 0;"))
            print("Added trade_count to leaderboard_snapshots")
        except Exception as e:
            print(f"Note: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE leaderboard_snapshots ADD COLUMN win_rate FLOAT DEFAULT 0;"))
            print("Added win_rate to leaderboard_snapshots")
        except Exception as e:
            print(f"Note: {e}")
            
        # Add columns to model_leaderboard_snapshots
        try:
            await conn.execute(text("ALTER TABLE model_leaderboard_snapshots ADD COLUMN trade_count INTEGER DEFAULT 0;"))
            print("Added trade_count to model_leaderboard_snapshots")
        except Exception as e:
            print(f"Note: {e}")
            
        try:
            await conn.execute(text("ALTER TABLE model_leaderboard_snapshots ADD COLUMN win_rate FLOAT DEFAULT 0;"))
            print("Added win_rate to model_leaderboard_snapshots")
        except Exception as e:
            print(f"Note: {e}")
            
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
