"""
Portfolio Service - Calculate and track portfolio value over time
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Optional
import logging

from database.models import Position, Order, PortfolioSnapshot
from database.connection import get_db

logger = logging.getLogger(__name__)

class PortfolioService:
    """Service for calculating and managing portfolio values"""
    
    def __init__(self, db: Session):
        self.db =db
    
    async def calculate_portfolio_value(self, user_address: str) -> Dict[str, float]:
        """
        Calculate current portfolio value for a user
        
        Returns:
            {
                'portfolio_value': float,
                'cash_balance': float,
                'position_value': float,
                'unrealized_pnl': float,
                'realized_pnl': float
            }
        """
        logger.info(f"Calculating portfolio value for {user_address}")
        
        # Get all open positions
        positions = self.db.query(Position).filter(
            Position.user_address == user_address
        ).all()
        
        # Calculate metrics from positions
        position_value = sum(p.margin_used for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        
        # Calculate realized PNL from trade history
        realized_pnl = self._calculate_realized_pnl(user_address)
        
        # Get cash balance
        # TODO: This should come from exchange API or wallet balance
        # For now, we estimate it from account value
        # In production: cash_balance = await exchange_api.get_balance(user_address)
        cash_balance = position_value  # Simplified for now
        
        # Total portfolio value = Cash + Unrealized PNL
        portfolio_value = cash_balance + unrealized_pnl
        
        return {
            'portfolio_value': portfolio_value,
            'cash_balance': cash_balance,
            'position_value': position_value,
            'unrealized_pnl': unrealized_pnl,
            'realized_pnl': realized_pnl
        }
    
    async def save_snapshot(self, user_address: str):
        """
        Save current portfolio snapshot to database
        """
        try:
            metrics = await self.calculate_portfolio_value(user_address)
            
            snapshot = PortfolioSnapshot(
                user_address=user_address,
                timestamp=datetime.utcnow(),
                portfolio_value=metrics['portfolio_value'],
                cash_balance=metrics['cash_balance'],
                position_value=metrics['position_value'],
                unrealized_pnl=metrics['unrealized_pnl'],
                realized_pnl=metrics['realized_pnl']
            )
            
            self.db.add(snapshot)
            self.db.commit()
            
            logger.info(f"Saved portfolio snapshot for {user_address}: ${metrics['portfolio_value']:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot for {user_address}: {e}")
            self.db.rollback()
    
    def get_portfolio_history(
        self,
        user_address: str,
        timeframe: str = '1d',
        limit: int = 500
    ) -> List[Dict]:
        """
        Get portfolio value history for charting
        
        Args:
            user_address: User wallet address
            timeframe: '1d', '7d', '30d', 'all'
            limit: Max number of data points
        
        Returns:
            List of {timestamp, value} dicts
        """
        # Calculate time range
        cutoff_time = self._get_cutoff_time(timeframe)
        
        query = self.db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.user_address == user_address
        )
        
        if cutoff_time:
            query = query.filter(PortfolioSnapshot.timestamp >= cutoff_time)
        
        snapshots = query.order_by(
            PortfolioSnapshot.timestamp
        ).limit(limit).all()
        
        return [
            {
                'timestamp': s.timestamp.isoformat(),
                'value': s.portfolio_value,
                'unrealized_pnl': s.unrealized_pnl,
                'realized_pnl': s.realized_pnl
            }
            for s in snapshots
        ]
    
    def _calculate_realized_pnl(self, user_address: str) -> float:
        """
        Calculate realized PNL from closed positions
        This is simplified - in production you'd track closed positions separately
        """
        # Query filled orders to estimate realized PNL
        result = self.db.query(
            func.sum(
                func.case(
                    (Order.side == 'sell', Order.notional_usd),
                    else_=-Order.notional_usd
                )
            )
        ).filter(
            Order.user_address == user_address,
            Order.status == 'filled'
        ).scalar()
        
        return float(result or 0)
    
    def _get_cutoff_time(self, timeframe: str) -> Optional[datetime]:
        """Get cutoff datetime for given timeframe"""
        timeframes = {
            '1d': timedelta(days=1),
            '7d': timedelta(days=7),
            '30d': timedelta(days=30),
            'all': None
        }
        
        delta = timeframes.get(timeframe)
        if delta is None:
            return None
        
        return datetime.utcnow() - delta
    
    async def snapshot_all_active_users(self):
        """
        Create snapshots for all users with open positions
        Called by periodic background task
        """
        # Get unique users with open positions
        active_users = self.db.query(Position.user_address).distinct().all()
        
        logger.info(f"Creating snapshots for {len(active_users)} active users")
        
        for (user_address,) in active_users:
            await self.save_snapshot(user_address)
        
        logger.info("Portfolio snapshots completed")
