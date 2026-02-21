"""
Usage Tracking Service for Agent
Tracks LLM API calls, tokens, and costs
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class UsageTracker:
    """SQLite-based usage tracking for agent"""

    def __init__(self, db_path: str = "logs/usage.db"):
        base_dir = Path(__file__).resolve().parents[2]
        candidate = Path(db_path)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        candidate.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = str(candidate)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def get_connection(self):
        """Get database connection with context manager"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # AI Usage Logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_address TEXT NOT NULL,
                    session_id TEXT,
                    model TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Daily Usage Snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    user_address TEXT NOT NULL,
                    total_cost REAL DEFAULT 0.0,
                    total_tokens INTEGER DEFAULT 0,
                    request_count INTEGER DEFAULT 0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, user_address)
                )
            """)

            # Create indexes
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_user ON ai_usage_logs(user_address)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_time ON ai_usage_logs(timestamp)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_user_time ON ai_usage_logs(user_address, timestamp)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_user ON daily_usage_snapshots(user_address)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_usage_snapshots(date)"
            )

            logger.info("Usage tracking database initialized")

    async def log_usage(
        self,
        user_address: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        session_id: Optional[str] = None,
    ):
        """Log an AI request and update daily snapshot"""
        user_key = (user_address or "").strip().lower()
        if not user_key:
            logger.error("User address is empty, skipping usage log")
            return

        with self._lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Log individual request
                cursor.execute(
                    """
                    INSERT INTO ai_usage_logs (user_address, session_id, model, input_tokens, output_tokens, cost)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (user_key, session_id, model, input_tokens, output_tokens, cost),
                )

                # Update or create daily snapshot
                today = date.today().isoformat()
                total_tokens = input_tokens + output_tokens

                cursor.execute(
                    """
                    INSERT INTO daily_usage_snapshots (date, user_address, total_cost, total_tokens, request_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(date, user_address) DO UPDATE SET
                        total_cost = total_cost + excluded.total_cost,
                        total_tokens = total_tokens + excluded.total_tokens,
                        request_count = request_count + 1,
                        last_updated = CURRENT_TIMESTAMP
                """,
                    (today, user_key, cost, total_tokens),
                )

                logger.debug(
                    f"Logged usage: {model} - {total_tokens} tokens - ${cost:.6f}"
                )

    async def get_user_stats(self, user_address: str) -> Dict[str, Any]:
        """Get aggregated stats for a user"""
        user_key = (user_address or "").strip().lower()
        if not user_key:
            return {
                "total_cost": 0,
                "total_tokens": 0,
                "request_count": 0,
                "credit_balance": 100.0,
            }

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Get totals
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(cost), 0) as total_cost,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COUNT(*) as request_count
                FROM ai_usage_logs
                WHERE user_address = ?
            """,
                (user_key,),
            )

            row = cursor.fetchone()

            total_cost = float(row["total_cost"] or 0)
            total_tokens = int(row["total_tokens"] or 0)
            request_count = int(row["request_count"] or 0)
            credit_balance = max(0, 100.0 - total_cost)  # Default $100 budget

            return {
                "total_cost": total_cost,
                "total_tokens": total_tokens,
                "request_count": request_count,
                "credit_balance": credit_balance,
            }

    async def get_history(
        self, user_address: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get historical usage logs"""
        user_key = (user_address or "").strip().lower()
        if not user_key:
            return []

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, model, input_tokens, output_tokens, cost, timestamp
                FROM ai_usage_logs
                WHERE user_address = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """,
                (user_key, limit, offset),
            )

            return [
                {
                    "id": row["id"],
                    "model": row["model"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cost": row["cost"],
                    "timestamp": row["timestamp"],
                }
                for row in cursor.fetchall()
            ]

    async def get_chart_data(
        self, user_address: str, days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get daily usage data for charts"""
        user_key = (user_address or "").strip().lower()
        if not user_key:
            return []

        with self.get_connection() as conn:
            cursor = conn.cursor()

            start_date = (date.today() - timedelta(days=days)).isoformat()

            cursor.execute(
                """
                SELECT date, total_cost, total_tokens, request_count
                FROM daily_usage_snapshots
                WHERE user_address = ? AND date >= ?
                ORDER BY date ASC
            """,
                (user_key, start_date),
            )

            return [
                {
                    "date": row["date"],
                    "cost": row["total_cost"],
                    "tokens": row["total_tokens"],
                    "requests": row["request_count"],
                }
                for row in cursor.fetchall()
            ]

    async def get_last_used_models(
        self, user_address: str, timeframe: str = "all", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get last used models with aggregated metrics"""
        user_key = (user_address or "").strip().lower()
        if not user_key:
            return []

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Timeframe filter
            time_filter = ""
            if timeframe == "24h":
                time_filter = "AND timestamp >= datetime('now', '-24 hours')"
            elif timeframe == "7d":
                time_filter = "AND timestamp >= datetime('now', '-7 days')"
            elif timeframe == "30d":
                time_filter = "AND timestamp >= datetime('now', '-30 days')"

            cursor.execute(
                f"""
                SELECT
                    model,
                    COUNT(*) as request_count,
                    SUM(input_tokens + output_tokens) as total_tokens,
                    SUM(cost) as total_cost,
                    MAX(timestamp) as last_used
                FROM ai_usage_logs
                WHERE user_address = ? {time_filter}
                GROUP BY model
                ORDER BY last_used DESC
                LIMIT ?
            """,
                (user_key, limit),
            )

            return [
                {
                    "model": row["model"],
                    "request_count": row["request_count"],
                    "total_tokens": row["total_tokens"],
                    "total_cost": float(row["total_cost"] or 0),
                    "last_used": row["last_used"],
                }
                for row in cursor.fetchall()
            ]

    async def get_global_weekly_usage(self) -> Dict[str, int]:
        """Get total tokens used per model globally in the last 7 days"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT model, SUM(input_tokens + output_tokens) as total_tokens
                FROM ai_usage_logs
                WHERE timestamp >= datetime('now', '-7 days')
                GROUP BY model
            """)

            return {row["model"]: row["total_tokens"] for row in cursor.fetchall()}

    async def clear_old_logs(self, days_old: int = 90):
        """Clear logs older than specified days"""
        with self._lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    DELETE FROM ai_usage_logs
                    WHERE timestamp < datetime('now', '-' || ? || ' days')
                """,
                    (days_old,),
                )

                deleted = cursor.rowcount
                logger.info(f"Cleared {deleted} usage logs older than {days_old} days")


# Singleton instance
usage_tracker = UsageTracker()
