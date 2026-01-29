"""
Leaderboard API Routes
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from database.connection import get_db
from services.leaderboard_service import LeaderboardService

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])

@router.get("/traders")
async def get_trader_leaderboard(
    timeframe: str = Query('24h', regex='^(24h|7d|30d|all)$'),
    snapshot_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    ai_only: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    Get trader leaderboard rankings
    
    Args:
        timeframe: '24h', '7d', '30d', or 'all'
        snapshot_date: Date in YYYY-MM-DD format (default: today)
        page: Page number
        limit: Items per page (max 100)
        ai_only: If True, only show traders using AI agents
    
    Returns:
        {
            "data": [
                {
                    "rank": 1,
                    "trader": "0xABC...123",
                    "accountValue": 50000.00,
                    "pnl": 5000.00,
                    "roi": 10.5,
                    "volume": 1000000.00,
                    "agentModel": "gpt-4o"  # null if manual trader
                }
            ],
            "pagination": {...}
        }
    """
    service = LeaderboardService(db)
    
    parsed_date = date.fromisoformat(snapshot_date) if snapshot_date else None
    
    return await service.get_trader_leaderboard(
        timeframe=timeframe,
        snapshot_date=parsed_date,
        page=page,
        limit=limit,
        ai_only=ai_only
    )

@router.get("/agents")
async def get_agent_leaderboard(
    timeframe: str = Query('24h', regex='^(24h|7d|30d|all)$'),
    snapshot_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get AI agent model leaderboard (global aggregation)
    
    Args:
        timeframe: '24h', '7d', '30d', or 'all'
        snapshot_date: Date in YYYY-MM-DD format (default: today)
        page: Page number
        limit: Items per page (max 100)
    
    Returns:
        {
            "data": [
                {
                    "rank": 1,
                    "agentName": "gpt-4o",
                    "totalUsers": 120,
                    "accountValue": 2500000.00,
                    "pnl": 500000.00,
                    "roi": 25.5,
                    "volume": 50000000.00
                }
            ],
            "pagination": {...}
        }
    """
    service = LeaderboardService(db)
    
    parsed_date = date.fromisoformat(snapshot_date) if snapshot_date else None
    
    return await service.get_model_leaderboard(
        timeframe=timeframe,
        snapshot_date=parsed_date,
        page=page,
        limit=limit
    )

@router.post("/refresh")
async def refresh_leaderboard_snapshots(
    snapshot_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Manually trigger leaderboard snapshot calculation
    (Normally run by daily cronjob)
    
    Args:
        snapshot_date: Date in YYYY-MM-DD format (default: today)
    """
    service = LeaderboardService(db)
    
    parsed_date = date.fromisoformat(snapshot_date) if snapshot_date else None
    
    await service.save_snapshots(snapshot_date=parsed_date)
    
    return {
        "status": "success",
        "message": f"Leaderboard snapshots calculated for {parsed_date or date.today()}"
    }
