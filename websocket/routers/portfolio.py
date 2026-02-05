"""
Portfolio API Routes
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database.connection import get_db
from services.portfolio_service import PortfolioService

router = APIRouter(tags=["portfolio"])

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
    
    history = await service.get_portfolio_history(
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


@router.get("/{user_address}/funding")
async def get_funding_history(
    user_address: str,
    type: Optional[str] = Query(None, regex='^(Deposit|Withdraw)$'),
    db: Session = Depends(get_db)
):
    """
    Get deposit/withdrawal history from Indexed DB.
    """
    service = PortfolioService(db)
    history = await service.get_funding_history(user_address, type)
    return {"data": history}


@router.get("/{user_address}/trades")
async def get_trade_history(
    user_address: str,
    db: Session = Depends(get_db)
):
    """
    Get trade history (filled orders)
    """
    try:
        from services.order_service import OrderService
        from config import settings
        service = OrderService()
        
        # We use get_user_orders with status='filled'
        orders = await service.get_user_orders(user_address, status='filled')
        
        # Format for TradeHistoryData frontend model
        trades = []
        builder_fee_bps = getattr(settings, 'OSMO_BUILDER_FEE_BPS', 50)
        
        for o in orders:
            pnl = o.get('realized_pnl') or 0
            notional = o.get('notional_usd', 0)
            fee = (notional * builder_fee_bps) / 10000
            
            trades.append({
                "id": o['id'],
                "time": o['filled_at'] or o['created_at'] or datetime.utcnow().isoformat(),
                "symbol": o['symbol'],
                "direction": "Long" if o['side'].lower() == 'buy' else "Short",
                "price": o['avg_fill_price'] or o['price'] or 0,
                "size": o['size'],
                "sizeAsset": o['symbol'].split('-')[0] if '-' in o['symbol'] else o['symbol'],
                "tradeValue": notional,
                "tradeValueAsset": "USDC",
                "fee": fee,
                "feeAsset": "USDC",
                "closedPnl": pnl,
                "closedPnlAsset": "USDC"
            })
            
        return {"data": trades}
    except Exception as e:
        import traceback
        print(f"Error in get_trade_history: {e}")
        print(traceback.format_exc())
        return {"error": str(e), "data": []}


@router.post("/{user_address}/funding")
async def record_funding_transaction(
    user_address: str,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Record a new funding transaction (Internal/Webhook use)
    Payload: { "type": "Deposit", "asset": "USDC", "amount": 100, "txHash": "..." }
    """
    # Deprecated: We fetch on-chain now.
    # But keep endpoint for compatibility or manual overrides if needed.
    return {"status": "success", "message": "Transaction cached (but history uses on-chain source)"}
