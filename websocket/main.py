from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram
import signal
import sys
import os
import logging
import asyncio
import json
import time
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
from Ostium.subgraph_client import OstiumSubgraphClient  # New
from sqlalchemy import text
from database.connection import init_db, AsyncSessionLocal
from database.models import Candle, Trade
from storage.redis_manager import redis_manager

# Import connector system
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from connectors.init_connectors import connector_registry
from connectors.web3_arbitrum.api_routes import router as web3_router
from connectors.hyperliquid.category_map import get_category  # Import category mapping

# Import orders API
from routers.orders import router as orders_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
from prometheus_client import REGISTRY, Counter, Gauge, Histogram

# Clear existing metrics if they exist to avoid duplication errors during reloads
for metric in ['osmo_http_requests_total', 'osmo_ws_connections', 'osmo_api_latency_seconds']:
    try:
        # Check if metric is already in the registry
        # We need to access the protected _names_to_collectors mapping
        if metric in REGISTRY._names_to_collectors:
            collector = REGISTRY._names_to_collectors[metric]
            REGISTRY.unregister(collector)
    except Exception:
        pass

http_requests_total = Counter('osmo_http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
active_connections = Gauge('osmo_ws_connections', 'Active WebSocket connections', ['module', 'symbol'])
request_latency = Histogram('osmo_api_latency_seconds', 'API request latency', ['endpoint'])

# Global state
hyperliquid_client: HyperliquidWebSocketClient = None
ostium_client: OstiumAPIClient = None
ostium_poller: OstiumPoller = None
ostium_subgraph: OstiumSubgraphClient = None # New
ostium_price_history: PriceHistoryTracker = PriceHistoryTracker()
hl_price_history: PriceHistoryTracker = PriceHistoryTracker() # Tracker for HL high/low
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
    
    # Preserve 24h stats from existing state
    for symbol, new_data in normalized.items():
        # Update price history tracker
        if "price" in new_data:
            hl_price_history.update_price(symbol, float(new_data["price"]))

    # Update latest_prices and enrich normalized data with stats
    for symbol, data in normalized.items():
        if symbol in latest_prices:
            latest_prices[symbol].update(data)
            # Inject stats into the broadcast message so frontend gets them
            current_stats = latest_prices[symbol]
            data["high_24h"] = current_stats.get("high_24h", 0)
            data["low_24h"] = current_stats.get("low_24h", 0)
            data["volume_24h"] = current_stats.get("volume_24h", 0)
            data["change_24h"] = current_stats.get("change_24h", 0)
            data["change_24h"] = current_stats.get("change_24h", 0)
            data["change_percent_24h"] = current_stats.get("change_percent_24h", 0)
            data["maxLeverage"] = current_stats.get("maxLeverage", 50)
            data["category"] = current_stats.get("category", "Crypto")
        else:
            # New symbol from WS - Initialize with defaults
            # Extract coin from symbol (e.g., "BTC-USD" -> "BTC")
            coin = symbol.split("-")[0]
            data["category"] = get_category(coin)
            data["maxLeverage"] = 0 # Default until poll_hyperliquid_stats updates it
            data["high_24h"] = 0
            data["low_24h"] = 0
            data["volume_24h"] = 0
            data["change_24h"] = 0
            data["change_percent_24h"] = 0
            latest_prices[symbol] = data
    
    # Broadcast to "ALL" subscribers (global stream)
    if "ALL" in connected_clients and normalized:
        try:
            # OPTIMIZATION: Only send the CHANGED data (normalized), not the full state
            # This prevents overwhelming the client and filling the WS buffer
            all_message = json.dumps({
                "type": "price_update",
                "data": normalized
            })
            disconnected = set()
            for client in list(connected_clients["ALL"]):
                try:
                    await client.send_text(all_message)
                except Exception as e:
                    logger.error(f"Failed to send to ALL client: {e}")
                    disconnected.add(client)
            connected_clients["ALL"] -= disconnected
        except Exception as json_err:
            logger.error(f"JSON serialization error in HL broadcast: {json_err}")
    
    # Broadcast to connected clients (per symbol)
    for symbol, price_data in normalized.items():
        if symbol in connected_clients:
            try:
                message = json.dumps({
                    "type": "price_update",
                    "data": price_data
                })
                
                # Broadcast to all clients subscribed to this symbol
                disconnected = set()
                for client in list(connected_clients[symbol]):
                    try:
                        await client.send_text(message)
                    except Exception as e:
                        logger.error(f"Failed to send to client: {e}")
                        disconnected.add(client)
                
                # Remove disconnected clients
                connected_clients[symbol] -= disconnected
            except Exception as e:
                logger.error(f"Error broadcasting symbol {symbol}: {e}")


async def handle_l2book_message(data: dict):
    """Handle incoming L2 Orderbook data"""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Handling L2Book message: {str(data)[:100]}...")

    coin = data.get("coin")
    if not coin:
        logger.warning(f"⚠️ L2Book data missing 'coin' field: {data.keys()}")
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
        for client in list(connected_l2book_clients[symbol]):
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
        logger.warning(f"⚠️ Trades data is not a non-empty list: {type(data)}")
        return
        
    coin = data[0].get("coin")
    if not coin:
        logger.warning(f"⚠️ Trades data missing 'coin' field in first element: {data[0].keys()}")
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
        for client in list(connected_trades_clients[symbol]):
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
    
    # FILTER: Skip crypto markets in Ostium handler (We use Hyperliquid for Crypto)
    crypto_skips = {'BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD', 'BNB-USD', 'LINK-USD', 'TRX-USD', 'XRP-USD', 'HYPE-USD', 'GLXY-USD', 'BMNR-USD', 'CRCL-USD', 'SBET-USD', 'SUI-USD'}
    filtered_normalized = {}

    # Process each symbol
    for symbol, price_data in normalized.items():
        if symbol in crypto_skips:
            continue
            
        filtered_normalized[symbol] = price_data
        
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
            # Stats fields mapping
            price_data["change_24h"] = stats.get("change_24h", 0)
            price_data["change_percent_24h"] = stats.get("change_percent_24h", 0)
            price_data["high_24h"] = stats.get("high_24h")
            price_data["low_24h"] = stats.get("low_24h")
            
        # 3. Add Mark Price (For Ostium, Price = Mark Price)
        price_data["markPrice"] = price_data["price"]
        
        # 4. PRESERVE fields from existing state
        if symbol in latest_prices:
            existing = latest_prices[symbol]
            # Copy volume data if not present in new update
            if "volume_24h" in existing and price_data.get("volume_24h") is None:
                price_data["volume_24h"] = existing["volume_24h"]
            if "openInterest" in existing and "openInterest" not in price_data:
                price_data["openInterest"] = existing["openInterest"]
            if "utilization" in existing and "utilization" not in price_data:
                price_data["utilization"] = existing["utilization"]
    
    latest_prices.update(filtered_normalized)
    
    # Broadcast to "ALL" subscribers (global stream)
    if "ALL" in connected_clients and filtered_normalized:
        try:
            # OPTIMIZATION: Only send the CHANGED data (filtered_normalized), not the full state
            all_message = json.dumps({
                "type": "price_update",
                "data": filtered_normalized
            })
            disconnected = set()
            for client in list(connected_clients["ALL"]):
                try:
                    await client.send_text(all_message)
                except Exception as e:
                    logger.error(f"Failed to send to ALL client (Ostium): {e}")
                    disconnected.add(client)
            connected_clients["ALL"] -= disconnected
        except Exception as json_err:
            logger.error(f"JSON serialization error in Ostium broadcast: {json_err}")

    # Broadcast to connected clients (per symbol)
    for symbol, price_data in filtered_normalized.items():
        if symbol in connected_clients:
            try:
                message = json.dumps({
                    "type": "price_update",
                    "data": price_data
                })
                
                disconnected = set()
                for client in list(connected_clients[symbol]):
                    try:
                        await client.send_text(message)
                    except Exception as e:
                        logger.error(f"Failed to send to client {symbol}: {e}")
                        disconnected.add(client)
                
                connected_clients[symbol] -= disconnected
            except Exception as e:
                logger.error(f"Error broadcasting symbol {symbol} from Ostium: {e}")


async def poll_ostium_volume():
    """Periodically fetch volume/OI data from Ostium Subgraph"""
    global latest_prices, ostium_subgraph
    
    while True:
        try:
            if ostium_subgraph:
                logger.debug("Polling Ostium Subgraph for Volume/OI...")
                # Add timeout
                pairs_data = await asyncio.wait_for(ostium_subgraph.get_formatted_pairs_details(), timeout=30.0)
                
                count = 0
                for item in pairs_data:
                    symbol = item['symbol']
                    
                    # FILTER: Skip crypto markets in Ostium poller (We use Hyperliquid for Crypto)
                    # This prevents overwriting HL's high volume data with Ostium's low OI data
                    s_clean = symbol.upper().replace("-", "")
                    crypto_skips = ['ADAUSD', 'BNBUSD', 'BTCUSD', 'ETHUSD', 'LINKUSD', 'SOLUSD', 'TRXUSD', 'XRPUSD', 'HYPEUSD', 'GLXYUSD', 'BMNRUSD', 'CRCLUSD', 'SBETUSD', 'SUIUSD']
                    if s_clean in crypto_skips:
                        continue
                    
                    # Ensure entry exists
                    if symbol not in latest_prices:
                        latest_prices[symbol] = {
                            "symbol": symbol,
                            "price": 0,
                            "price": 0,
                            "source": "ostium",
                            "maxLeverage": 100, # Default for Forex/Commodities on Ostium
                            "timestamp": int(time.time() * 1000)
                        }
                    
                    # Use Total OI as a proxy for "Volume" / Market Size
                    latest_prices[symbol]["volume_24h"] = item['totalOI'] 
                    latest_prices[symbol]["openInterest"] = item['totalOI']
                    latest_prices[symbol]["utilization"] = item['utilization']
                    latest_prices[symbol]["openInterest"] = item['totalOI']
                    latest_prices[symbol]["utilization"] = item['utilization']
                    latest_prices[symbol]["source"] = "ostium" 
                    latest_prices[symbol]["maxLeverage"] = 100 # Ensure present update
                    
                    # Add 24h stats from history
                    stats = ostium_price_history.get_stats(symbol)
                    if stats:
                        latest_prices[symbol]["change_24h"] = stats.get("change_24h", 0)
                        latest_prices[symbol]["change_percent_24h"] = stats.get("change_percent_24h", 0)
                        latest_prices[symbol]["high_24h"] = stats.get("high_24h")
                        latest_prices[symbol]["low_24h"] = stats.get("low_24h")
                    
                    count += 1
                
                if count > 0:
                    logger.info(f"✅ Updated volume/OI for {count} Ostium symbols")
                else:
                    logger.warning(f"⚠️ Polled Ostium Subgraph but found 0 matches in latest_prices. (Total pairs: {len(pairs_data)})")
                    
        except Exception as e:
            logger.error(f"❌ Error in volume poller: {e}")
            
        await asyncio.sleep(30)  # Poll every 30s


async def poll_hyperliquid_stats():
    """Periodically fetch 24h stats for Hyperliquid (Volume, OI)"""
    global latest_prices
    
    while True:
        try:
            logger.info("Polling Hyperliquid stats (Volume, OI, etc)...")
            # Add timeout
            data = await asyncio.wait_for(http_client.get_meta_and_asset_ctxs(), timeout=30.0)
            
            if data and len(data) == 2:
                meta = data[0]
                ctxs = data[1]
                universe = meta.get("universe", [])
                
                count = 0
                for i, asset_info in enumerate(universe):
                    if i < len(ctxs):
                        coin = asset_info["name"]
                        ctx = ctxs[i]
                        symbol = f"{coin}-USD"
                        
                        # Extract maxLeverage from universe info
                        max_leverage = asset_info.get("maxLeverage", 50)
                        
                        # Ensure entry exists
                        if symbol not in latest_prices:
                            latest_prices[symbol] = {
                                "symbol": symbol,
                                "price": float(ctx.get("midPx") or ctx.get("markPx") or 0),
                                "source": "hyperliquid",
                                "category": get_category(coin),  # Add category
                                "maxLeverage": max_leverage,
                                "timestamp": int(time.time() * 1000)
                            }
                        else:
                            # Re-assert source to be sure
                            latest_prices[symbol]["source"] = "hyperliquid"
                            latest_prices[symbol]["category"] = get_category(coin)  # Add category
                            latest_prices[symbol]["maxLeverage"] = max_leverage
                        
                        # dayNtlVlm is 24h volume
                        latest_prices[symbol]["volume_24h"] = float(ctx.get("dayNtlVlm", 0))
                        latest_prices[symbol]["openInterest"] = float(ctx.get("openInterest", 0))
                        
                        # premium/funding could also be added here
                        latest_prices[symbol]["funding"] = float(ctx.get("funding", 0))

                        # Calculate 24h Change
                        try:
                            prev_day_px = float(ctx.get("prevDayPx", 0))
                            mark_px = float(ctx.get("markPx", 0))
                            if prev_day_px > 0:
                                change_abs = mark_px - prev_day_px
                                change_pct = (change_abs / prev_day_px) * 100
                                
                                latest_prices[symbol]["change_24h"] = change_abs
                                latest_prices[symbol]["change_percent_24h"] = change_pct
                        except Exception:
                            pass
                            
                        # Add High/Low from tracker
                        hl_stats = hl_price_history.get_stats(symbol)
                        if hl_stats:
                            if hl_stats.get("high_24h"):
                                latest_prices[symbol]["high_24h"] = hl_stats["high_24h"]
                            if hl_stats.get("low_24h"):
                                latest_prices[symbol]["low_24h"] = hl_stats["low_24h"]
                        
                        count += 1
                
                if count > 0:
                     logger.info(f"Updated stats for {count} Hyperliquid assets")
                     
        except Exception as e:
            logger.error(f"Error polling Hyperliquid stats: {e}")
            
        await asyncio.sleep(60)  # Poll every 60s


async def bootstrap_hyperliquid_history():
    """Initial fetch of 24h high/low for all Hyperliquid assets via candles"""
    global latest_prices, hl_price_history
    
    logger.info("⚡ Bootstrapping Hyperliquid High/Low history...")
    try:
        data = await http_client.get_meta_and_asset_ctxs()
        if data and len(data) == 2:
            universe = data[0].get("universe", [])
            
            # Limit to top assets or process in chunks to avoid rate limits
            for i, asset in enumerate(universe):
                coin = asset["name"]
                symbol = f"{coin}-USD"
                try:
                    # Extract Max Leverage
                    max_leverage = asset.get("maxLeverage", 50) # Use 50 as fallback if missing, but should be there

                    # Fetch 1d candle for current high/low
                    candles = await http_client.get_candles(coin, interval="1d")
                    if candles:
                        latest_candle = candles[-1]
                        high = float(latest_candle.get("high", 0))
                        low = float(latest_candle.get("low", 0))
                        
                        if high > 0:
                            hl_price_history.update_price(symbol, high)
                        if low > 0:
                            hl_price_history.update_price(symbol, low)
                            
                        # Ensure latest_prices has the data, initializing if needed
                        if symbol not in latest_prices:
                            latest_prices[symbol] = {
                                "symbol": symbol, 
                                "source": "hyperliquid",
                                "category": get_category(coin),  # Add category
                                "maxLeverage": max_leverage,     # Add maxLeverage
                                "price": 0, # Will be updated by WS
                                "change_24h": 0,
                                "change_percent_24h": 0,
                                "volume_24h": 0
                            }
                        else:
                             latest_prices[symbol]["category"] = get_category(coin)
                             latest_prices[symbol]["maxLeverage"] = max_leverage
                        
                        latest_prices[symbol]["high_24h"] = high
                        latest_prices[symbol]["low_24h"] = low
                    
                    # Small delay to be polite to the API
                    if i % 10 == 0:
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    # logger.warning(f"Failed to bootstrap {coin}: {e}")
                    continue
            
            logger.info(f"✅ Bootstrapped High/Low for {len(universe)} HL symbols")
    except Exception as e:
        logger.error(f"❌ Error bootstrapping HL history: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events"""
    global hyperliquid_client, ostium_client, ostium_poller, ostium_subgraph, ostium_candle_generator, ostium_persister
    
    # Startup
    logger.info("🚀 Starting Osmo Backend...")
    logger.info(f"Environment: {settings.ENV}")
    
    # Load persistence
    ostium_price_history.load_from_disk()
    hl_price_history.load_from_disk("/tmp/hl_history_snapshot.json")
    
    # Initialize Persistence
    candle_queue = asyncio.Queue()
    ostium_candle_generator = CandleGenerator(queue=candle_queue)
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
        ws_url = settings.HYPERLIQUID_WS_URL or "wss://api.hyperliquid.xyz/ws"
        logger.info(f"🔌 Connecting to Hyperliquid WS at: {ws_url}")
        
        hyperliquid_client = HyperliquidWebSocketClient(ws_url)
        await hyperliquid_client.connect()
        logger.info("✅ Connection established, subscribing to allMids...")
        
        await hyperliquid_client.subscribe("allMids", handle_hyperliquid_message)
        logger.info("✅ Subscribed to allMids, starting listen loop...")
        
        asyncio.create_task(hyperliquid_client.listen())
        logger.info("✅ Hyperliquid WebSocket client started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start Hyperliquid client: {e}", exc_info=True)
        
    # Start Hyperliquid Stats Poller & Bootstrap
    asyncio.create_task(poll_hyperliquid_stats())
    asyncio.create_task(bootstrap_hyperliquid_history())
    
    # Start Ostium API poller
    try:
        ostium_client = OstiumAPIClient(settings.OSTIUM_API_URL)
        ostium_poller = OstiumPoller(
            api_client=ostium_client,
            poll_interval=settings.OSTIUM_POLL_INTERVAL,
            callback=handle_ostium_message
        )
        await ostium_poller.start()
        
        # Start Ostium Subgraph Volume Poller (SDK)
        try:
            ostium_subgraph = OstiumSubgraphClient()
            asyncio.create_task(poll_ostium_volume())
            logger.info(f"✅ Ostium Subgraph Poller started")
        except Exception as e:
            logger.error(f"⚠️ Failed to start Subgraph Poller: {e}")
            
        logger.info(f"✅ Ostium poller started (interval: {settings.OSTIUM_POLL_INTERVAL}s)")
    except Exception as e:
        logger.error(f"❌ Failed to start Ostium poller: {e}")

    # Initialize Connector System
    try:
        await connector_registry.initialize(redis_url=settings.REDIS_URL)
        logger.info("✅ Connector system initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize connector system: {e}")
    
    # Initialize Database
    try:
        await init_db()
        logger.info("✅ Database initialized")
        
        # CLEAR TABLES FOR DEVELOPMENT (Per user request: store temporarily)
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("TRUNCATE TABLE candles RESTART IDENTITY CASCADE"))
                await session.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
                # Also truncate new trading tables if they exist
                try:
                    await session.execute(text("TRUNCATE TABLE orders RESTART IDENTITY CASCADE"))
                    await session.execute(text("TRUNCATE TABLE positions RESTART IDENTITY CASCADE"))
                except Exception:
                    pass
                await session.commit()
                logger.info("🧹 Development: Markets and Trading tables cleared for new session")
        except Exception as truncate_err:
            logger.warning(f"⚠️ Failed to clear some tables: {truncate_err}")
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Osmo Backend...")
    
    # CLEAR TABLES ON EXIT (Per user request)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("TRUNCATE TABLE candles RESTART IDENTITY CASCADE"))
            await session.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
            try:
                await session.execute(text("TRUNCATE TABLE orders RESTART IDENTITY CASCADE"))
                await session.execute(text("TRUNCATE TABLE positions RESTART IDENTITY CASCADE"))
            except Exception:
                pass
            await session.commit()
            logger.info("🧹 Development: Tables cleared on shutdown")
    except Exception as e:
        logger.error(f"⚠️ Failed to clear tables on shutdown: {e}")
    
    ostium_price_history.save_to_disk()
    hl_price_history.save_to_disk("/tmp/hl_history_snapshot.json")
    
    # Shutdown connector system
    await connector_registry.shutdown()
    
    if hyperliquid_client:
        await hyperliquid_client.disconnect()
    
    await redis_manager.disconnect()
    
    if ostium_persister:
        await ostium_persister.stop()

    if ostium_poller:
        await ostium_poller.stop()
    if ostium_client:
        await ostium_client.close()
    if ostium_subgraph:
        await ostium_subgraph.close()
    logger.info("✅ Shutdown complete")


# Initialize FastAPI
app = FastAPI(
    title="Osmo API",
    description="Trading & AI Agent API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
app.include_router(web3_router, prefix="/api/v1", tags=["web3"])

# Add Prometheus metrics to FastAPI
# We need to expose /metrics endpoint
from starlette.responses import Response
import time

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")

# Include Routers
from routers.user import router as user_router
from routers.leaderboard import router as leaderboard_router
from routers.orders import router as orders_router
from connectors.web3_arbitrum.api_routes import router as web3_router
from routers.usage import router as usage_router
from routers.portfolio import router as portfolio_router
from routers.agent import router as agent_router
from routers.markets import router as markets_router
from routers.connectors import router as connectors_router # NEW
from routers.history import router as history_router # NEW
from routers.watchlist import router as watchlist_router # NEW

app.include_router(user_router, prefix="/api/user", tags=["user"])
app.include_router(leaderboard_router, prefix="/api/leaderboard", tags=["leaderboard"])
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
app.include_router(web3_router, prefix="/api/v1", tags=["web3"])
app.include_router(usage_router, prefix="/api/usage", tags=["usage"])
app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(agent_router, prefix="/api/agent", tags=["agent"])
app.include_router(markets_router, prefix="/api/markets", tags=["markets"])
app.include_router(connectors_router, prefix="/api/connectors", tags=["connectors"]) # NEW: /api/connectors/hyperliquid/prices
app.include_router(history_router, prefix="/api/history", tags=["history"]) # NEW: /api/history
app.include_router(watchlist_router, tags=["watchlist"]) # NEW: /api/watchlist (prefix already in router)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health status"""
    hl_status = {"connected": False}
    try:
        hl_status = hyperliquid_client.get_status() if hyperliquid_client else {"connected": False}
    except Exception as e:
        logger.error(f"Health check: HL status fail: {e}")
    
    # Check Database
    db_connected = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_connected = True
    except Exception as e:
        logger.error(f"Health check: DB status fail: {e}")

    # Check Ostium
    ostium_connected = False
    try:
        if ostium_poller and ostium_poller.is_running:
            ostium_connected = True
    except Exception as e:
        logger.error(f"Health check: Ostium status fail: {e}")

    return {
        "status": "healthy",
        "hyperliquid": {
            "connected": hl_status.get("connected", False),
            "symbols": len(latest_prices),
            "subscriptions": hl_status.get("subscriptions", 0)
        },
        "ostium": {
            "connected": ostium_connected,
            "symbols": len([s for s in latest_prices if '-' in s and not s.endswith('-USD')]) , # Heuristic
            "last_poll": None 
        },
        "database": {
            "connected": db_connected
        },
        "redis": await redis_manager.get_status()
    }


# Candle history endpoint
@app.get("/api/candles/{symbol}")
async def get_candles(symbol: str, exchange: str = None, limit: int = 100):
    """Get OHLC candles for a symbol
    
    Args:
        symbol: Trading pair symbol (e.g., EUR-USD, BTC-USD)
        exchange: Exchange filter - 'ostium' or 'hyperliquid' (optional)
        limit: Number of candles to return (default 100)
    """
    # Route based on exchange parameter
    if exchange == "ostium":
        # Force Ostium Candle Generator
        if symbol in ostium_candle_generator.candles or symbol in ostium_candle_generator.current_candles:
            logger.info(f"📊 Fetching {limit} Ostium candles for {symbol}")
            return ostium_candle_generator.get_candles(symbol, limit)
        else:
            logger.warning(f"⚠️ No Ostium candles found for {symbol}")
            return []
    
    elif exchange == "hyperliquid":
        # Force Hyperliquid API
        try:
            coin = symbol.split("-")[0]
            end_time = int(time.time() * 1000)
            start_time = end_time - (limit * 60 * 1000)
            
            logger.info(f"📊 Fetching {limit} Hyperliquid candles for {coin}")
            candles = await http_client.get_candles(coin, interval="1m", start_time=start_time, end_time=end_time)
            return candles
        except Exception as e:
            logger.error(f"Failed to fetch Hyperliquid candles for {symbol}: {e}")
            return []
    
    else:
        # Auto-detect: Try Ostium first, then Hyperliquid
        if symbol in ostium_candle_generator.candles or symbol in ostium_candle_generator.current_candles:
            return ostium_candle_generator.get_candles(symbol, limit)
        
        # Try Hyperliquid API
        try:
            coin = symbol.split("-")[0]
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
    
    # DEBUG: Log first market keys to verify category/leverage presence
    if latest_prices:
        first_key = list(latest_prices.keys())[0]
        logger.info(f"DEBUG /api/markets sample ({first_key}): {latest_prices[first_key].keys()} | Category: {latest_prices[first_key].get('category')} | Leverage: {latest_prices[first_key].get('maxLeverage')} | Vol: {latest_prices[first_key].get('volume_24h')}")

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
    try:
        if symbol == "ALL":
            logger.info(f"📊 Sending {len(latest_prices)} keys to ALL client")
            payload = json.dumps({
                "type": "price_update",
                "data": latest_prices
            })
            await websocket.send_text(payload)
            logger.info("✅ Initial prices sent to ALL client")
        elif symbol in latest_prices:
            # Send specific symbol price
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": latest_prices[symbol]
            }))
            logger.info(f"✅ Initial price sent for {symbol}")
    except Exception as e:
        logger.error(f"❌ Failed to send initial prices: {e}")
        # Don't close connection, just log the error
    
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


@app.websocket("/ws/ostium/{symbol}")
async def ostium_websocket(websocket: WebSocket, symbol: str):
    """Stream real-time Ostium prices to frontend"""
    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module="ostium", symbol=symbol).inc()
    
    logger.info(f"📡 Ostium client connected to {symbol}")
    
    # Send latest price immediately
    try:
        if symbol in latest_prices:
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": latest_prices[symbol]
            }))
            logger.info(f"✅ Initial Ostium price sent for {symbol}")
    except Exception as e:
        logger.error(f"❌ Failed to send initial Ostium price: {e}")
    
    try:
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received from Ostium client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"📴 Ostium client disconnected from {symbol}")
    
    finally:
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module="ostium", symbol=symbol).dec()


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
    """Subscribe to user notifications (Stub)"""
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


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
        reload=True,  # Hot reload for development Haus
        log_level=settings.LOG_LEVEL.lower()
    )
