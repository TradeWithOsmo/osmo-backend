
import asyncio
import sys
import os

sys.path.append(os.path.abspath("backend/websocket"))

from database.connection import init_db, AsyncSessionLocal
from database.models import FundingHistory
from sqlalchemy import select

async def debug_funding():
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FundingHistory))
        records = result.scalars().all()
        print(f"TOTAL RECORDS: {len(records)}")
        for r in records:
            print(f"--- Record ID: {r.id} ---")
            print(f"User Address: {r.user_address}")
            print(f"Type        : {r.type}")
            print(f"Amount      : {r.amount}")
            print(f"Tx Hash     : {r.tx_hash}")
            print(f"Status      : {r.status}")
            print(f"Timestamp   : {r.timestamp}")
            print("-" * 20)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(debug_funding())
