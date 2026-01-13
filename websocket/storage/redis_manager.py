import json
import asyncio
import logging
from typing import Optional, Any
from redis.asyncio import Redis, ConnectionPool
from config import settings

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self):
        self._redis: Optional[Redis] = None
        self._pool: Optional[ConnectionPool] = None
        
    async def connect(self):
        """Initialize Redis connection pool"""
        if self._redis:
            return

        try:
            self._pool = ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8"
            )
            self._redis = Redis(connection_pool=self._pool)
            await self._redis.ping()
            logger.info(f"✅ Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise e

    async def disconnect(self):
        """Close Redis connection"""
        if self._redis:
            await self._redis.close()
            logger.info("✅ Redis connection closed")

    async def publish(self, channel: str, message: Any):
        """Publish message to Pub/Sub channel"""
        if not self._redis:
            logger.warning("Redis not connected, skipping publish")
            return

        try:
            if not isinstance(message, str):
                message = json.dumps(message)
            
            await self._redis.publish(channel, message)
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")

    async def add_stream(self, stream_key: str, data: dict, max_len: int = 1000):
        """Add entry to Redis Stream"""
        if not self._redis:
            return

        try:
            # XADD stream_key MAXLEN ~ max_len * data
            await self._redis.xadd(
                name=stream_key,
                fields=data,
                maxlen=max_len,
                approximate=True
            )
        except Exception as e:
            logger.error(f"Failed to add to stream {stream_key}: {e}")
            
    async def get_status(self) -> dict:
        """Get connection status"""
        connected = False
        try:
            if self._redis:
                await self._redis.ping()
                connected = True
        except:
            connected = False
            
        return {"connected": connected}

# Global instance
redis_manager = RedisManager()
