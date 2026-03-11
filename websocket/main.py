from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# Trigger Reload 1
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram
import signal
import sys
import os
import logging
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Dict, Set, List, Any, Optional
import httpx

from config import settings
from Hyperliquid.websocket_client import HyperliquidWebSocketClient
from Hyperliquid.http_client import http_client
from Hyperliquid.normalizer import normalize_all_mids
from Ostium.api_client import OstiumAPIClient
from Ostium.poller import OstiumPoller
from Ostium.normalizer import normalize_ostium_prices
from Ostium.price_history import PriceHistoryTracker
from Ostium.price_history import PriceHistoryTracker
from Ostium.subgraph_client import OstiumSubgraphClient  # New
from sqlalchemy import text
from database.connection import init_db, AsyncSessionLocal
from database import models
from database.models import Trade
from storage.redis_manager import redis_manager

# Import connector system
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from connectors.web3_arbitrum.api_routes import router as web3_router
from connectors.hyperliquid.category_map import get_category  # Import category mapping

# Import orders API
from routers.orders import router as orders_router
from services.canonical_source_registry import canonical_registry
from services.client_registry import get_exchange_client
from connectors.init_connectors import connector_registry
from services.price_pusher import price_pusher
from services.price_monitor_service import price_monitor_service
from services.ai_trigger_service import ai_trigger_service


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
connected_clients: Dict[str, Set[WebSocket]] = {}  # symbol -> set of websockets
connected_l2book_clients: Dict[str, Set[WebSocket]] = {}
connected_trades_clients: Dict[str, Set[WebSocket]] = {}
latest_prices: Dict[str, dict] = {}  # symbol -> latest price data
_COMMODITY_BASES = {"XAU", "XAG", "WTI", "BRN", "NG", "GC", "SI", "HG", "CL"}

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
    
    # Update price monitor service with latest prices
    price_monitor_service.update_prices(latest_prices)
    
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
        logger.warning(f"âš ï¸ L2Book data missing 'coin' field: {data.keys()}")
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
        logger.warning(f"âš ï¸ Trades data is not a non-empty list: {type(data)}")
        return
        
    coin = data[0].get("coin")
    if not coin:
        logger.warning(f"âš ï¸ Trades data missing 'coin' field in first element: {data[0].keys()}")
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
    global latest_prices, ostium_price_history
    
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
                    logger.info(f"âœ… Updated volume/OI for {count} Ostium symbols")
                else:
                    logger.warning(f"âš ï¸ Polled Ostium Subgraph but found 0 matches in latest_prices. (Total pairs: {len(pairs_data)})")
                    
        except Exception as e:
            logger.error(f"âŒ Error in volume poller: {e}")
            
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
    
    logger.info("âš¡ Bootstrapping Hyperliquid High/Low history...")
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
                    
                    # Delay to avoid Hyperliquid 429 rate limit
                    if i % 5 == 0:
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    # logger.warning(f"Failed to bootstrap {coin}: {e}")
                    continue
            
            logger.info(f"âœ… Bootstrapped High/Low for {len(universe)} HL symbols")
    except Exception as e:
        logger.error(f"âŒ Error bootstrapping HL history: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events"""
    global hyperliquid_client, ostium_client, ostium_poller, ostium_subgraph, ostium_candle_generator, ostium_persister
    
    # Startup
    logger.info("ðŸš€ Starting Osmo Backend...")
    logger.info(f"Environment: {settings.ENV}")

    # Initialize Database FIRST to ensure tables exist for background services
    try:
        await init_db()
        logger.info("âœ… Database initialized")
        
        # Tables are preserved across restarts so simulation balance and positions persist.
        # To manually clear: psql -c "TRUNCATE TABLE orders, positions, ledger_accounts;"
            
    except Exception as e:
        logger.error(f"â Œ Database initialization failed: {e}")
    
    # Load persistence only when explicitly allowed (dev mode is in-memory only).
    if not settings.WS_IN_MEMORY_ONLY:
        ostium_price_history.load_from_disk()
        hl_price_history.load_from_disk("/tmp/hl_history_snapshot.json")
    
    # Disable local candle generator and DB persister as requested by user
    ostium_candle_generator = None
    ostium_persister = None
    
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
        logger.info(f"ðŸ”Œ Connecting to Hyperliquid WS at: {ws_url}")
        
        hyperliquid_client = HyperliquidWebSocketClient(ws_url)
        await hyperliquid_client.connect()
        logger.info("âœ… Connection established, subscribing to allMids...")
        
        await hyperliquid_client.subscribe("allMids", handle_hyperliquid_message)
        logger.info("âœ… Subscribed to allMids, starting listen loop...")
        
        asyncio.create_task(hyperliquid_client.listen())
        logger.info("âœ… Hyperliquid WebSocket client started successfully")
    except Exception as e:
        logger.error(f"âŒ Failed to start Hyperliquid client: {e}", exc_info=True)
        
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
            logger.info(f"âœ… Ostium Subgraph Poller started")
        except Exception as e:
            logger.error(f"âš ï¸ Failed to start Subgraph Poller: {e}")
            
        logger.info(f"âœ… Ostium poller started (interval: {settings.OSTIUM_POLL_INTERVAL}s)")
        
        # Start Price Pusher (Sync to on-chain OrderRouter + CustomMarketDataFeed)
        asyncio.create_task(price_pusher.start(latest_prices, connected_clients))
        logger.info("✅ Price Pusher started")
    except Exception as e:
        logger.error(f"âŒ Failed to start Ostium poller: {e}")

    # Start Indexer Service (Hybrid Architecture)
    try:
        print("DEBUG: Loading indexer_service...")
        from services.indexer_service import indexer_service
        print("DEBUG: Starting indexer_service task...")
        asyncio.create_task(indexer_service.start())
        logger.info("âœ… Indexer Service started (Listening to On-Chain Events)")
        
        # Start Simulation Matching Engine
        print("DEBUG: Loading matching_engine...")
        from services.matching_engine import simulation_matching_engine
        print("DEBUG: Starting matching_engine task...")
        asyncio.create_task(simulation_matching_engine.start())
        logger.info("âœ… Simulation Matching Engine started")
        
        # Start Price Monitor Service (GP/GL monitoring)
        try:
            from services.ai_trigger_service import ai_trigger_service
            from services.binance_candle_service import binance_candle_service
            
            # Start Binance Candle Service (BTC & ARB)
            asyncio.create_task(binance_candle_service.start())
            logger.info("✅ Binance Candle Service started")

            ai_callback = await ai_trigger_service.create_ai_trigger_callback()
            price_monitor_service.set_ai_trigger_callback(ai_callback)
            await price_monitor_service.start(latest_prices)
            logger.info("✅ Price Monitor Service started (GP/GL monitoring)")
        except Exception as e:
            logger.error(f"❌ Failed to start Trading Services: {e}")
        
    except Exception as e:
        logger.error(f"âŒ Failed to start Indexer/Matching Services: {e}")

    # Initialize Connector System
    try:
        asyncio.create_task(connector_registry.initialize(redis_url=settings.REDIS_URL))
        logger.info("âœ… Connector system initialized")
    except Exception as e:
        logger.error(f"âŒ Failed to initialize connector system: {e}")
    
    yield
    
    # Shutdown
    logger.info("ðŸ›‘ Shutting down Osmo Backend...")
    
    # Tables are preserved on shutdown so simulation balance and positions persist across restarts.
    # To manually clear: psql -c "TRUNCATE TABLE orders, positions, ledger_accounts;"
    
    if not settings.WS_IN_MEMORY_ONLY:
        ostium_price_history.save_to_disk()
        hl_price_history.save_to_disk("/tmp/hl_history_snapshot.json")
    
    # Shutdown connector system
    await connector_registry.shutdown()
    
    # Stop price monitor service
    await price_monitor_service.stop()
    
    if hyperliquid_client:
        await hyperliquid_client.disconnect()
    
    await redis_manager.disconnect()
    
    if ostium_persister:
        await ostium_persister.stop()
        
    try:
        from services.binance_candle_service import binance_candle_service
        await binance_candle_service.stop()
    except Exception:
        pass

    if ostium_poller:
        await ostium_poller.stop()
    if ostium_client:
        await ostium_client.close()
    if ostium_subgraph:
        await ostium_subgraph.close()
    logger.info("âœ… Shutdown complete")


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
from routers.tools import router as tools_router
from routers.arena import router as arena_router
from routers.referrals import router as referrals_router
from routers.trade_setups import router as trade_setups_router  # NEW: GP/GL monitoring
from routers.tradebook import router as tradebook_router  # NEW: multi-exchange tradebook
from routers.global_chat import router as global_chat_router
from routers.icons import router as icons_router

app.include_router(icons_router, prefix="/api/icons", tags=["icons"])
app.include_router(user_router, prefix="/api/user", tags=["user"])
app.include_router(leaderboard_router, prefix="/api/leaderboard", tags=["leaderboard"])
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
app.include_router(arena_router, prefix="/api/arena", tags=["arena"])
app.include_router(referrals_router, prefix="/api/referrals", tags=["referrals"])
app.include_router(web3_router, prefix="/api/v1", tags=["web3"])
app.include_router(usage_router, prefix="/api/usage", tags=["usage"])

app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(agent_router, prefix="/api/agent", tags=["agent"])
app.include_router(markets_router, prefix="/api/markets", tags=["markets"])
app.include_router(connectors_router, prefix="/api/connectors", tags=["connectors"]) # NEW: /api/connectors/hyperliquid/prices
app.include_router(history_router, prefix="/api/history", tags=["history"]) # NEW: /api/history
app.include_router(watchlist_router, tags=["watchlist"]) # NEW: /api/watchlist (prefix already in router)
app.include_router(tools_router)
app.include_router(trade_setups_router)  # NEW: /api/trade-setups (GP/GL monitoring)
app.include_router(tradebook_router, prefix="/api/tradebook", tags=["tradebook"])  # REST: /api/tradebook/{symbol}/orderbook
app.include_router(tradebook_router)  # WS: /ws/orderbook/{symbol} and /ws/trades/{symbol}
app.include_router(global_chat_router, prefix="/api/chat", tags=["chat"])

# Serve locally cloned icon repos as static files — eliminates GitHub/jsDelivr CDN hops
import os as _os
_ICON_REPOS_DIR = next((p for p in ['/app/icon-repos', '/root/icon-repos'] if _os.path.isdir(p)), None)
if _ICON_REPOS_DIR:
    app.mount("/icons", StaticFiles(directory=_ICON_REPOS_DIR), name="icon-repos")



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
async def get_candles(
    symbol: str,
    exchange: str = None,
    limit: int = 100,
    resolution: str = None,
    timeframe: str = None,
):
    """Get OHLC candles for a symbol, routed to connectors.py robust implementation."""
    from routers.connectors import get_candles as connector_get_candles

    def to_timeframe(raw: str) -> str:
        value = str(raw or "1m").strip().lower()
        mapping = {
            "1": "1m", "1m": "1m",
            "5": "5m", "5m": "5m",
            "15": "15m", "15m": "15m",
            "30": "30m", "30m": "30m",
            "60": "1h", "1h": "1h",
            "240": "4h", "4h": "4h",
            "1d": "1d", "d": "1d",
            "1w": "1w", "w": "1w",
            "1mo": "1mo", "m": "1mo",
        }
        return mapping.get(value, "1m")

    tf = to_timeframe(timeframe or resolution or "1m")
    
    return await connector_get_candles(
        symbol=symbol,
        timeframe=tf,
        limit=limit,
        exchange=exchange,
        asset_type="crypto" # fallback mapping
    )
# NOTE: /api/markets is now handled by routers/markets.py (mounted at prefix /api/markets)
# which queries ALL exchanges (hyperliquid, ostium, aster, vest, avantis, orderly, paradex, dydx, aevo).
# The old endpoint here only returned latest_prices (Hyperliquid WS + Ostium poller).

_PRICE_WS_REFRESH_SECONDS = 2.0
_EXCHANGE_SNAPSHOT_TTL_SECONDS = 6.0
_exchange_snapshot_cache: Dict[str, List[Dict[str, Any]]] = {}
_exchange_snapshot_cache_ts: Dict[str, float] = {}
_exchange_snapshot_locks: Dict[str, asyncio.Lock] = {}


def _normalize_symbol_ws(raw: str) -> str:
    return str(raw or "").strip().upper().replace("/", "-").replace("_", "-")


def _symbol_candidates_ws(symbol: str) -> List[str]:
    normalized = _normalize_symbol_ws(symbol)
    candidates = {normalized}
    compact = normalized.replace("-", "")
    if compact:
        candidates.add(compact)
    parts = [p for p in normalized.split("-") if p]
    if len(parts) == 2:
        base, quote = parts
        candidates.add(f"{base}{quote}")
        if quote == "USD":
            candidates.add(f"{base}-USDT")
            candidates.add(f"{base}USDT")
            candidates.add(f"{base}-USDC")
            candidates.add(f"{base}USDC")
        if quote in {"USDT", "USDC"}:
            candidates.add(f"{base}-USD")
            candidates.add(f"{base}USD")
    return list(candidates)


def _to_float_ws(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        return f if f == f else default
    except Exception:
        return default


def _price_payload_from_row(row: Dict[str, Any], symbol: str, exchange: str) -> Dict[str, Any]:
    payload = dict(row or {})
    payload["symbol"] = symbol
    payload["source"] = exchange
    payload["price"] = _to_float_ws(payload.get("price"), 0.0)
    payload["high_24h"] = _to_float_ws(payload.get("high_24h"), _to_float_ws(payload.get("high24h"), 0.0))
    payload["low_24h"] = _to_float_ws(payload.get("low_24h"), _to_float_ws(payload.get("low24h"), 0.0))
    payload["volume_24h"] = _to_float_ws(payload.get("volume_24h"), _to_float_ws(payload.get("volume24h"), 0.0))
    payload["change_24h"] = _to_float_ws(payload.get("change_24h"), _to_float_ws(payload.get("change24h"), 0.0))
    payload["change_percent_24h"] = _to_float_ws(
        payload.get("change_percent_24h"), _to_float_ws(payload.get("change24hPercent"), 0.0)
    )
    payload["funding_rate"] = _to_float_ws(payload.get("funding_rate"), _to_float_ws(payload.get("fundingRate"), 0.0))
    payload["timestamp"] = int(time.time() * 1000)
    return payload


async def _fetch_symbol_snapshot(exchange: str, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from routers.markets import _fetch_exchange  # local import to avoid heavy import at startup
        now = time.time()
        rows = _exchange_snapshot_cache.get(exchange)
        ts = _exchange_snapshot_cache_ts.get(exchange, 0.0)
        if not rows or (now - ts) > _EXCHANGE_SNAPSHOT_TTL_SECONDS:
            lock = _exchange_snapshot_locks.setdefault(exchange, asyncio.Lock())
            async with lock:
                # Double-check after waiting lock
                now = time.time()
                rows = _exchange_snapshot_cache.get(exchange)
                ts = _exchange_snapshot_cache_ts.get(exchange, 0.0)
                if not rows or (now - ts) > _EXCHANGE_SNAPSHOT_TTL_SECONDS:
                    rows = await _fetch_exchange(exchange)
                    _exchange_snapshot_cache[exchange] = rows or []
                    _exchange_snapshot_cache_ts[exchange] = time.time()
        rows = rows or []
        if not rows:
            return None

        candidates = set(_symbol_candidates_ws(symbol))
        for row in rows:
            row_sym = _normalize_symbol_ws(row.get("symbol"))
            if not row_sym:
                continue
            if row_sym in candidates or row_sym.replace("-", "") in candidates:
                return _price_payload_from_row(row, symbol=symbol, exchange=exchange)
    except Exception as e:
        logger.debug(f"[WS] snapshot fetch failed {exchange}/{symbol}: {e}")
    return None


# WebSocket endpoint for Hyperliquid price streaming
@app.websocket("/ws/hyperliquid/{symbol}")
async def hyperliquid_websocket(websocket: WebSocket, symbol: str):
    """Stream real-time Hyperliquid prices to frontend"""
    symbol = _normalize_symbol_ws(symbol)
    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module="hyperliquid", symbol=symbol).inc()
    
    logger.info(f"ðŸ“¡ Client connected to {symbol}")
    
    # Send latest price immediately
    try:
        if symbol == "ALL":
            logger.info(f"ðŸ“Š Sending {len(latest_prices)} keys to ALL client")
            payload = json.dumps({
                "type": "price_update",
                "data": latest_prices
            })
            await websocket.send_text(payload)
            logger.info("âœ… Initial prices sent to ALL client")
        elif symbol in latest_prices:
            # Send specific symbol price
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": latest_prices[symbol]
            }))
            logger.info(f"âœ… Initial price sent for {symbol}")
        else:
            snapshot = await _fetch_symbol_snapshot("hyperliquid", symbol)
            if snapshot:
                latest_prices[symbol] = {**latest_prices.get(symbol, {}), **snapshot}
                await websocket.send_text(json.dumps({
                    "type": "price_update",
                    "data": latest_prices[symbol]
                }))
            else:
                await websocket.send_text(json.dumps({
                    "type": "price_update",
                    "data": {"symbol": symbol, "source": "hyperliquid", "price": 0, "available": False}
                }))
    except Exception as e:
        logger.error(f"âŒ Failed to send initial prices: {e}")
        # Don't close connection, just log the error
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Echo back for now (can add client commands later)
            logger.debug(f"Received from client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ Client disconnected from {symbol}")
    except RuntimeError as e:
        logger.info(f"WebSocket runtime close ({symbol}): {e}")
    
    finally:
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module="hyperliquid", symbol=symbol).dec()


