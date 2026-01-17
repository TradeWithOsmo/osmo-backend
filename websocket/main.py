from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram
import signal
import sys
import os
import logging
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Set

from config import settings
from Hyperliquid.websocket_client import HyperliquidWebSocketClient
from Hyperliquid.http_client import http_client
from Hyperliquid.normalizer import normalize_all_mids
from Ostium.api_client import OstiumAPIClient
from Ostium.poller import OstiumPoller
from Ostium.normalizer import normalize_ostium_prices
from Ostium.price_history import PriceHistoryTracker
from Ostium.candles import CandleGenerator
from Ostium.persistence import CandlePersister
from database.connection import init_db
from database.models import Candle, Trade
from storage.redis_manager import redis_manager

# Import connector system
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from connectors.init_connectors import connector_registry
from connectors.api_routes import router as connectors_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
http_requests_total = Counter('osmo_http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
active_connections = Gauge('osmo_ws_connections', 'Active WebSocket connections', ['module', 'symbol'])
request_latency = Histogram('osmo_api_latency_seconds', 'API request latency', ['endpoint'])

# Global state
hyperliquid_client: HyperliquidWebSocketClient = None
ostium_client: OstiumAPIClient = None
ostium_poller: OstiumPoller = None
ostium_price_history: PriceHistoryTracker = PriceHistoryTracker()
ostium_candle_generator: CandleGenerator = CandleGenerator()
ostium_persister: CandlePersister = None # Will be initialized in lifespan
connected_clients: Dict[str, Set[WebSocket]] = {}  # symbol -> set of websockets
connected_l2book_clients: Dict[str, Set[WebSocket]] = {}
connected_trades_clients: Dict[str, Set[WebSocket]] = {}
latest_prices: Dict[str, dict] = {}  # symbol -> latest price data


async def handle_hyperliquid_message(data: dict):
    """Handle incoming messages from Hyperliquid and broadcast to connected clients"""
    global latest_prices
    
    normalized = normalize_all_mids(data)
    latest_prices.update(normalized)
    
    # Broadcast to connected clients
    for symbol, price_data in normalized.items():
        if symbol in connected_clients:
            message = json.dumps({
                "type": "price_update",
                "data": price_data
            })
            
            # Broadcast to all clients subscribed to this symbol
            disconnected = set()
            for client in connected_clients[symbol]:
                try:
                    await client.send_text(message)
                except Exception as e:
                    logger.error(f"Failed to send to client: {e}")
                    disconnected.add(client)
            
            # Remove disconnected clients
            connected_clients[symbol] -= disconnected


async def handle_l2book_message(data: dict):
    """Handle incoming L2 Orderbook data"""
    coin = data.get("coin")
    if not coin:
        return
        
    symbol = f"{coin}-USD" # Normalize
    message = json.dumps({
        "type": "l2Book",
        "data": data,
        "symbol": symbol
    })
    
    # Broadcast to WebSocket clients
    if symbol in connected_l2book_clients:
        disconnected = set()
        for client in connected_l2book_clients[symbol]:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)
        connected_l2book_clients[symbol] -= disconnected

    # Publish to Redis
    try:
        await redis_manager.publish(f"orderbook:{symbol}", message)
    except Exception:
        pass


async def handle_trades_message(data: dict):
    """Handle incoming Trades data"""
    # trades data is usually a list of trades
    if not isinstance(data, list) or not data:
        return
        
    coin = data[0].get("coin")
    if not coin:
        return

    symbol = f"{coin}-USD"
    message = json.dumps({
        "type": "trades",
        "data": data,
        "symbol": symbol
    })
    
    # Broadcast to WebSocket clients
    if symbol in connected_trades_clients:
        disconnected = set()
        for client in connected_trades_clients[symbol]:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)
        connected_trades_clients[symbol] -= disconnected

    # Publish to Redis
    try:
        await redis_manager.publish(f"trades:{symbol}", message)
    except Exception:
        pass


