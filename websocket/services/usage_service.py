import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from sqlalchemy import select, func, desc

from database.models import AIUsageLog, DailyUsageSnapshot

logger = logging.getLogger(__name__)

class UsageService:
    """Service to track and report AI usage across models"""
    
    def __init__(self, db_session=None):
        self.db = db_session

    async def log_usage(self, user_address: str, model: str, input_tokens: int, output_tokens: int, cost: float, session_id: Optional[str] = None):
        """Log an individual AI request and update daily snapshot"""
        if not self.db:
            logger.warning("UsageService: No DB session provided, usage not logged.")
            return

        try:
            log = AIUsageLog(
                user_address=user_address,
                session_id=session_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            )
            self.db.add(log)
            
            # Update daily snapshot
            snapshot_date = datetime.utcnow().date()
            result = await self.db.execute(
                select(DailyUsageSnapshot)
                .filter(DailyUsageSnapshot.user_address == user_address, DailyUsageSnapshot.date == snapshot_date)
            )
            snapshot = result.scalars().first()
            
            if snapshot:
                snapshot.total_tokens += (input_tokens + output_tokens)
                snapshot.total_cost += cost
                snapshot.request_count += 1
            else:
                new_snapshot = DailyUsageSnapshot(
                    user_address=user_address,
                    date=snapshot_date,
                    total_tokens=(input_tokens + output_tokens),
                    total_cost=cost,
                    request_count=1,
                )
                self.db.add(new_snapshot)
            
            await self.db.commit()
        except Exception as e:
            logger.error(f"Error logging usage: {e}")
            await self.db.rollback()

    async def get_user_stats(self, user_address: str) -> Dict[str, Any]:
        """Get aggregated stats for a user"""
        if not self.db: return {"total_cost": 0, "total_tokens": 0, "request_count": 0, "credit_balance": 0}
        
        try:
            result = await self.db.execute(
                select(
                    func.sum(DailyUsageSnapshot.total_cost).label("total_cost"),
                    func.sum(DailyUsageSnapshot.total_tokens).label("total_tokens"),
                    func.sum(DailyUsageSnapshot.request_count).label("request_count")
                ).filter(DailyUsageSnapshot.user_address == user_address)
            )
            row = result.fetchone()
            
            # Mock credit balance logic
            total_cost = float(row.total_cost or 0)
            credit_balance = max(0, 100.0 - total_cost) # Default $100 budget
            
            return {
                "total_cost": total_cost,
                "total_tokens": int(row.total_tokens or 0),
                "request_count": int(row.request_count or 0),
                "credit_balance": credit_balance
            }
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {"total_cost": 0, "total_tokens": 0, "request_count": 0, "credit_balance": 0}

    async def get_history(self, user_address: str, limit: int = 50, offset: int = 0) -> List[AIUsageLog]:
        """Get historical usage logs"""
        if not self.db: return []
        
        try:
            result = await self.db.execute(
                select(AIUsageLog)
                .filter(AIUsageLog.user_address == user_address)
                .order_by(desc(AIUsageLog.created_at))
                .limit(limit)
                .offset(offset)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    async def get_chart_data(self, user_address: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily usage data for charts"""
        if not self.db: return []
        
        try:
            start_date = date.today() - timedelta(days=days)
            result = await self.db.execute(
                select(DailyUsageSnapshot)
                .filter(DailyUsageSnapshot.user_address == user_address, DailyUsageSnapshot.date >= start_date)
                .order_by(DailyUsageSnapshot.date)
            )
            snapshots = result.scalars().all()
            
            return [
                {
                    "date": s.date.strftime("%Y-%m-%d"),
                    "cost": s.total_cost,
                    "tokens": s.total_tokens,
                    "requests": s.request_count
                }
                for s in snapshots
            ]
        except Exception as e:
            logger.error(f"Error getting chart data: {e}")
            return []

# Singleton instance
usage_service = UsageService()
