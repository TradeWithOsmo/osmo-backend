from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.connection import get_db
from database.arena_models import ArenaPick, ArenaReward, ArenaLeaderboard
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional

router = APIRouter()

class PickRequest(BaseModel):
    user_address: str
    side: str
    wager: float
    tx_hash: Optional[str] = None

class UserStatsResponse(BaseModel):
    rank: Optional[int] = None
    pnl: float = 0.0
    roi: float = 0.0
    wager: float = 0.0
    points: float = 0.0

@router.post("/pick")
async def sync_pick(req: PickRequest, db: AsyncSession = Depends(get_db)):
    # Check current pick
    stmt = select(ArenaPick).where(ArenaPick.user_address == req.user_address)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    now = datetime.utcnow()
    lock_until = now + timedelta(days=7)

    if existing:
        if existing.lock_until > now:
            raise HTTPException(status_code=400, detail="Pick is currently locked")
        
        existing.side = req.side
        existing.wager = req.wager
        existing.tx_hash = req.tx_hash
        existing.picked_at = now
        existing.lock_until = lock_until
    else:
        new_pick = ArenaPick(
            user_address=req.user_address,
            side=req.side,
            wager=req.wager,
            tx_hash=req.tx_hash,
            picked_at=now,
            lock_until=lock_until
        )
        db.add(new_pick)
    
    await db.commit()
    return {"status": "success"}

@router.get("/stats/{address}", response_model=UserStatsResponse)
async def get_user_stats(address: str, db: AsyncSession = Depends(get_db)):
    # 1. Get Pick Info
    pick_stmt = select(ArenaPick).where(ArenaPick.user_address == address)
    pick_res = await db.execute(pick_stmt)
    pick = pick_res.scalar_one_or_none()

    # 2. Get Leaderboard Info
    lb_stmt = select(ArenaLeaderboard).where(ArenaLeaderboard.user_address == address)
    lb_res = await db.execute(lb_stmt)
    lb = lb_res.scalar_one_or_none()

    # 3. Get Points (Rewards)
    rew_stmt = select(ArenaReward).where(ArenaReward.user_address == address)
    rew_res = await db.execute(rew_stmt)
    rewards = rew_res.scalars().all()
    total_points = sum(r.amount for r in rewards)

    return UserStatsResponse(
        rank=lb.rank if lb else None,
        pnl=lb.pnl if lb else 0.0,
        roi=lb.roi if lb else 0.0,
        wager=pick.wager if pick else 0.0,
        points=total_points
    )

@router.get("/leaderboard")
async def get_arena_leaderboard(side: str = "human", db: AsyncSession = Depends(get_db)):
    stmt = select(ArenaLeaderboard).where(ArenaLeaderboard.side == side).order_by(ArenaLeaderboard.rank.asc()).limit(100)
    result = await db.execute(stmt)
    return result.scalars().all()