async def handle_ostium_message(data: dict):
    """Handle incoming Ostium price data and broadcast to connected clients"""
    global latest_prices, ostium_price_history, ostium_candle_generator
    
    # Update price history tracker
    if isinstance(data, list):
        ostium_price_history.update_from_ostium_response(data)
    
    normalized = normalize_ostium_prices(data)
    
    # Process each symbol
    for symbol, price_data in normalized.items():
        # 1. Update Candle Generator
        try:
            price = float(price_data["price"])
            timestamp = price_data["timestamp"]
            ostium_candle_generator.update_price(symbol, price, timestamp)
        except Exception as e:
            logger.error(f"Failed to update candle for {symbol}: {e}")

        # 2. Add 24h stats
        stats = ostium_price_history.get_stats(symbol)
        if stats:
            price_data.update({
                "change_24h": stats["change_percent_24h"],
                "high_24h": stats["high_24h"],
                "low_24h": stats["low_24h"],
                "volume_24h": stats["volume_24h"]
            })
            
        # 3. Add Mark Price (For Ostium, Price = Mark Price)
        price_data["markPrice"] = price_data["price"]
    
    latest_prices.update(normalized)
    
    # Broadcast to connected clients
    for symbol, price_data in normalized.items():
        if symbol in connected_clients:
            message = json.dumps({
                "type": "price_update",
                "data": price_data
            })
            
            disconnected = set()
            for client in connected_clients[symbol]:
                try:
                    await client.send_text(message)
                except Exception as e:
                    logger.error(f"Failed to send to client: {e}")
                    disconnected.add(client)
            
            connected_clients[symbol] -= disconnected


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events"""
    global hyperliquid_client, ostium_client, ostium_poller, ostium_candle_generator, ostium_persister
    
    # Startup
    logger.info("🚀 Starting Osmo Backend...")
    logger.info(f"Environment: {settings.ENV}")
    
    # Initialize Persistence
    candle_queue = asyncio.Queue()
    ostium_candle_generator = CandleGenerator(queue=candle_queue)
    ostium_persister = CandlePersister(queue=candle_queue)
    ostium_persister = CandlePersister(queue=candle_queue)
    await ostium_persister.start()
    
    # Initialize Redis
    try:
        await redis_manager.connect()
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
    
    # Start Bridge Monitor - REMOVED (Not implemented)
    # await bridge_monitor.start()

    # Start Hyperliquid WebSocket client
    try:
        hyperliquid_client = HyperliquidWebSocketClient(settings.HYPERLIQUID_WS_URL)
        await hyperliquid_client.connect()
        await hyperliquid_client.subscribe("allMids", handle_hyperliquid_message)
        asyncio.create_task(hyperliquid_client.listen())
        logger.info("✅ Hyperliquid WebSocket client started")
    except Exception as e:
        logger.error(f"❌ Failed to start Hyperliquid client: {e}")
    
    # Start Ostium API poller
    try:
        ostium_client = OstiumAPIClient(settings.OSTIUM_API_URL)
        ostium_poller = OstiumPoller(
            api_client=ostium_client,
            poll_interval=settings.OSTIUM_POLL_INTERVAL,
            callback=handle_ostium_message
        )
        await ostium_poller.start()
        logger.info(f"✅ Ostium poller started (interval: {settings.OSTIUM_POLL_INTERVAL}s)")
    except Exception as e:
        logger.error(f"❌ Failed to start Ostium poller: {e}")

    # Initialize Connector System
    try:
        await connector_registry.initialize(redis_url=settings.REDIS_URL)
        logger.info("✅ Connector system initialized")
    except Exception as e:
        logger.error(f"❌ Connector initialization failed: {e}")
    
    # Initialize Database
    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down gracefully...")
    
    # Shutdown connector system
    await connector_registry.shutdown()
    
    if hyperliquid_client:
        await hyperliquid_client.disconnect()
    
    await bridge_monitor.stop()
    await redis_manager.disconnect()
    
    if ostium_persister:
        await ostium_persister.stop()

    if ostium_poller:
        await ostium_poller.stop()
    if ostium_client:
        await ostium_client.close()
    logger.info("✅ Shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title="Osmo Backend API",
    description="Real-time trading data aggregation for Hyperliquid and Ostium",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Include Routers
from routers.user import router as user_router
app.include_router(user_router)

# Include Connector Routes
app.include_router(connectors_router)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health status"""
    hl_status = hyperliquid_client.get_status() if hyperliquid_client else {"connected": False}
    
    return {
        "status": "healthy",
        "hyperliquid": {
            "connected": hl_status.get("connected", False),
            "symbols": len(latest_prices),
            "subscriptions": hl_status.get("subscriptions", 0)
        },
        "ostium": {
            "connected": False,
            "symbols": 0,
            "last_poll": None
        },
        "database": {
            "connected": False
        },
        "redis": await redis_manager.get_status()
    }


