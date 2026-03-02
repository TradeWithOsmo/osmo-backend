import os
from datetime import date
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from database.arena_models import ArenaLeaderboard, ArenaPick, ArenaReward
from database.connection import get_db
from database.models import Order
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.leaderboard_service import LeaderboardService
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
ARENA_WINDOW_DAYS = 7
MAX_OVERALL_LIMIT = 1000
ARENA_BASE_CAPITAL = 1000.0


def _parse_event_end_utc() -> Optional[datetime]:
    raw = os.getenv("ARENA_END_ISO") or os.getenv("VITE_ARENA_END_ISO")
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def _get_active_window_bounds() -> tuple[datetime, datetime]:
    end_at = _parse_event_end_utc()
    if end_at:
        start_at = end_at - timedelta(days=ARENA_WINDOW_DAYS)
        return start_at, end_at

    # Dev fallback when event end is not configured: rolling 7-day eligibility.
    now = datetime.utcnow()
    start_at = now - timedelta(days=ARENA_WINDOW_DAYS)
    end_at = now + timedelta(days=ARENA_WINDOW_DAYS)
    return start_at, end_at


def _normalize_side(side: str) -> str:
    normalized = (side or "").strip().lower()
    if normalized not in {"human", "ai"}:
        raise HTTPException(
            status_code=400, detail="Invalid side. Use 'human' or 'ai'."
        )
    return normalized


def _build_order_metrics_subquery(window_start: datetime, window_end: datetime):
    order_time = func.coalesce(Order.filled_at, Order.updated_at, Order.created_at)
    return (
        select(
            func.lower(Order.user_address).label("user_address"),
            func.coalesce(func.sum(Order.realized_pnl), 0.0).label("pnl"),
            func.coalesce(func.sum(Order.notional_usd), 0.0).label("volume"),
            func.count(Order.id).label("trade_count"),
            func.coalesce(
                func.sum(case((Order.realized_pnl > 0, 1), else_=0)),
                0,
            ).label("win_count"),
        )
        .where(
            func.lower(Order.status).in_(["filled", "confirmed"]),
            order_time >= window_start,
            order_time <= window_end,
        )
        .group_by(func.lower(Order.user_address))
        .subquery()
    )


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
    trade_count: int = 0
    win_rate: float = 0.0


class LeaderboardResponse(BaseModel):
    data: List[LeaderboardEntry]
    pagination: dict


class OverallLeaderboardEntry(BaseModel):
    rank: int
    user_address: str
    total_points: float
    pnl: float
    roi: float
    volume: float
    trade_count: int = 0
    win_rate: float = 0.0
    side: Optional[str] = None


class OverallLeaderboardResponse(BaseModel):
    data: List[OverallLeaderboardEntry]
    pagination: dict


