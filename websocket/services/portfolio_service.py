"""
Portfolio Service - Calculate and track portfolio value over time
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Optional
import logging

from database.models import Position, Order, PortfolioSnapshot, FundingHistory, LedgerAccount
from database.connection import get_db

logger = logging.getLogger(__name__)

from sqlalchemy import select

class PortfolioService:
    """Service for calculating and managing portfolio values"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def calculate_portfolio_value(self, user_address: str) -> Dict[str, float]:
        """
        Calculate current portfolio value for a user using Ledger State
        """
        logger.info(f"Calculating portfolio value for {user_address}")
        
        # 1. Get Balance from Ledger
        result = await self.db.execute(select(LedgerAccount).where(LedgerAccount.address == user_address.lower()))
        ledger = result.scalar_one_or_none()
        
        cash_balance = ledger.balance if ledger else 0.0
        locked_margin = ledger.locked_margin if ledger else 0.0
        realized_pnl = ledger.realized_pnl if ledger else 0.0
        
        # 2. Get all open positions
        result = await self.db.execute(
            select(Position).where(
                Position.user_address == user_address.lower(),
                Position.status == 'OPEN'
            )
        )
        positions = result.scalars().all()
        
        position_value = sum(p.margin_used for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        
        portfolio_value = cash_balance + unrealized_pnl
        
        return {
            'portfolio_value': portfolio_value,
            'cash_balance': cash_balance - locked_margin,
            'locked_margin': locked_margin,
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
                user_address=user_address.lower(),
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
    
    async def get_portfolio_history(
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
        
        stmt = select(PortfolioSnapshot).where(
            func.lower(PortfolioSnapshot.user_address) == user_address.lower()
        )
        
        if cutoff_time:
            stmt = stmt.where(PortfolioSnapshot.timestamp >= cutoff_time)
        
        stmt = stmt.order_by(PortfolioSnapshot.timestamp).limit(limit)
        
        result = await self.db.execute(stmt)
        snapshots = result.scalars().all()
        
        return [
            {
                'timestamp': s.timestamp.isoformat(),
                'value': s.portfolio_value,
                'unrealized_pnl': s.unrealized_pnl,
                'realized_pnl': s.realized_pnl
            }
            for s in snapshots
        ]

    async def get_funding_history(self, user_address: str, type: Optional[str] = None) -> List[Dict]:
        """
        Get deposit/withdraw history
        """
        stmt = select(FundingHistory).where(
            func.lower(FundingHistory.user_address) == user_address.lower()
        )

        if type:
            stmt = stmt.where(FundingHistory.type == type)

        stmt = stmt.order_by(FundingHistory.timestamp.desc())
        
        result = await self.db.execute(stmt)
        history = result.scalars().all()

        return [
            {
                "id": str(h.id),
                "type": h.type,
                "asset": h.asset,
                "amount": h.amount,
                "txHash": h.tx_hash,
                "status": h.status,
                "timestamp": h.timestamp.isoformat()
            }
            for h in history
        ]

    async def create_funding_record(self, user_address: str, type: str, asset: str, amount: float, tx_hash: str, status: str = 'Completed'):
        """Record a new deposit or withdrawal"""
        try:
            record = FundingHistory(
                user_address=user_address.lower(),
                type=type,
                asset=asset,
                amount=amount,
                tx_hash=tx_hash,
                status=status
            )
            self.db.add(record)
            await self.db.commit()
            return record
        except Exception as e:
            logger.error(f"Failed to save funding record: {e}")
            await self.db.rollback()
            raise
    
    async def _calculate_realized_pnl(self, user_address: str) -> float:
        """
        Calculate realized PNL from closed positions
        """
        stmt = select(
            func.sum(
                func.case(
                    (Order.side == 'sell', Order.notional_usd),
                    else_=-Order.notional_usd
                )
            )
        ).where(
            func.lower(Order.user_address) == user_address.lower(),
            Order.status == 'filled'
        )
        
        result = await self.db.execute(stmt)
        return float(result.scalar() or 0)
    
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
        stmt = select(Position.user_address).distinct()
        result = await self.db.execute(stmt)
        active_users = result.all()
        
        logger.info(f"Creating snapshots for {len(active_users)} active users")
        
        for (user_address,) in active_users:
            await self.save_snapshot(user_address)
        
        logger.info("Portfolio snapshots completed")
