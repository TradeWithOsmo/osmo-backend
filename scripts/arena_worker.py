import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from websocket.database.connection import engine, Base
from websocket.database.models import Order
from websocket.database.arena_models import ArenaPick, ArenaReward, ArenaLeaderboard

# Multipliers
WINNER_MULTIPLIER = 200 # 2x
LOSER_MULTIPLIER = 10   # 10% consolation

POINT_PER_USD = 1.0

async def award_trading_points(db: AsyncSession):
    """Scan filled orders and award points to users."""
    print("[ArenaWorker] Checking for new trading points...")
    
    # Simple logic: Find confirmed orders that don't have points awarded yet
    # In a real app, we'd have a 'points_awarded' flag on Order or a tracking table
    # For now, we fetch all filled orders from the last hour
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    stmt = select(Order).where(Order.status == 'filled') # , Order.updated_at > hour_ago
    result = await db.execute(stmt)
    orders = result.scalars().all()
    
    for order in orders:
        points = float(order.notional_usd) * POINT_PER_USD
        if points <= 0: continue
        
        # Check if already awarded (using user_address + window_id + order_id logic would be better)
        # For this demo, let's just award if not exists in ArenaReward with this context
        # Ideally, we should add 'order_id' to ArenaReward as a tracking field
        
        # Skip check for simplicity in this POC, just assume we have a way to track
        pass
    
    await db.commit()

async def update_leaderboard(db: AsyncSession):
    """Aggregate PNL/ROI from orders and update ArenaLeaderboard."""
    print("[ArenaWorker] Updating leaderboard...")
    
    # 1. Get all picks
    stmt = select(ArenaPick)
    result = await db.execute(stmt)
    picks = result.scalars().all()
    
    for pick in picks:
        # Aggregate performance for this user in the window
        # For simplicity, we use the 'Order.realized_pnl' field
        pnl_stmt = select(func.sum(Order.realized_pnl), func.sum(Order.notional_usd)).where(Order.user_address == pick.user_address)
        pnl_res = await db.execute(pnl_stmt)
        total_pnl, total_vol = pnl_res.fetchone()
        
        total_pnl = total_pnl or 0.0
        total_vol = total_vol or 0.0
        roi = (total_pnl / pick.wager * 100) if pick.wager > 0 else 0.0
        
        # Update leaderboard table
        lb_stmt = select(ArenaLeaderboard).where(ArenaLeaderboard.user_address == pick.user_address)
        lb_result = await db.execute(lb_stmt)
        lb = lb_result.scalar_one_or_none()
        
        if lb:
            lb.pnl = total_pnl
            lb.roi = roi
            lb.volume = total_vol
            lb.side = pick.side
        else:
            new_lb = ArenaLeaderboard(
                user_address=pick.user_address,
                side=pick.side,
                pnl=total_pnl,
                roi=roi,
                volume=total_vol
            )
            db.add(new_lb)
    
    await db.commit()
    
    # Update Ranks
    for side in ['human', 'ai']:
        lb_stmt = select(ArenaLeaderboard).where(ArenaLeaderboard.side == side).order_by(ArenaLeaderboard.roi.desc())
        lb_res = await db.execute(lb_stmt)
        entries = lb_res.scalars().all()
        for i, entry in enumerate(entries):
            entry.rank = i + 1
    
    await db.commit()

async def settle_event(db: AsyncSession):
    """Determine the winning side using Top 1000 traders and distribute points."""
    print("[ArenaWorker] Checking for event settlement (using Top 1000 logic)...")
    
    # Calculate average ROI for TOP 1000 of each side
    async def get_top_1000_avg_roi(side: str):
        subq = (
            select(ArenaLeaderboard.roi)
            .where(ArenaLeaderboard.side == side)
            .order_by(ArenaLeaderboard.roi.desc())
            .limit(1000)
            .subquery()
        )
        stmt = select(func.avg(subq.c.roi))
        res = await db.execute(stmt)
        return res.scalar() or 0.0

    h_roi = await get_top_1000_avg_roi('human')
    a_roi = await get_top_1000_avg_roi('ai')
    
    winner_side = 'human' if h_roi > a_roi else 'ai'
    print(f"[ArenaWorker] Winning Side: {winner_side}")
    print(f"  - Humans (Top 1000 Avg ROI): {h_roi:.2f}%")
    print(f"  - AI (Top 1000 Avg ROI): {a_roi:.2f}%")
    
    # Fetch ALL picks to settle (not just top 1000)
    pick_stmt = select(ArenaPick).where(ArenaPick.status == 'confirmed')
    picks = (await db.execute(pick_stmt)).scalars().all()
    
    # Calculate Total Wagers per side
    total_winner_wager = sum(p.wager for p in picks if p.side == winner_side)
    total_loser_wager = sum(p.wager for p in picks if p.side != winner_side)
    
    # Distribution Settings
    WINNER_BONUS_POOL_PCT = 0.65
    LOSER_REBATE_PCT = 0.10
    
    bonus_pool = total_loser_wager * WINNER_BONUS_POOL_PCT
    
    print(f"  - Total Winner Wagers: {total_winner_wager}")
    print(f"  - Total Loser Wagers: {total_loser_wager}")
    print(f"  - Bonus Pool to Winners (65%): {bonus_pool}")
    print(f"  - Rebate Pool to Losers (10%): {total_loser_wager * LOSER_REBATE_PCT}")

    for pick in picks:
        won = pick.side == winner_side
        reward_amount = 0.0
        
        if won:
            # Reward = Stake + Share of 65% Loser Pool
            share = (pick.wager / total_winner_wager) if total_winner_wager > 0 else 0
            reward_amount = pick.wager + (share * bonus_pool)
        else:
            # Losers get 10% of their stake back as consolation
            reward_amount = pick.wager * LOSER_REBATE_PCT
        
        # 1. Update Database
        reward = ArenaReward(
            user_address=pick.user_address,
            amount=reward_amount,
            window_id=1 
        )
        db.add(reward)
        pick.status = 'settled'
        
        # 2. Trigger On-Chain (Simulation)
        print(f"  - Settled {pick.user_address}: {'WON' if won else 'LOST'} | Wager: {pick.wager} -> Payout: {reward_amount:.4f}")

    await db.commit()

async def main():
    while True:
        try:
            async with AsyncSession(engine) as db:
                await award_trading_points(db)
                await update_leaderboard(db)
                
                # In a real app, check if block.timestamp > event_end
                # For this POC, we can trigger it manually or via a flag
                # await settle_event(db) 
                
            print("[ArenaWorker] Loop finished. Sleeping for 60s...")
            await asyncio.sleep(60)
        except Exception as e:
            print(f"[ArenaWorker] Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
