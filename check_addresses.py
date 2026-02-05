
import asyncio
import sys
import os

sys.path.append(os.path.abspath("backend/websocket"))

from database.connection import init_db, AsyncSessionLocal
from database.models import LedgerAccount, FundingHistory
from sqlalchemy import select

async def check_addresses():
    await init_db()
    async with AsyncSessionLocal() as session:
        # Check Ledger Accounts
        acc_result = await session.execute(select(LedgerAccount))
        accounts = acc_result.scalars().all()
        print(f"--- Ledger Accounts ({len(accounts)}) ---")
        for a in accounts:
            print(f"Address: {a.address} | Balance: {a.balance}")

        # Check Funding History
        fund_result = await session.execute(select(FundingHistory))
        records = fund_result.scalars().all()
        print(f"\n--- Funding History Unique Addresses ---")
        addresses = set(r.user_address for r in records)
        for addr in addresses:
            count = sum(1 for r in records if r.user_address == addr)
            print(f"Address: {addr} | Records: {count}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_addresses())