@app.websocket("/ws/{exchange}/{symbol}")
async def exchange_websocket(websocket: WebSocket, exchange: str, symbol: str):
    """Stream real-time prices to frontend for various exchanges (ostium, aster, vest, avantis, hyperliquid, orderly, paradex, dydx, aevo)"""
    exchange = exchange.lower()
    symbol = _normalize_symbol_ws(symbol)
    # Avoid generic route swallowing dedicated websocket endpoints.
    if exchange == "notifications":
        await notification_websocket(websocket, symbol)
        return
    if exchange == "bridge":
        await bridge_websocket(websocket, symbol)
        return
    if exchange not in ["ostium", "aster", "vest", "avantis", "orderly", "paradex", "dydx", "aevo"]:
        if exchange == "hyperliquid": 
            pass # handled above
        else:
            await websocket.close()
            return

    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module=exchange, symbol=symbol).inc()
    
    logger.info(f"ðŸ“¡ {exchange.capitalize()} client connected to {symbol}")

    async def send_snapshot(force_fetch: bool = False):
        data = latest_prices.get(symbol)
        row_source = str((data or {}).get("source", "")).lower()
        if data and not force_fetch and (row_source in {"", exchange}):
            await websocket.send_text(json.dumps({"type": "price_update", "data": data}))
            return True

        if force_fetch and not data:
            # Send immediate placeholder so clients don't wait on slow upstream fetches.
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": {"symbol": symbol, "source": exchange, "price": 0, "available": False}
            }))
            return False

        snapshot = await _fetch_symbol_snapshot(exchange, symbol)
        if snapshot:
            latest_prices[symbol] = {**latest_prices.get(symbol, {}), **snapshot}
            await websocket.send_text(json.dumps({"type": "price_update", "data": latest_prices[symbol]}))
            return True

        if data and force_fetch:
            await websocket.send_text(json.dumps({"type": "price_update", "data": data}))
            return True

        await websocket.send_text(json.dumps({
            "type": "price_update",
            "data": {"symbol": symbol, "source": exchange, "price": 0, "available": False}
        }))
        return False

    refresh_task = None
    try:
        await send_snapshot(force_fetch=True)

        async def periodic_refresh():
            while True:
                await asyncio.sleep(_PRICE_WS_REFRESH_SECONDS)
                try:
                    await send_snapshot(force_fetch=False)
                except Exception as refresh_err:
                    logger.debug(f"[WS] periodic refresh failed {exchange}/{symbol}: {refresh_err}")
                    break

        refresh_task = asyncio.create_task(periodic_refresh())

    except Exception as e:
        logger.error(f"â Œ Failed to send initial {exchange.capitalize()} price: {e}")

    try:
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received from {exchange.capitalize()} client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ {exchange.capitalize()} client disconnected from {symbol}")
    except RuntimeError as e:
        logger.info(f"{exchange.capitalize()} websocket runtime close ({symbol}): {e}")
    
    finally:
        if refresh_task:
            refresh_task.cancel()
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module=exchange, symbol=symbol).dec()


