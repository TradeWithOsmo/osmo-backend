import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from sqlalchemy import select, func, desc

from database.models import AIUsageLog, DailyUsageSnapshot, UserEnabledModels, UserEnabledAgents
from database.connection import AsyncSessionLocal
import json

logger = logging.getLogger(__name__)

class UsageService:
    """Service to track and report AI usage across models"""
    
    def __init__(self, db_session=None):
        self.db = db_session  # Kept for backward compatibility, though not used in new methods

    @staticmethod
    def _normalize_user_address(user_address: str) -> str:
        return (user_address or "").strip().lower()

    @staticmethod
    def _normalize_enabled_ids(values: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for item in values or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    async def log_usage(self, user_address: str, model: str, input_tokens: int, output_tokens: int, cost: float, session_id: Optional[str] = None):
        """Log an individual AI request and update daily snapshot"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            logger.error("Error logging usage: user_address is empty")
            return
        try:
            async with AsyncSessionLocal() as session:
                log = AIUsageLog(
                    user_address=user_key,
                    session_id=session_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                )
                session.add(log)
                
                # Update daily snapshot
                snapshot_date = datetime.utcnow().date()
                result = await session.execute(
                    select(DailyUsageSnapshot)
                    .filter(
                        func.lower(DailyUsageSnapshot.user_address) == user_key,
                        DailyUsageSnapshot.date == snapshot_date
                    )
                )
                snapshot = result.scalars().first()
                
                if snapshot:
                    snapshot.total_tokens += (input_tokens + output_tokens)
                    snapshot.total_cost += cost
                    snapshot.request_count += 1
                else:
                    new_snapshot = DailyUsageSnapshot(
                        user_address=user_key,
                        date=snapshot_date,
                        total_tokens=(input_tokens + output_tokens),
                        total_cost=cost,
                        request_count=1,
                    )
                    session.add(new_snapshot)
                
                await session.commit()
        except Exception as e:
            logger.error(f"Error logging usage: {e}")

    async def get_user_stats(self, user_address: str) -> Dict[str, Any]:
        """Get aggregated stats for a user"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return {"total_cost": 0, "total_tokens": 0, "request_count": 0, "credit_balance": 0}
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        func.sum(DailyUsageSnapshot.total_cost).label("total_cost"),
                        func.sum(DailyUsageSnapshot.total_tokens).label("total_tokens"),
                        func.sum(DailyUsageSnapshot.request_count).label("request_count")
                    ).filter(func.lower(DailyUsageSnapshot.user_address) == user_key)
                )
                row = result.fetchone()
                
                # Mock credit balance logic
                total_cost = float(row.total_cost or 0) if row else 0
                total_tokens = int(row.total_tokens or 0) if row else 0
                request_count = int(row.request_count or 0) if row else 0
                credit_balance = max(0, 100.0 - total_cost) # Default $100 budget
                
                return {
                    "total_cost": total_cost,
                    "total_tokens": total_tokens,
                    "request_count": request_count,
                    "credit_balance": credit_balance
                }
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {"total_cost": 0, "total_tokens": 0, "request_count": 0, "credit_balance": 0}

    async def get_history(self, user_address: str, limit: int = 50, offset: int = 0) -> List[AIUsageLog]:
        """Get historical usage logs"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return []
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AIUsageLog)
                    .filter(func.lower(AIUsageLog.user_address) == user_key)
                    .order_by(desc(AIUsageLog.timestamp))
                    .limit(limit)
                    .offset(offset)
                )
                return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    async def get_chart_data(self, user_address: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily usage data for charts"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return []
        try:
            async with AsyncSessionLocal() as session:
                start_date = date.today() - timedelta(days=days)
                result = await session.execute(
                    select(DailyUsageSnapshot)
                    .filter(
                        func.lower(DailyUsageSnapshot.user_address) == user_key,
                        DailyUsageSnapshot.date >= start_date
                    )
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

    async def get_last_used_models(self, user_address: str, timeframe: str = 'all', limit: int = 50) -> List[Dict[str, Any]]:
        """Get last used models with aggregated metrics by timeframe"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return []
        try:
            async with AsyncSessionLocal() as session:
                query = select(
                    AIUsageLog.model,
                    func.count(AIUsageLog.id).label("request_count"),
                    func.sum(AIUsageLog.input_tokens + AIUsageLog.output_tokens).label("total_tokens"),
                    func.sum(AIUsageLog.cost).label("total_cost"),
                    func.max(AIUsageLog.timestamp).label("last_used")
                ).filter(func.lower(AIUsageLog.user_address) == user_key)

                # Timeframe filter
                if timeframe == '24h':
                    query = query.filter(AIUsageLog.timestamp >= datetime.utcnow() - timedelta(hours=24))
                elif timeframe == '7d':
                    query = query.filter(AIUsageLog.timestamp >= datetime.utcnow() - timedelta(days=7))
                elif timeframe == '30d':
                    query = query.filter(AIUsageLog.timestamp >= datetime.utcnow() - timedelta(days=30))

                query = query.group_by(AIUsageLog.model).order_by(desc("last_used")).limit(limit)
                
                result = await session.execute(query)
                rows = result.fetchall()

                return [
                    {
                        "model": row.model,
                        "request_count": int(row.request_count or 0),
                        "total_tokens": int(row.total_tokens or 0),
                        "total_cost": float(row.total_cost or 0.0),
                        "last_used": row.last_used.strftime("%Y-%m-%d %H:%M") if row.last_used else ""
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting last used models: {e}")
            return []

    async def get_global_weekly_usage(self) -> Dict[str, int]:
        """Get total tokens used per model globally in the last 7 days"""
        try:
            async with AsyncSessionLocal() as session:
                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                query = select(
                    AIUsageLog.model,
                    func.sum(AIUsageLog.input_tokens + AIUsageLog.output_tokens).label("total_tokens")
                ).filter(AIUsageLog.timestamp >= seven_days_ago).group_by(AIUsageLog.model)
                
                result = await session.execute(query)
                rows = result.fetchall()
                return {row.model: int(row.total_tokens or 0) for row in rows}
        except Exception as e:
            logger.error(f"Error getting global weekly usage: {e}")
            return {}

    async def get_enabled_models(self, user_address: str) -> List[str]:
        """Get list of enabled models for a user"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return []
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserEnabledModels).filter(UserEnabledModels.user_address == user_key)
                )
                record = result.scalars().first()
                
                if record and record.model_list:
                    return self._normalize_enabled_ids(json.loads(record.model_list))
                
                # Default fallback
                return []
        except Exception as e:
            logger.error(f"Error getting enabled models: {e}")
            return []

    async def save_enabled_models(self, user_address: str, models: List[str]) -> bool:
        """Save list of enabled models for a user"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            logger.error("Error saving enabled models: user_address is empty")
            return False
        try:
            async with AsyncSessionLocal() as session:
                # Check if exists
                result = await session.execute(
                    select(UserEnabledModels).filter(UserEnabledModels.user_address == user_key)
                )
                record = result.scalars().first()
                
                models_json = json.dumps(self._normalize_enabled_ids(models))
                
                if record:
                    record.model_list = models_json
                else:
                    record = UserEnabledModels(
                        user_address=user_key,
                        model_list=models_json
                    )
                    session.add(record)
                
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving enabled models: {e}")
            return False

    async def get_default_enabled_models(self) -> List[str]:
        """Get the global default enabled models"""
        DEFAULT_MODELS = [
            'anthropic/claude-4.5-sonnet',
            'deepseek/deepseek-chat-v3.1',
            'google/gemini-3-pro',
            'openai/gpt-5.1',
            'openai/gpt-oss-120b:free',
            'x-ai/grok-4',
            'x-ai/grok-420',
            'moonshot/kimi-k2-thinking',
            'qwen/qwen-3-max',
            'nvidia/moonshotai/kimi-k2-thinking',
            'nvidia/qwen/qwen3-next-80b-a3b-thinking',
            'nvidia/z-ai/glm4.7',
            'nvidia/minimaxai/minimax-m2.1',
            'nvidia/moonshotai/kimi-k2.5',
            'moonshotai/kimi-k2-thinking',
            'qwen/qwen3-next-80b-a3b-thinking',
            'z-ai/glm4.7',
            'minimaxai/minimax-m2.1',
            'moonshotai/kimi-k2.5'
        ]
        
        try:
            async with AsyncSessionLocal() as session:
                # Use a specific keyword for default settings
                result = await session.execute(
                    select(UserEnabledModels).filter(UserEnabledModels.user_address == "global_default")
                )
                record = result.scalars().first()
                
                if record and record.model_list:
                    stored = self._normalize_enabled_ids(json.loads(record.model_list))
                    return self._normalize_enabled_ids([*stored, *DEFAULT_MODELS])
                
                return DEFAULT_MODELS
        except Exception as e:
            logger.error(f"Error getting default enabled models: {e}")
            return DEFAULT_MODELS

    async def get_enabled_agents(self, user_address: str) -> List[str]:
        """Get list of enabled agents for a user"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            return []
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserEnabledAgents).filter(UserEnabledAgents.user_address == user_key)
                )
                record = result.scalars().first()
                
                if record and record.agent_list:
                    return self._normalize_enabled_ids(json.loads(record.agent_list))
                
                return []
        except Exception as e:
            logger.error(f"Error getting enabled agents: {e}")
            return []

    async def save_enabled_agents(self, user_address: str, agents: List[str]) -> bool:
        """Save list of enabled agents for a user"""
        user_key = self._normalize_user_address(user_address)
        if not user_key:
            logger.error("Error saving enabled agents: user_address is empty")
            return False
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserEnabledAgents).filter(UserEnabledAgents.user_address == user_key)
                )
                record = result.scalars().first()
                
                agents_json = json.dumps(self._normalize_enabled_ids(agents))
                
                if record:
                    record.agent_list = agents_json
                else:
                    record = UserEnabledAgents(
                        user_address=user_key,
                        agent_list=agents_json
                    )
                    session.add(record)
                
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving enabled agents: {e}")
            return False

    async def get_default_enabled_agents(self) -> List[str]:
        """Get the global default enabled agents"""
        DEFAULT_AGENTS = []
        
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserEnabledAgents).filter(UserEnabledAgents.user_address == "global_default")
                )
                record = result.scalars().first()
                
                if record and record.agent_list:
                    return json.loads(record.agent_list)
                
                return DEFAULT_AGENTS
        except Exception as e:
            logger.error(f"Error getting default enabled agents: {e}")
            return DEFAULT_AGENTS

# Singleton instance
usage_service = UsageService()
