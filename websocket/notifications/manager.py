import logging
import json
from typing import Dict, Set, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class NotificationManager:
    """Manages user notifications"""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {} # user_address -> websockets
        
    async def connect(self, user_address: str, websocket: WebSocket):
        if user_address not in self.active_connections:
            self.active_connections[user_address] = set()
        self.active_connections[user_address].add(websocket)
        logger.info(f"User {user_address} connected to notifications")

    async def disconnect(self, user_address: str, websocket: WebSocket):
        if user_address in self.active_connections:
            self.active_connections[user_address].discard(websocket)
            if not self.active_connections[user_address]:
                del self.active_connections[user_address]

    async def send_notification(self, user_address: str, message: dict):
        """Send notification to a specific user"""
        if user_address in self.active_connections:
            payload = json.dumps(message)
            disconnected = set()
            for ws in self.active_connections[user_address]:
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.add(ws)
            
            self.active_connections[user_address] -= disconnected

notification_manager = NotificationManager()
