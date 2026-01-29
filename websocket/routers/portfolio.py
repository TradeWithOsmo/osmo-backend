"""
Portfolio API Routes
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from database.connection import get_db
from services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

@router.get("/{user_address}/history")
async def get_portfolio_history(
    user_address: str,
    timeframe: str = Query('1d', regex='^(1d|7d|30d|all)$'),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Get portfolio value history for charting
    
    Args:
        user_address: User wallet address
        timeframe: '1d', '7d', '30d', or 'all'
        limit: Max data points (default 500, max 1000)
    
    Returns:
        {
            "data": [
                {
                    "timestamp": "2026-01-29T10:00:00Z",
                    "value": 1000.00,
                    "unrealized_pnl": 50.00,
                    "realized_pnl": 100.00
                }
            ]
        }
    """
    service = PortfolioService(db)
    
    history = service.get_portfolio_history(
        user_address=user_address,
        timeframe=timeframe,
        limit=limit
    )
    
    return {"data": history}


@router.get("/{user_address}/current")
async def get_current_portfolio_value(
    user_address: str,
    db: Session = Depends(get_db)
):
    """
    Get current portfolio value and metrics
    
    Returns:
        {
            "portfolio_value": 1050.00,
            "cash_balance": 1000.00,
            "position_value": 500.00,
            "unrealized_pnl": 50.00,
            "realized_pnl": 100.00
        }
    """
    service = PortfolioService(db)
    
    metrics = await service.calculate_portfolio_value(user_address)
    
    return metrics


@router.post("/{user_address}/snapshot")
async def create_portfolio_snapshot(
    user_address: str,
    db: Session = Depends(get_db)
):
    """
    Manually trigger a portfolio snapshot
    (Normally run by background task)
    """
    service = PortfolioService(db)
    
    await service.save_snapshot(user_address)
    
    return {
        "status": "success",
        "message": f"Portfolio snapshot created for {user_address}"
    }


@router.post("/snapshot/all")
async def snapshot_all_users(db: Session = Depends(get_db)):
    """
    Create snapshots for all active users
    (Cron job endpoint)
    """
    service = PortfolioService(db)
    
    await service.snapshot_all_active_users()
    
    return {
        "status": "success",
        "message": "Portfolio snapshots created for all active users"
    }