# Candle history endpoint
@app.get("/api/candles/{symbol}")
async def get_candles(symbol: str, limit: int = 100):
    """Get OHLC candles for a symbol"""
    # 1. Try Ostium Candle Generator first
    if symbol in ostium_candle_generator.candles or symbol in ostium_candle_generator.current_candles:
        return ostium_candle_generator.get_candles(symbol, limit)
    
    # 2. Try Hyperliquid API
    # Assuming symbol format "BTC-USD" -> "BTC" for HL
    try:
        coin = symbol.split("-")[0]
        # Calculate time range for 'limit' candles
        # Assuming 1m interval for now
        end_time = int(time.time() * 1000)
        start_time = end_time - (limit * 60 * 1000)
        
        candles = await http_client.get_candles(coin, interval="1m", start_time=start_time, end_time=end_time)
        return candles
    except Exception as e:
        logger.error(f"Failed to fetch external candles for {symbol}: {e}")
        return []


# Market info endpoint
@app.get("/api/markets")
async def get_markets():
    """List all available markets"""
    markets = []
    for symbol, data in latest_prices.items():
        markets.append({
            "symbol": symbol,
            "source": data.get("source", "hyperliquid"),
            "status": "active",
            "price": data["price"],
            **{k: v for k, v in data.items() if k not in ["symbol", "source", "price"]}
        })
    
    return {
        "total_markets": len(markets),
        "markets": markets
    }


# WebSocket endpoint for Hyperliquid price streaming
@app.websocket("/ws/hyperliquid/{symbol}")
async def hyperliquid_websocket(websocket: WebSocket, symbol: str):
    """Stream real-time Hyperliquid prices to frontend"""
    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module="hyperliquid", symbol=symbol).inc()
    
    logger.info(f"📡 Client connected to {symbol}")
    
    # Send latest price immediately
    if symbol in latest_prices:
        await websocket.send_text(json.dumps({
            "type": "price_update",
            "data": latest_prices[symbol]
        }))
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Echo back for now (can add client commands later)
            logger.debug(f"Received from client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"📴 Client disconnected from {symbol}")
    
    finally:
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module="hyperliquid", symbol=symbol).dec()


@app.websocket("/ws/orderbook/{symbol}")
async def orderbook_websocket(websocket: WebSocket, symbol: str):
    """Stream L2 Orderbook data"""
    await websocket.accept()
    
    coin = symbol.split("-")[0]
    
    if symbol not in connected_l2book_clients:
        connected_l2book_clients[symbol] = set()
    connected_l2book_clients[symbol].add(websocket)
    
    # Subscribe to Hyperliquid
    if hyperliquid_client and hyperliquid_client.is_connected:
        await hyperliquid_client.subscribe("l2Book", handle_l2book_message, coin=coin)
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if symbol in connected_l2book_clients:
            connected_l2book_clients[symbol].discard(websocket)


@app.websocket("/ws/trades/{symbol}")
async def trades_websocket(websocket: WebSocket, symbol: str):
    """Stream Trades data"""
    await websocket.accept()
    
    coin = symbol.split("-")[0]
    
    if symbol not in connected_trades_clients:
        connected_trades_clients[symbol] = set()
    connected_trades_clients[symbol].add(websocket)
    
    # Subscribe to Hyperliquid
    if hyperliquid_client and hyperliquid_client.is_connected:
        await hyperliquid_client.subscribe("trades", handle_trades_message, coin=coin)
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if symbol in connected_trades_clients:
            connected_trades_clients[symbol].discard(websocket)


@app.websocket("/ws/bridge/{address}")
async def bridge_websocket(websocket: WebSocket, address: str):
    """Subscribe to bridge deposit events"""
    await websocket.accept()
    
    async def send_event(data):
        try:
            await websocket.send_json(data)
        except Exception:
            pass
    
    await bridge_monitor.subscribe(address, send_event)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bridge_monitor.unsubscribe(address, send_event)


@app.websocket("/ws/notifications/{address}")
async def notification_websocket(websocket: WebSocket, address: str):
    """Subscribe to user notifications"""
    await websocket.accept()
    await notification_manager.connect(address, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await notification_manager.disconnect(address, websocket)


# Graceful shutdown handler
def handle_shutdown(signum, frame):
    logger.info(f"Received signal {signum}, initiating shutdown...")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Hot reload for development
        log_level=settings.LOG_LEVEL.lower()
    )
