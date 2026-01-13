import asyncio
import websockets
import json
import logging
from typing import Optional, Callable, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class HyperliquidWebSocketClient:
    """WebSocket client for Hyperliquid with auto-reconnection"""
    
    def __init__(self, ws_url: str = "wss://api.hyperliquid.xyz/ws"):
        self.ws_url = ws_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.subscriptions: Dict[str, dict] = {}
        self.message_callbacks: Dict[str, Callable] = {}
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        
    async def connect(self):
        """Establish WebSocket connection"""
        try:
            self.websocket = await websockets.connect(self.ws_url)
            self.is_connected = True
            self.reconnect_attempts = 0
            logger.info(f"✅ Connected to Hyperliquid WebSocket: {self.ws_url}")
            
            # Resubscribe to existing subscriptions after reconnect
            for sub_id, subscription in self.subscriptions.items():
                await self._send_subscription(subscription)
                
        except Exception as e:
            logger.error(f"❌ Failed to connect to Hyperliquid: {e}")
            self.is_connected = False
            raise
    
    async def disconnect(self):
        """Close WebSocket connection"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("🔌 Disconnected from Hyperliquid WebSocket")
    
    async def subscribe(self, subscription_type: str, callback: Callable, **kwargs):
        """
        Subscribe to a Hyperliquid feed
        
        Args:
            subscription_type: Type of subscription (e.g., "allMids", "trades", "l2Book")
            callback: Function to call when messages are received
            **kwargs: Additional subscription parameters (e.g., coin="BTC", interval="1m")
        """
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": subscription_type,
                **kwargs
            }
        }
        
        sub_id = f"{subscription_type}_{json.dumps(kwargs, sort_keys=True)}"
        
        # Avoid re-subscribing if already active
        if sub_id in self.subscriptions:
            logger.debug(f"Already subscribed to {sub_id}")
            # Ensure callback is updated just in case
            self.message_callbacks[subscription_type] = callback
            return

        self.subscriptions[sub_id] = subscription
        self.message_callbacks[subscription_type] = callback
        
        if self.is_connected:
            await self._send_subscription(subscription)
        
        logger.info(f"📡 Subscribed to {subscription_type} with params {kwargs}")
    
    async def _send_subscription(self, subscription: dict):
        """Send subscription message to Hyperliquid"""
        try:
            await self.websocket.send(json.dumps(subscription))
        except Exception as e:
            logger.error(f"Failed to send subscription: {e}")
    
    async def listen(self):
        """Listen for messages from Hyperliquid and dispatch to callbacks"""
        while True:
            try:
                if not self.is_connected:
                    await self._reconnect()
                
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # Handle subscription confirmation
                if data.get("channel") == "subscriptionResponse":
                    logger.info(f"✅ Subscription confirmed: {data['data']}")
                    continue
                
                # Dispatch message to appropriate callback
                channel = data.get("channel")
                if channel and channel in self.message_callbacks:
                    await self.message_callbacks[channel](data.get("data"))
                
            except websockets.ConnectionClosed:
                logger.warning("❌ Connection closed, attempting reconnect...")
                self.is_connected = False
                await self._reconnect()
                
            except Exception as e:
                logger.error(f"Error in listen loop: {e}")
                await asyncio.sleep(1)
    
    async def _reconnect(self):
        """Reconnect with exponential backoff"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            wait_time = min(2 ** self.reconnect_attempts, 30)  # Max 30 seconds
            logger.info(f"🔄 Reconnecting in {wait_time}s (attempt {self.reconnect_attempts + 1}/{self.max_reconnect_attempts})")
            
            await asyncio.sleep(wait_time)
            
            try:
                await self.connect()
                logger.info("✅ Reconnected successfully")
                return
            except Exception as e:
                self.reconnect_attempts += 1
                logger.error(f"Reconnect attempt {self.reconnect_attempts} failed: {e}")
        
        logger.error(f"❌ Max reconnect attempts ({self.max_reconnect_attempts}) reached")
        raise ConnectionError("Failed to reconnect to Hyperliquid")
    
    def get_status(self) -> dict:
        """Get connection status"""
        return {
            "connected": self.is_connected,
            "subscriptions": len(self.subscriptions),
            "reconnect_attempts": self.reconnect_attempts
        }
