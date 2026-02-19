from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
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
    account_value: float = 0.0

class LeaderboardEntry(BaseModel):
    rank: int
    user_address: str
    pnl: float
    roi: float
    volume: float

class LeaderboardResponse(BaseModel):
    data: List[LeaderboardEntry]
    pagination: dict

@router.post("/pick")
async def sync_pick(req: PickRequest, db: AsyncSession = Depends(get_db)):
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
    address_lower = address.lower()
    
    pick_stmt = select(ArenaPick).where(ArenaPick.user_address == address_lower)
    pick_res = await db.execute(pick_stmt)
    pick = pick_res.scalar_one_or_none()

    lb_stmt = select(ArenaLeaderboard).where(ArenaLeaderboard.user_address == address_lower)
    lb_res = await db.execute(lb_stmt)
    lb = lb_res.scalar_one_or_none()

    rew_stmt = select(ArenaReward).where(ArenaReward.user_address == address_lower)
    rew_res = await db.execute(rew_stmt)
    rewards = rew_res.scalars().all()
    total_points = sum(r.amount for r in rewards)

    return UserStatsResponse(
        rank=lb.rank if lb else None,
        pnl=lb.pnl if lb else 0.0,
        roi=lb.roi if lb else 0.0,
        wager=pick.wager if pick else 0.0,
        points=total_points,
        account_value=1000.0 + (lb.pnl if lb else 0.0)
    )

@router.get("/rank/{address}")
async def get_user_rank(address: str, side: str = "human", db: AsyncSession = Depends(get_db)):
    address_lower = address.lower()
    
    lb_stmt = select(ArenaLeaderboard).where(
        ArenaLeaderboard.user_address == address_lower,
        ArenaLeaderboard.side == side
    )
    lb_res = await db.execute(lb_stmt)
    lb = lb_res.scalar_one_or_none()
    
    if lb:
        return {
            "rank": lb.rank,
            "pnl": lb.pnl,
            "roi": lb.roi,
            "volume": lb.volume
        }
    
    total_stmt = select(func.count()).select_from(ArenaLeaderboard).where(ArenaLeaderboard.side == side)
    total_res = await db.execute(total_stmt)
    total = total_res.scalar() or 0
    
    return {
        "rank": total + 1,
        "pnl": 0.0,
        "roi": 0.0,
        "volume": 0.0
    }

@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_arena_leaderboard(
    side: str = "human", 
    page: int = 1, 
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * limit
    
    count_stmt = select(func.count()).select_from(ArenaLeaderboard).where(ArenaLeaderboard.side == side)
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0
    
    stmt = (
        select(ArenaLeaderboard)
        .where(ArenaLeaderboard.side == side)
        .order_by(ArenaLeaderboard.pnl.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    
    data = []
    for idx, row in enumerate(rows):
        actual_rank = offset + idx + 1
        data.append(LeaderboardEntry(
            rank=actual_rank,
            user_address=row.user_address,
            pnl=row.pnl,
            roi=row.roi,
            volume=row.volume
        ))
    
    return LeaderboardResponse(
        data=data,
        pagination={
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if limit > 0 else 1
        }
    )
