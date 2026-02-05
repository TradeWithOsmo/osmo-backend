import asyncio
from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import Position, LedgerAccount

async def find_problem():
    async with AsyncSessionLocal() as session:
        # Find any position or account with approx 2.65 margin
        print("--- Checking Positions ---")
        res_pos = await session.execute(select(Position).where(Position.status == 'OPEN'))
        for p in res_pos.scalars().all():
            if abs(p.margin_used - 2.65) < 0.1:
                print(f"POS: {p.user_address} | {p.symbol} | Margin: {p.margin_used}")

        print("\n--- Checking Ledger ---")
        res_led = await session.execute(select(LedgerAccount))
        for l in res_led.scalars().all():
            if abs(l.locked_margin - 2.65) < 0.1:
                print(f"LED: {l.address} | Margin: {l.locked_margin} | Bal: {l.balance}")

if __name__ == "__main__":
    asyncio.run(find_problem())
