
import asyncio
from sqlalchemy import text
from database.connection import AsyncSessionLocal

async def check_columns():
    async with AsyncSessionLocal() as session:
        print("Checking Chat tables columns...")
        
        for table in ["chat_sessions", "chat_messages", "chat_workspaces"]:
            print(f"\n--- Columns in {table} ---")
            try:
                result = await session.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'"))
                cols = result.fetchall()
                for c in cols:
                    print(f"  {c[0]}: {c[1]}")
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_columns())
