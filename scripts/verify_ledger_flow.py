
import sys
import os
# Fix import path immediately
sys.path.append(os.path.join(os.path.dirname(__file__), 'websocket'))
sys.path.append(os.path.dirname(__file__))

import asyncio
import uuid
from websocket.services.ledger_service import ledger_service
from websocket.services.portfolio_service import PortfolioService
from websocket.database.connection import AsyncSessionLocal, init_db

async def verify_flow():
    user = "0xTestUser" + str(uuid.uuid4())[:8]
    print(f"Testing Ledger Flow for {user}...")
    
    # 1. Simulate Deposit
    tx_hash = "0x" + str(uuid.uuid4()).replace("-", "")
    print(f"Processing Deposit of 1000 USDC...")
    await ledger_service.process_deposit(user, 1000.0, tx_hash)
    
    # Check Balance
    async with AsyncSessionLocal() as session:
        pf = PortfolioService(session)
        val = await pf.calculate_portfolio_value(user)
        print(f"Portfolio after Deposit: {val}")
        assert val['cash_balance'] == 1000.0, "Balance mismatch"
    
    # 2. Simulate Trade (Long BTC 0.1 @ 50000)
    # Margin = 5000 (1x leverage for simplicity)
    print("Processing Trade (Long BTC)...")
    tx_hash_order = "0x" + str(uuid.uuid4()).replace("-", "")
    await ledger_service.process_trade_open(
        user_address=user,
        symbol="BTC-USD",
        side="Long",
        size_token=0.1,
        entry_price=50000.0,
        leverage=1,
        margin_used=5000.0,
        order_id=tx_hash_order
    )
    
    async with AsyncSessionLocal() as session:
        pf = PortfolioService(session)
        val = await pf.calculate_portfolio_value(user)
        print(f"Portfolio after Trade: {val}")
        # Ledger Balance is still 1000. Available should be 1000 - 5000? Wait, deposit was 1000.
        # 1000 deposit. Trade requires 5000 margin?? That should be invalid.
        # But `process_trade_open` assumes validation happened before (OrderRouter check or OrderService check).
        # In this logic, it just updates. locked_margin should be 5000.
        # Cash Balance (Available) should be 1000 - 5000 = -4000.
        # This confirms we need to enforce checks in `OrderService` OR `LedgerService` before sending to chain, 
        # BUT `process_trade_open` reflects what happened (even if valid/invalid state, simulating effect).
        # Let's fix the test numbers.
        
    # Retry with valid numbers: Deposit 10,000
    print("Top-up Deposit 9000...")
    await ledger_service.process_deposit(user, 9000.0, "0x" + str(uuid.uuid4()))
    
    async with AsyncSessionLocal() as session:
        pf = PortfolioService(session)
        val = await pf.calculate_portfolio_value(user)
        print(f"Portfolio after TopUp: {val}")
        # Total Balance 10000. Locked 5000. Cash (Free) 5000.
        assert val['locked_margin'] == 5000.0
        assert val['cash_balance'] == 5000.0
        
    # 3. Simulate Price Move (Price Pusher Mock)
    # Logic in PortfolioService reads from `p.unrealized_pnl`. 
    # Usually `price_pusher` updates `Position.unrealized_pnl` column directly in DB or via Service.
    # Let's mock a database update for PnL.
    from sqlalchemy import update
    from websocket.database.models import Position
    print("Simulating Price Move (BTC -> 55000)... PnL = +500")
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Position)
            .where(Position.user_address == user.lower())
            .values(unrealized_pnl=500.0)
        )
        await session.commit()
        
    async with AsyncSessionLocal() as session:
        pf = PortfolioService(session)
        val = await pf.calculate_portfolio_value(user)
        print(f"Portfolio after Price Move: {val}")
        assert val['unrealized_pnl'] == 500.0
        assert val['portfolio_value'] == 10000.0 + 500.0
        
    # 4. Close Position
    print("Processing Close...")
    await ledger_service.process_trade_close(user, "BTC-USD", 55000.0) # Full close
    
    async with AsyncSessionLocal() as session:
        pf = PortfolioService(session)
        val = await pf.calculate_portfolio_value(user)
        print(f"Final Portfolio: {val}")
        assert val['locked_margin'] == 0
        assert val['cash_balance'] == 10500.0 # 10000 start + 500 profit
        assert val['portfolio_value'] == 10500.0

    print("✅ Ledger Flow Verification Passed!")

if __name__ == "__main__":
    # Fix import path
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), 'websocket'))
    # Init DB first just in case
    # asyncio.run(init_db()) 
    # Actually skip init_db if we trust schema is applied
    asyncio.run(verify_flow())