@router.get("/agents")
async def get_arena_agents_leaderboard(
    timeframe: str = "24h",
    snapshot_date: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """
    Backward-compatible agent leaderboard endpoint used by frontend:
    /api/arena/agents?timeframe=...&page=...&limit=...
    """
    parsed_date = date.fromisoformat(snapshot_date) if snapshot_date else None
    service = LeaderboardService(db)
    return await service.get_model_leaderboard(
        timeframe=timeframe,
        snapshot_date=parsed_date,
        page=page,
        limit=limit,
    )


@router.post("/pick")
async def sync_pick(req: PickRequest, db: AsyncSession = Depends(get_db)):
    user_address = req.user_address.lower()
    side = _normalize_side(req.side)
    now = datetime.utcnow()
    window_start, window_end = _get_active_window_bounds()

    if now > window_end:
        raise HTTPException(status_code=400, detail="Arena window has ended")

    stmt = select(ArenaPick).where(func.lower(ArenaPick.user_address) == user_address)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.user_address = user_address
        is_current_window_pick = (
            existing.picked_at and window_start <= existing.picked_at <= window_end
        )
        if is_current_window_pick:
            raise HTTPException(
                status_code=400, detail="Pick already submitted for current window"
            )

        existing.side = side
        existing.wager = req.wager
        existing.tx_hash = req.tx_hash
        existing.picked_at = now
        existing.lock_until = window_end
        existing.status = "confirmed"
    else:
        new_pick = ArenaPick(
            user_address=user_address,
            side=side,
            wager=req.wager,
            tx_hash=req.tx_hash,
            picked_at=now,
            lock_until=window_end,
            status="confirmed",
        )
        db.add(new_pick)

    # Ensure each picker is represented in historical leaderboard.
    lb_stmt = select(ArenaLeaderboard).where(
        func.lower(ArenaLeaderboard.user_address) == user_address
    )
    lb_res = await db.execute(lb_stmt)
    lb = lb_res.scalar_one_or_none()
    if lb:
        lb.side = side
        lb.last_updated = now
    else:
        db.add(
            ArenaLeaderboard(
                user_address=user_address,
                side=side,
                pnl=0.0,
                roi=0.0,
                volume=0.0,
                rank=None,
                last_updated=now,
            )
        )

    await db.commit()
    return {"status": "success", "window_end": window_end.isoformat()}


@router.get("/stats/{address}", response_model=UserStatsResponse)
async def get_user_stats(address: str, db: AsyncSession = Depends(get_db)):
    address_lower = address.lower()

    pick_stmt = select(ArenaPick).where(
        func.lower(ArenaPick.user_address) == address_lower
    )
    pick_res = await db.execute(pick_stmt)
    pick = pick_res.scalar_one_or_none()

    lb_stmt = select(ArenaLeaderboard).where(
        func.lower(ArenaLeaderboard.user_address) == address_lower
    )
    lb_res = await db.execute(lb_stmt)
    lb = lb_res.scalar_one_or_none()

    rew_stmt = select(ArenaReward).where(
        func.lower(ArenaReward.user_address) == address_lower
    )
    rew_res = await db.execute(rew_stmt)
    rewards = rew_res.scalars().all()
    total_points = sum(r.amount for r in rewards)

    return UserStatsResponse(
        rank=lb.rank if lb else None,
        pnl=lb.pnl if lb else 0.0,
        roi=lb.roi if lb else 0.0,
        wager=pick.wager if pick else 0.0,
        points=total_points,
        account_value=1000.0 + (lb.pnl if lb else 0.0),
    )


@router.get("/rank/{address}")
async def get_user_rank(
    address: str, side: str = "human", db: AsyncSession = Depends(get_db)
):
    address_lower = address.lower()
    normalized_side = _normalize_side(side)
    window_start, window_end = _get_active_window_bounds()
    order_metrics_subq = _build_order_metrics_subquery(window_start, window_end)

    active_pick_stmt = select(ArenaPick.user_address).where(
        func.lower(ArenaPick.user_address) == address_lower,
        ArenaPick.side == normalized_side,
        ArenaPick.picked_at >= window_start,
        ArenaPick.picked_at <= window_end,
    )
    active_pick = (await db.execute(active_pick_stmt)).scalar_one_or_none()

    total_stmt = select(func.count()).select_from(
        select(ArenaPick.user_address)
        .where(
            ArenaPick.side == normalized_side,
            ArenaPick.picked_at >= window_start,
            ArenaPick.picked_at <= window_end,
        )
        .subquery()
    )
    total = (await db.execute(total_stmt)).scalar() or 0

    if not active_pick:
        return {"rank": total + 1, "pnl": 0.0, "roi": 0.0, "volume": 0.0}

    user_metrics_stmt = select(
        order_metrics_subq.c.pnl,
        order_metrics_subq.c.volume,
    ).where(order_metrics_subq.c.user_address == address_lower)
    user_metrics = (await db.execute(user_metrics_stmt)).first()

    lb_stmt = select(ArenaLeaderboard).where(
        func.lower(ArenaLeaderboard.user_address) == address_lower
    )
    lb = (await db.execute(lb_stmt)).scalar_one_or_none()
    user_pnl = float(user_metrics.pnl) if user_metrics else float(lb.pnl) if lb else 0.0
    user_volume = (
        float(user_metrics.volume) if user_metrics else float(lb.volume) if lb else 0.0
    )
    user_roi = (user_pnl / ARENA_BASE_CAPITAL) * 100.0

    higher_stmt = (
        select(func.count())
        .select_from(ArenaPick)
        .outerjoin(
            order_metrics_subq,
            order_metrics_subq.c.user_address == func.lower(ArenaPick.user_address),
        )
        .outerjoin(
            ArenaLeaderboard,
            func.lower(ArenaLeaderboard.user_address)
            == func.lower(ArenaPick.user_address),
        )
        .where(
            ArenaPick.side == normalized_side,
            ArenaPick.picked_at >= window_start,
            ArenaPick.picked_at <= window_end,
            func.coalesce(order_metrics_subq.c.pnl, ArenaLeaderboard.pnl, 0.0)
            > user_pnl,
        )
    )
    higher = (await db.execute(higher_stmt)).scalar() or 0

    return {
        "rank": int(higher) + 1,
        "pnl": user_pnl,
        "roi": user_roi,
        "volume": user_volume,
    }


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_arena_leaderboard(
    side: str = "human",
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    normalized_side = _normalize_side(side)
    window_start, window_end = _get_active_window_bounds()
    offset = (page - 1) * limit
    order_metrics_subq = _build_order_metrics_subquery(window_start, window_end)

    active_pick_subq = (
        select(func.lower(ArenaPick.user_address).label("user_address"))
        .where(
            ArenaPick.side == normalized_side,
            ArenaPick.picked_at >= window_start,
            ArenaPick.picked_at <= window_end,
        )
        .distinct()
        .subquery()
    )

    count_stmt = select(func.count()).select_from(active_pick_subq)
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    pnl_expr = func.coalesce(order_metrics_subq.c.pnl, ArenaLeaderboard.pnl, 0.0)
    volume_expr = func.coalesce(
        order_metrics_subq.c.volume, ArenaLeaderboard.volume, 0.0
    )
    trade_count_expr = func.coalesce(order_metrics_subq.c.trade_count, 0)
    win_count_expr = func.coalesce(order_metrics_subq.c.win_count, 0)
    roi_expr = (pnl_expr / ARENA_BASE_CAPITAL) * 100.0
    win_rate_expr = case(
        (trade_count_expr > 0, (win_count_expr * 100.0) / trade_count_expr),
        else_=0.0,
    )

    stmt = (
        select(
            active_pick_subq.c.user_address,
            pnl_expr.label("pnl"),
            roi_expr.label("roi"),
            volume_expr.label("volume"),
            trade_count_expr.label("trade_count"),
            win_rate_expr.label("win_rate"),
        )
        .select_from(active_pick_subq)
        .outerjoin(
            order_metrics_subq,
            order_metrics_subq.c.user_address == active_pick_subq.c.user_address,
        )
        .outerjoin(
            ArenaLeaderboard,
            func.lower(ArenaLeaderboard.user_address)
            == active_pick_subq.c.user_address,
        )
        .order_by(
            pnl_expr.desc(),
            roi_expr.desc(),
            volume_expr.desc(),
            win_rate_expr.desc(),
            active_pick_subq.c.user_address.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    data = []
    for idx, row in enumerate(rows):
        actual_rank = offset + idx + 1
        data.append(
            LeaderboardEntry(
                rank=actual_rank,
                user_address=row.user_address,
                pnl=float(row.pnl or 0.0),
                roi=float(row.roi or 0.0),
                volume=float(row.volume or 0.0),
                trade_count=int(row.trade_count or 0),
                win_rate=float(row.win_rate or 0.0),
            )
        )

    return LeaderboardResponse(
        data=data,
        pagination={
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if limit > 0 else 1,
        },
    )


@router.get("/leaderboard/overall", response_model=OverallLeaderboardResponse)
async def get_overall_leaderboard(
    page: int = 1,
    limit: int = MAX_OVERALL_LIMIT,
    db: AsyncSession = Depends(get_db),
):
    if page < 1:
        page = 1
    limit = max(1, min(limit, MAX_OVERALL_LIMIT))
    offset = (page - 1) * limit
    window_start, window_end = _get_active_window_bounds()

    users_subq = (
        select(func.lower(ArenaLeaderboard.user_address).label("user_address"))
        .distinct()
        .subquery()
    )

    points_subq = (
        select(
            func.lower(ArenaReward.user_address).label("user_address"),
            func.coalesce(func.sum(ArenaReward.amount), 0.0).label("total_points"),
        )
        .group_by(func.lower(ArenaReward.user_address))
        .subquery()
    )

    lb_metrics_subq = (
        select(
            func.lower(ArenaLeaderboard.user_address).label("user_address"),
            func.max(ArenaLeaderboard.pnl).label("pnl"),
            func.max(ArenaLeaderboard.roi).label("roi"),
            func.max(ArenaLeaderboard.volume).label("volume"),
            func.max(ArenaLeaderboard.side).label("side"),
        )
        .group_by(func.lower(ArenaLeaderboard.user_address))
        .subquery()
    )
    order_metrics_subq = _build_order_metrics_subquery(window_start, window_end)

    pnl_expr = func.coalesce(order_metrics_subq.c.pnl, lb_metrics_subq.c.pnl, 0.0)
    volume_expr = func.coalesce(
        order_metrics_subq.c.volume, lb_metrics_subq.c.volume, 0.0
    )
    # Arena points are now aligned to realized 7D PNL (primary ranking basis).
    total_points_expr = pnl_expr
    trade_count_expr = func.coalesce(order_metrics_subq.c.trade_count, 0)
    win_count_expr = func.coalesce(order_metrics_subq.c.win_count, 0)
    roi_expr = (pnl_expr / ARENA_BASE_CAPITAL) * 100.0
    win_rate_expr = case(
        (trade_count_expr > 0, (win_count_expr * 100.0) / trade_count_expr),
        else_=0.0,
    )

    count_stmt = select(func.count()).select_from(users_subq)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(
            users_subq.c.user_address,
            total_points_expr.label("total_points"),
            pnl_expr.label("pnl"),
            roi_expr.label("roi"),
            volume_expr.label("volume"),
            trade_count_expr.label("trade_count"),
            win_rate_expr.label("win_rate"),
            lb_metrics_subq.c.side,
        )
        .select_from(users_subq)
        .outerjoin(points_subq, points_subq.c.user_address == users_subq.c.user_address)
        .outerjoin(
            lb_metrics_subq, lb_metrics_subq.c.user_address == users_subq.c.user_address
        )
        .outerjoin(
            order_metrics_subq,
            order_metrics_subq.c.user_address == users_subq.c.user_address,
        )
        .order_by(
            pnl_expr.desc(),
            roi_expr.desc(),
            volume_expr.desc(),
            win_rate_expr.desc(),
            users_subq.c.user_address.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    data = []
    for idx, row in enumerate(rows):
        data.append(
            OverallLeaderboardEntry(
                rank=offset + idx + 1,
                user_address=row.user_address,
                total_points=float(row.total_points or 0.0),
                pnl=float(row.pnl or 0.0),
                roi=float(row.roi or 0.0),
                volume=float(row.volume or 0.0),
                trade_count=int(row.trade_count or 0),
                win_rate=float(row.win_rate or 0.0),
                side=row.side,
            )
        )

    return OverallLeaderboardResponse(
        data=data,
        pagination={
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if limit > 0 else 1,
        },
    )
