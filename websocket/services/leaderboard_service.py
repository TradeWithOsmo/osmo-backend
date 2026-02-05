"""
Leaderboard Service - Calculate and store trader/agent rankings
"""
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_, or_, select, case
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Optional
import logging

from database.models import Order, Position, LeaderboardSnapshot, ModelLeaderboardSnapshot

logger = logging.getLogger(__name__)

class LeaderboardService:
    """Service for calculating and managing leaderboard data"""
    
    TIMEFRAMES = {
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30),
        'all': None  # No time limit
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def calculate_trader_leaderboard(self, timeframe: str = '24h') -> List[Dict]:
        """
        Calculate trader leaderboard for given timeframe
        Returns: List of trader data with rankings
        """
        logger.info(f"Calculating trader leaderboard for {timeframe}")
        
        # Get time cutoff
        cutoff_time = self._get_cutoff_time(timeframe)
        
        # Query all filled orders within timeframe
        stmt = select(
            Order.user_address,
            func.sum(Order.notional_usd).label('volume'),
            func.count(Order.id).label('trade_count'),
            func.max(Order.agent_model).label('agent_model')
        ).where(
            Order.status.in_(['filled', 'FILLED'])
        )
        
        if cutoff_time:
            stmt = stmt.where(Order.filled_at >= cutoff_time)
        
        stmt = stmt.group_by(Order.user_address)
        
        result = await self.db.execute(stmt)
        rows = result.all()
        
        traders_data = []
        for row in rows:
            user_address = row.user_address
            
            # Get current positions for this user
            pos_stmt = select(Position).where(Position.user_address == user_address)
            pos_result = await self.db.execute(pos_stmt)
            positions = pos_result.scalars().all()
            
            # Calculate metrics
            account_value = sum(p.margin_used for p in positions)
            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
            realized_pnl = await self._calculate_realized_pnl(user_address, cutoff_time)
            
            # Win rate calculation
            win_count_stmt = select(func.count(Order.id)).where(
                Order.user_address == user_address,
                Order.status.in_(['filled', 'FILLED']),
                Order.realized_pnl > 0
            )
            if cutoff_time:
                win_count_stmt = win_count_stmt.where(Order.filled_at >= cutoff_time)
            
            win_count_result = await self.db.execute(win_count_stmt)
            win_count = win_count_result.scalar() or 0
            win_rate = (win_count / row.trade_count * 100) if row.trade_count > 0 else 0
            
            total_pnl = unrealized_pnl + realized_pnl
            roi = (total_pnl / account_value * 100) if account_value > 0 else 0
            
            traders_data.append({
                'user_address': user_address,
                'account_value': account_value,
                'pnl': total_pnl,
                'roi': roi,
                'volume': float(row.volume or 0),
                'agent_model': row.agent_model,  # Will be None if manual trader
                'trade_count': row.trade_count,
                'win_rate': win_rate
            })
        
        # Sort by PNL descending
        traders_data.sort(key=lambda x: x['pnl'], reverse=True)
        
        # Assign ranks
        for idx, trader in enumerate(traders_data, start=1):
            trader['rank'] = idx
        
        return traders_data
    
    async def calculate_model_leaderboard(self, timeframe: str = '24h') -> List[Dict]:
        """
        Calculate agent model leaderboard (global aggregation)
        Returns: List of model performance data
        """
        logger.info(f"Calculating model leaderboard for {timeframe}")
        
        cutoff_time = self._get_cutoff_time(timeframe)
        
        # Query agent trades grouped by model
        stmt = select(
            Order.agent_model,
            func.count(func.distinct(Order.user_address)).label('total_users'),
            func.sum(Order.notional_usd).label('volume'),
        ).where(
            Order.status.in_(['filled', 'FILLED']),
            Order.is_agent_trade == True,
            Order.agent_model.isnot(None)
        )
        
        if cutoff_time:
            stmt = stmt.where(Order.filled_at >= cutoff_time)
        
        stmt = stmt.group_by(Order.agent_model)
        
        result = await self.db.execute(stmt)
        rows = result.all()
        
        models_data = []
        for row in rows:
            agent_model = row.agent_model
            
            # Get all users using this model
            users_stmt = select(Order.user_address).where(
                Order.agent_model == agent_model,
                Order.is_agent_trade == True,
                Order.status.in_(['filled', 'FILLED'])
            ).distinct()
            
            if cutoff_time:
                users_stmt = users_stmt.where(Order.filled_at >= cutoff_time)
            
            users_result = await self.db.execute(users_stmt)
            users = users_result.scalars().all()
            
            # Aggregate metrics across all users of this model
            total_pnl = 0
            total_account_value = 0
            
            for user_address in users:
                pos_stmt = select(Position).where(Position.user_address == user_address)
                pos_result = await self.db.execute(pos_stmt)
                positions = pos_result.scalars().all()
                
                account_value = sum(p.margin_used for p in positions)
                unrealized_pnl = sum(p.unrealized_pnl for p in positions)
                realized_pnl = await self._calculate_realized_pnl(user_address, cutoff_time)
                
                total_account_value += account_value
                total_pnl += (unrealized_pnl + realized_pnl)
            
            roi = (total_pnl / total_account_value * 100) if total_account_value > 0 else 0
            
            # Model-wide stats
            stmt_stats = select(
                func.count(Order.id).label('total_trades'),
                func.count(Order.id).filter(Order.realized_pnl > 0).label('wins')
            ).where(
                Order.agent_model == agent_model,
                Order.is_agent_trade == True,
                Order.status.in_(['filled', 'FILLED'])
            )
            if cutoff_time:
                stmt_stats = stmt_stats.where(Order.filled_at >= cutoff_time)
            
            stats_result = await self.db.execute(stmt_stats)
            stats = stats_result.one()
            
            win_rate = (stats.wins / stats.total_trades * 100) if stats.total_trades > 0 else 0
            
            models_data.append({
                'agent_model': agent_model,
                'total_users': row.total_users,
                'account_value': total_account_value,
                'pnl': total_pnl,
                'roi': roi,
                'volume': float(row.volume or 0),
                'trade_count': stats.total_trades,
                'win_rate': win_rate
            })
        
        # Sort by PNL descending
        models_data.sort(key=lambda x: x['pnl'], reverse=True)
        
        # Assign ranks
        for idx, model in enumerate(models_data, start=1):
            model['rank'] = idx
        
        return models_data
    
    async def save_snapshots(self, snapshot_date: Optional[date] = None):
        """
        Calculate and save daily snapshots for all timeframes
        Should be run by a daily cronjob
        """
        if snapshot_date is None:
            snapshot_date = date.today()
        
        logger.info(f"Saving leaderboard snapshots for {snapshot_date}")
        
        for timeframe in self.TIMEFRAMES.keys():
            # Calculate trader leaderboard
            traders = await self.calculate_trader_leaderboard(timeframe)
            
            # Save trader snapshots
            for trader in traders:
                snapshot = LeaderboardSnapshot(
                    snapshot_date=snapshot_date,
                    timeframe=timeframe,
                    user_address=trader['user_address'],
                    account_value=trader['account_value'],
                    pnl=trader['pnl'],
                    roi=trader['roi'],
                    volume=trader['volume'],
                    trade_count=trader['trade_count'],
                    win_rate=trader['win_rate'],
                    agent_model=trader['agent_model'],
                    rank=trader['rank']
                )
                await self.db.merge(snapshot)
            
            # Calculate model leaderboard
            models = await self.calculate_model_leaderboard(timeframe)
            
            # Save model snapshots
            for model in models:
                snapshot = ModelLeaderboardSnapshot(
                    snapshot_date=snapshot_date,
                    timeframe=timeframe,
                    agent_model=model['agent_model'],
                    total_users=model['total_users'],
                    account_value=model['account_value'],
                    pnl=model['pnl'],
                    roi=model['roi'],
                    volume=model['volume'],
                    trade_count=model['trade_count'],
                    win_rate=model['win_rate'],
                    rank=model['rank']
                )
                await self.db.merge(snapshot)
        
        await self.db.commit()
        logger.info("Leaderboard snapshots saved successfully")
    
    async def get_trader_leaderboard(
        self, 
        timeframe: str = '24h',
        snapshot_date: Optional[date] = None,
        page: int = 1,
        limit: int = 20,
        ai_only: bool = False
    ) -> Dict:
        """Get trader leaderboard from snapshots"""
        if snapshot_date is None:
            snapshot_date = date.today()
        
        stmt = select(LeaderboardSnapshot).where(
            LeaderboardSnapshot.snapshot_date == snapshot_date,
            LeaderboardSnapshot.timeframe == timeframe
        )
        
        # Filter for AI traders only if requested
        if ai_only:
            stmt = stmt.where(LeaderboardSnapshot.agent_model.isnot(None))
        
        stmt = stmt.order_by(LeaderboardSnapshot.rank)
        
        # Count total (separate query needed for async)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar()
        
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)
        
        result = await self.db.execute(stmt)
        snapshots = result.scalars().all()
        
        return {
            'data': [
                {
                    'rank': s.rank,
                    'trader': s.user_address,
                    'accountValue': s.account_value,
                    'pnl': s.pnl,
                    'roi': s.roi,
                    'volume': s.volume,
                    'tradeCount': s.trade_count,
                    'winRate': s.win_rate,
                    'agentModel': s.agent_model
                }
                for s in snapshots
            ],
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        }
    
    async def get_model_leaderboard(
        self,
        timeframe: str = '24h',
        snapshot_date: Optional[date] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict:
        """Get model leaderboard from snapshots"""
        if snapshot_date is None:
            snapshot_date = date.today()
        
        stmt = select(ModelLeaderboardSnapshot).where(
            ModelLeaderboardSnapshot.snapshot_date == snapshot_date,
            ModelLeaderboardSnapshot.timeframe == timeframe
        ).order_by(ModelLeaderboardSnapshot.rank)
        
        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar()
        
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)
        
        result = await self.db.execute(stmt)
        snapshots = result.scalars().all()
        
        return {
            'data': [
                {
                    'rank': s.rank,
                    'agentName': s.agent_model,
                    'totalUsers': s.total_users,
                    'accountValue': s.account_value,
                    'pnl': s.pnl,
                    'roi': s.roi,
                    'volume': s.volume,
                    'tradeCount': s.trade_count,
                    'winRate': s.win_rate
                }
                for s in snapshots
            ],
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        }
    
    def _get_cutoff_time(self, timeframe: str) -> Optional[datetime]:
        """Get cutoff datetime for given timeframe"""
        delta = self.TIMEFRAMES.get(timeframe)
        if delta is None:
            return None
        return datetime.utcnow() - delta
    
    async def _calculate_realized_pnl(self, user_address: str, cutoff_time: Optional[datetime]) -> float:
        """Calculate realized PNL from closed positions"""
        # Query filled orders to estimate realized PNL
        stmt = select(
            func.sum(
                case(
                    (Order.side == 'sell', Order.notional_usd),
                    else_=-Order.notional_usd
                )
            )
        ).where(
            Order.user_address == user_address,
            Order.status.in_(['filled', 'FILLED'])
        )
        
        if cutoff_time:
            stmt = stmt.where(Order.filled_at >= cutoff_time)
        
        result = await self.db.execute(stmt)
        return float(result.scalar() or 0)
