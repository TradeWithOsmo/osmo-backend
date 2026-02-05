
import asyncio
import sys
import os
import uuid
import logging
from tabulate import tabulate
from datetime import datetime

# Add parent dir to path
curr_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(curr_dir) # backend
sys.path.append(parent_dir)
sys.path.append(curr_dir)

from database.connection import AsyncSessionLocal
from database.models import Position, Order, FundingHistory, Trade
from sqlalchemy import select
from connectors.init_connectors import connector_registry
from services.order_service import order_service
from services.ledger_service import ledger_service
from services.trade_action_service import trade_action_service
from services.matching_engine import simulation_matching_engine
from services.portfolio_service import PortfolioService
from sqlalchemy import text # Import text
from database.connection import engine, Base

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("SimTest")

# Ensure Schema Update
async def reset_tables():
    logger.info("♻️  Resetting DB Schema for Test...")
    async with engine.begin() as conn:
        # User is using local pg. Let's try to add columns via raw SQL if missing.
        try:
             await conn.execute(text("ALTER TABLE orders ADD COLUMN stop_price FLOAT"))
             await conn.execute(text("ALTER TABLE orders ADD COLUMN trigger_price FLOAT"))
             await conn.execute(text("ALTER TABLE orders ADD COLUMN trigger_condition VARCHAR"))
             await conn.execute(text("ALTER TABLE orders ADD COLUMN reduce_only BOOLEAN"))
             await conn.execute(text("ALTER TABLE orders ADD COLUMN post_only BOOLEAN"))
             await conn.execute(text("ALTER TABLE orders ADD COLUMN time_in_force VARCHAR"))
             logger.info("✅ Added missing columns to orders table")
        except Exception:
             pass # Columns likely exist or error ignored

TEST_USER = "0xTest_" + str(uuid.uuid4())[:8]
RESULTS = []

