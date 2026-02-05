import asyncio
from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import Order, Position, LedgerAccount

async def check(address):
    async with AsyncSessionLocal() as session:
        # Check Ledger
        res_ledger = await session.execute(select(LedgerAccount).where(LedgerAccount.address == address.lower()))
        ledger = res_ledger.scalar_one_or_none()
        if ledger:
            print(f"--- LEDGER ({address}) ---")
            print(f"Balance: {ledger.balance}")
            print(f"Locked Margin: {ledger.locked_margin}")
            print(f"Available: {ledger.available_balance}")
        else:
            print(f"No LedgerAccount for {address}")

        # Check Active Positions
        res_pos = await session.execute(select(Position).where(Position.user_address == address.lower(), Position.status == 'OPEN'))
        positions = res_pos.scalars().all()
        print(f"\n--- ACTIVE POSITIONS ({len(positions)}) ---")
        for p in positions:
            print(f"{p.symbol} | {p.side} | Size: {p.size} | Margin: {p.margin_used}")

        # Check Open Orders
        res_orders = await session.execute(select(Order).where(Order.user_address == address.lower(), Order.status.in_(['pending', 'open', 'OPEN'])))
        orders = res_orders.scalars().all()
        print(f"\n--- OPEN ORDERS ({len(orders)}) ---")
        for o in orders:
            print(f"{o.symbol} | {o.side} | Type: {o.order_type} | Status: {o.status}")

if __name__ == "__main__":
    import sys
    addr = sys.argv[1] if len(sys.argv) > 1 else "0x6e2003c73F54eE0740E7Ea8b0d40Bf57321F54e7"
    asyncio.run(check(addr))
