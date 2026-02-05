
import asyncio
import sys
import os

sys.path.append(os.path.abspath("backend/websocket"))

from database.connection import init_db, AsyncSessionLocal
from database.models import FundingHistory
from sqlalchemy import select

async def check_funding():
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FundingHistory))
        records = result.scalars().all()
        print(f"Total Funding Records: {len(records)}")
        for r in records:
            print(f"- {r.type} {r.amount} USDC | Tx: {r.tx_hash} | Time: {r.timestamp}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_funding())