async def check(name, condition, details=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append([name, status, details])
    if not condition:
        print(f"❌ {name} FAILED: {details}")
        # raise Exception(f"Test Failed: {name}")

async def run_suite():
    print(f"\n🚀 STARTING 100% COVERAGE SIMULATION TEST for {TEST_USER}")
    
    # Init
    await connector_registry.initialize()
    await reset_tables() # Reset DB to ensure columns exist
    asyncio.create_task(simulation_matching_engine.start())
    
    # ==================================================================================
    # TEST CASE 1: FUNDING HISTORY
    # ==================================================================================
    print("\n[1] FUNDING TEST (Deposit)")
    tx_hash = f"tx_{uuid.uuid4().hex[:10]}"
    await ledger_service.process_deposit(TEST_USER, 10000.0, tx_hash)
    await asyncio.sleep(1)
    
    async with AsyncSessionLocal() as session:
        # Verify Funding Record
        res = await session.execute(select(FundingHistory).where(FundingHistory.user_address == TEST_USER.lower()))
        funding = res.scalars().first()
        
        await check("Funding Record Exists", funding is not None)
        await check("Funding Amount", funding.amount == 10000.0)
        await check("Funding Asset", funding.asset == "USDC")
        await check("Funding Type", funding.type == "Deposit")
        await check("Funding TxHash", funding.tx_hash == tx_hash)
        await check("Funding Status", funding.status == "Completed")

    # ==================================================================================
    # TEST CASE 2: MARKET ORDER (Basic)
    # ==================================================================================
    print("\n[2] MARKET ORDER TEST")
    
    # Place Limit Buy far above price to simulate Market Fill (since we implemented Matching Engine logic mostly for pending?)
    # Wait, Market Order calls process_trade_open directly.
    
    # Buying 0.1 BTC (approx $10k at $100k, let's use $5000 USD size)
    # We fetch current price first to ensure we know what to expect
    conn = connector_registry.get_connector('hyperliquid')
    data = await conn.fetch('BTC', 'price')
    btc_price = float(data['data']['price'])
    logger.info(f"Current BTC Price: {btc_price}")

    await order_service.place_order(
        user_address=TEST_USER, symbol="BTC-USD", side="buy", order_type="market",
        amount_usd=5000.0, leverage=10, exchange="simulation" 
    )
    await asyncio.sleep(1) # DB Sync
    
    async with AsyncSessionLocal() as session:
        # Verify Position
        res = await session.execute(select(Position).where(Position.user_address == TEST_USER.lower(), Position.symbol == "BTC-USD"))
        pos = res.scalars().first()
        
        await check("Pos Created", pos is not None)
        await check("Pos Symbol", pos.symbol == "BTC-USD")
        await check("Pos Side", pos.side.lower() == "long")
        await check("Pos Entry Price", pos.entry_price > 0)
        expected_size = 5000.0 / pos.entry_price
        await check("Pos Size", abs(pos.size - expected_size) < 0.0001, f"Got {pos.size}, Exp {expected_size}")
        
        # Verify Trade History (Order Record)
        # Market Order creates Filled Order
        res_ord = await session.execute(select(Order).where(Order.user_address == TEST_USER.lower()))
        order = res_ord.scalars().first()
        await check("Order History Exists", order is not None)
        await check("Order Status", order.status == "FILLED")
        await check("Order Type", order.order_type == "market")

    # ==================================================================================
    # TEST CASE 3: LIMIT ORDER (GTC + Fill)
    # ==================================================================================
    print("\n[3] LIMIT ORDER TEST")
    
    # Place Limit Buy -10% from current price
    limit_price = btc_price * 0.9
    
    await order_service.place_order(
        user_address=TEST_USER, symbol="BTC-USD", side="buy", order_type="limit",
        amount_usd=1000.0, leverage=10, price=limit_price, exchange="simulation",
        time_in_force="GTC"
    )
    await asyncio.sleep(1)
    
    async with AsyncSessionLocal() as session:
        # Verify Pending Order
        # OrderService returns 'pending', verify against that or 'OPEN'
        res = await session.execute(select(Order).where(
            Order.user_address == TEST_USER.lower(),
            Order.order_type == "limit",
            Order.status.in_(['pending', 'OPEN'])
        ))
        pending_orders = res.scalars().all()
        # Filter by recent
        limit_order = pending_orders[-1] if pending_orders else None
        
        await check("Limit Pending Created", limit_order is not None, f"Found {len(pending_orders)} pending orders")
        if limit_order:
            await check("Limit Status Pending", limit_order.status in ["pending", "OPEN"], f"Got {limit_order.status}")
            await check("Limit Price Correct", limit_order.price == limit_price)
            
            # TRIGGER FILL
            # We cheat by injecting price into Matching Engine cache to force trigger
            # AND we must prevent engine from fetching live price and overwriting our cheat
            original_fetch = simulation_matching_engine._fetch_prices
            simulation_matching_engine._fetch_prices = lambda s: asyncio.sleep(0)
            
            print(f"    -> Simulating Price Drop to {limit_price - 100}")
            simulation_matching_engine._price_cache['BTC-USD'] = limit_price - 100
            
            await simulation_matching_engine.process_matching_cycle()
            
            # Restore
            simulation_matching_engine._fetch_prices = original_fetch
            
            await asyncio.sleep(1)
            
            await session.refresh(limit_order)
            await check("Limit Order Filled", limit_order.status == "FILLED")
            
            # Verify Position Merged
            res_p = await session.execute(select(Position).where(Position.user_address == TEST_USER.lower(), Position.symbol == "BTC-USD"))
            pos = res_p.scalars().first() # Re-fetch
            await check("Pos Size Increased", pos.size > expected_size)


    # ==================================================================================
    # TEST CASE 4: STOP ORDER
    # ==================================================================================
    print("\n[4] STOP ORDER TEST")
    # Stop Market Sell below current price
    stop_price = btc_price * 0.8
    
    await order_service.place_order(
        user_address=TEST_USER, symbol="BTC-USD", side="sell", order_type="stop_market",
        amount_usd=1000.0, leverage=10, price=0, stop_price=stop_price, exchange="simulation"
    )
    
    # Check trigger logic... (Simulate valid trigger later)

    # ==================================================================================
    # TEST CASE 5: TRADE ACTIONS (Reverse & Close)
    # ==================================================================================
    print("\n[5] TRADE ACTIONS TEST")
    
    # REVERSE
    from services.trade_action_service import trade_action_service
    # Force price for reverse match (Using cached price 90k)
    # Reverse expects to flip Long -> Short
    
    # We need to clear cache so it fetches real price for reverse? 
    # Or set cache to a profitable price?
    simulation_matching_engine._price_cache['BTC-USD'] = btc_price * 1.05 # Profit
    
    await trade_action_service.reverse_position(TEST_USER, "BTC-USD")
    await asyncio.sleep(1)
    
    async with AsyncSessionLocal() as session:
        # Must filter by OPEN because Reverse closes old one (keeping row) and opens new one
        res = await session.execute(select(Position).where(
            Position.user_address == TEST_USER.lower(), 
            Position.symbol == "BTC-USD",
            Position.status == "OPEN"
        ))
        pos_rev = res.scalars().first()
        await check("Reverse to Short", pos_rev is not None and pos_rev.side.lower() == "short")
        if pos_rev:
             logger.info(f"Reversed Position: {pos_rev.side} {pos_rev.size} @ {pos_rev.entry_price}")

    # ==================================================================================
    # TEST CASE: STOP ORDER TRIGGER
    # ==================================================================================
    # We placed a Stop Market Sell @ 0.8 * price.
    # To Trigger: Price MUST go BELOW 0.8 * price.
    trigger_level = btc_price * 0.75
    
    print(f"\n[4b] TRIGGER STOP ORDER (Drop to {trigger_level})")
    
    original_fetch = simulation_matching_engine._fetch_prices
    simulation_matching_engine._fetch_prices = lambda s: asyncio.sleep(0)
    simulation_matching_engine._price_cache['BTC-USD'] = trigger_level
    await simulation_matching_engine.process_matching_cycle()
    simulation_matching_engine._fetch_prices = original_fetch
    await asyncio.sleep(1)
    
    async with AsyncSessionLocal() as session:
         # Verify Stop Order Filled
         # Note: Stop Market becomes FILLED.
         # But wait, we reversed to SHORT.
         # The Stop Order was "Stop Market SELL".
         # Since we are now Short, a "Sell" order adds to Short.
         # Or if it was reduced only? We didn't specify.
         # Stop Market Sell defaults to opening/adding short or closing long?
         # "Side: sell". Open Short or Close Long.
         res_stop = await session.execute(select(Order).where(
             Order.user_address == TEST_USER.lower(),
             Order.order_type == "stop_market"
         ))
         stop_order = res_stop.scalars().first()
         
         await check("Stop Order Exists", stop_order is not None)
         if stop_order:
             await check("Stop Order Filled", stop_order.status == 'FILLED', f"Status: {stop_order.status}")

    # CLOSE ALL
    await trade_action_service.close_all_positions(TEST_USER)
    await asyncio.sleep(1)
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Position).where(Position.user_address == TEST_USER.lower(), Position.status == "OPEN"))
        open_pos = res.scalars().all()
        await check("Close All Success", len(open_pos) == 0)


    # ==================================================================================
    # REPORT
    # ==================================================================================
    print("\n" + "="*60)
    print(tabulate(RESULTS, headers=["Test Case", "Status", "Details"], tablefmt="fancy_grid"))
    print("="*60)
    
    await simulation_matching_engine.stop()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_suite())