@app.websocket("/ws/orderbook/{symbol}")
async def orderbook_websocket(websocket: WebSocket, symbol: str, exchange: str = "hyperliquid"):
    """
    Stream orderbook data — routes to the multi-exchange tradebook router.
    For Hyperliquid: subscribes to native WS l2Book feed.
    For all others: polls exchange REST API via tradebook modules.
    """
    from routers.tradebook import ws_orderbook
    await ws_orderbook(websocket, symbol=symbol, exchange=exchange, interval=1.5)


@app.websocket("/ws/trades/{symbol}")
async def trades_websocket(websocket: WebSocket, symbol: str, exchange: str = "hyperliquid"):
    """
    Stream recent trades — routes to the multi-exchange tradebook router.
    For Hyperliquid: subscribes to native WS trades feed.
    For all others: polls exchange REST API via tradebook modules.
    """
    from routers.tradebook import ws_trades
    await ws_trades(websocket, symbol=symbol, exchange=exchange, interval=2.0)


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
    """Subscribe to user-specific notifications (Trade fills, PnL updates, etc.)"""
    await websocket.accept()
    address = address.lower()
    
    # Send initial state
    try:
        from services.order_service import OrderService
        order_service = OrderService()
        state = await order_service.get_user_positions(address)
        await websocket.send_json({
            "type": "initial_state",
            "data": state
        })
    except Exception as e:
        logger.error(f"Error sending periodic state to {address}: {e}")

    # Subscribe to Redis for this user
    pubsub = redis_manager._redis.pubsub()
    channel = f"user_notifications:{address}"
    await pubsub.subscribe(channel)
    
    logger.info(f"ðŸ”” User {address} connected to real-time notifications")
    
    try:
        # Background task for this specific connection to listen to Redis
        async def listen_redis():
            try:
                async for message in pubsub.listen():
                    if message['type'] == 'message':
                        try:
                            # Already JSON string from LedgerService
                            # or Dict if published as dict
                            data = message['data']
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            
                            await websocket.send_text(data if isinstance(data, str) else json.dumps(data))
                        except Exception as e:
                            logger.error(f"Error relaying notification to {address}: {e}")
            except Exception as e:
                logger.error(f"Redis listener crashed for {address}: {e}")
        
        # Start redis listener as task
        redis_task = asyncio.create_task(listen_redis())
        
        # Keep connection alive
        while True:
            # Wait for client heartbeat or ignore incoming
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ Notification client disconnected: {address}")
    except Exception as e:
        logger.error(f"Error in notification socket for {address}: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        if 'redis_task' in locals():
            redis_task.cancel()


# IMPORTANT:
# Do not register process-level signal handlers at import time.
# Uvicorn manages SIGTERM/SIGINT for graceful shutdown; overriding them here
# causes noisy SystemExit/CancelledError tracebacks in Docker restarts.


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Hot reload for development Haus
        log_level=settings.LOG_LEVEL.lower()
    )

