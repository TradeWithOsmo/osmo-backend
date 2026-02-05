import asyncio
from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import Order, Position, LedgerAccount

async def check_all():
    async with AsyncSessionLocal() as session:
        # Check all ledgers
        res_ledger = await session.execute(select(LedgerAccount))
        ledgers = res_ledger.scalars().all()
        print(f"--- ALL LEDGER ACCOUNTS ({len(ledgers)}) ---")
        for l in ledgers:
            print(f"Addr: {l.address} | Bal: {l.balance} | Locked: {l.locked_margin}")

        # Check all active positions
        res_pos = await session.execute(select(Position).where(Position.status == 'OPEN'))
        positions = res_pos.scalars().all()
        print(f"\n--- ALL ACTIVE POSITIONS ({len(positions)}) ---")
        for p in positions:
            print(f"Addr: {p.user_address} | {p.symbol} | {p.side} | Margin: {p.margin_used}")

if __name__ == "__main__":
    asyncio.run(check_all())
