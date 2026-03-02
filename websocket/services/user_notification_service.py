from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from storage.redis_manager import redis_manager


class UserNotificationService:
    """Centralized publisher for user-scoped real-time notifications."""

    async def publish(
        self,
        user_address: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        user = str(user_address or "").lower().strip()
        if not user:
            return

        message = {
            "type": str(event_type or "event").strip().lower(),
            "address": user,
            "data": data or {},
            "meta": meta or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        await redis_manager.publish(f"user_notifications:{user}", message)


user_notification_service = UserNotificationService()

