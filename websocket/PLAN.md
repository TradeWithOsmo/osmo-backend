# Backend Websocket & Data Architecture Plan

## 1. Overview
This architecture is designed to handle real-time trading data from two distinct sources: **Hyperliquid** (Crypto/Perpetuals) and **Ostium** (RWA/Forex). 

The system uses a **Hybrid Approach**:
- **Hyperliquid Module**: Connects via native WebSocket to stream real-time high-frequency data (Orderbook, Trades).
- **Ostium Module**: Uses an Indexer/Poller approach (via API/SDK) to fetch Oracle-based prices.
- **In-Memory Streaming (Dev Focus)**: For development efficiency, data will be streamed directly to the frontend via WebSocket without persistent storage. 
- **Database (PostgreSQL)**: When storage is enabled (`SAVE_TO_DB=True`), the system targets **PostgreSQL** (optimally with TimescaleDB) for robust time-series management, replacing simple SQLite.
- **Ostium Polling Optimization**: Test various polling intervals (50ms to 2000ms) to find the optimal balance between real-time data and API rate limits. Results will determine production `OSTIUM_POLL_INTERVAL`.

### Deployment Strategy: Dockerization
To simplify development and deployment, the entire backend will be containerized.
*   **Container Isolation**: The `osmo-backend` service runs in a Docker container, ensuring consistent environments across dev and prod.
*   **Orchestration**: `docker-compose` will manage the backend service, PostgreSQL database, and Redis (for Pub/Sub and session management).
*   **Hot Reload**: Local development will use volume mounts to enable hot-reloading without rebuilding images.
*   **Horizontal Scaling**: Redis Pub/Sub enables horizontal scaling beyond single-instance WebSocket limits.
*   **Connection Pooling**: For Hyperliquid, use 1 upstream WebSocket connection per symbol, then broadcast to N downstream clients via Redis Pub/Sub to reduce load.

### Development Strategy: Modular Architecture
To ensure ease of debugging and maintenance, the system follows a **Strict Modular Architecture**:
*   **Decoupled Modules**: The Hyperliquid and Ostium logic are completely separated. A failure in one module (e.g., Ostium Polling) will NOT crash the other (Hyperliquid WS).
*   **Independent Services**: Each module runs its own async tasks, managed by the main FastAPI app.
*   **Debug Endpoints**: Each module exposes specific `/debug` endpoints (e.g., `/debug/hyperliquid/status`, `/debug/ostium/prices`) to inspect its internal state without needing to attach a debugger.

## 2. Target Folder Structure
The implementation will be organized as follows:

```
d:/WorkingSpace/backend/
└── websocket/
    ├── database/          # Database Interaction (SQLAlchemy Models)
    │   └── dbwebsocket/   
    ├── Hyperliquid/       # Hyperliquid connection logic & WS clients
    │   └── Test/          # Isolated tests for Hyperliquid module
    ├── Ostium/            # Ostium polling/SDK interaction logic
    │   └── Test/          # Isolated tests for Ostium module
    ├── Resources/         # Documentation (Existing)
    ├── Dockerfile         # Docker build instructions
    ├── docker-compose.yml # Service orchestration (App + Postgres + Redis)
    ├── .env.example       # Environment variable template
    └── requirements.txt
```

### Folder Breakdown

#### `database/dbwebsocket/`
Handles all database operations:
- Table schemas (trades, candles, user sessions)
- Connection pooling and session management
- Query builders and CRUD operations
- Data persistence logic

#### `Hyperliquid/`
Manages real-time WebSocket connections to Hyperliquid:
- WebSocket connection lifecycle (connect, reconnect, disconnect)
- Message parsing (binary and JSON formats)
- Subscription management per symbol (orderbook, trades, ticker)
- Rate limiting enforcement (1200 requests/minute)
- Data normalization to unified schema
- Unit tests for connection stability and parsing accuracy

#### `Ostium/`
Handles Ostium API polling and Oracle price integration:
- HTTP client with circuit breaker pattern
- Background polling service with configurable intervals
- Oracle price response parsing
- Data normalization to unified schema
- Builder fee injection for revenue generation
- Polling optimization tests (50ms to 3000ms intervals)

#### `Resources/`
Documentation reference library (**Read-only**):
- Hyperliquid API specifications, WebSocket guides, signing methods
- Ostium API documentation, Oracle mechanics, security audits

---

**Development Approach:**  
The `Hyperliquid/` and `Ostium/` modules can be developed **independently and in parallel**. Each module is completely self-contained with its own logic, tests, and dependencies. This allows for:
- **Parallel Development**: Different developers can work on Hyperliquid and Ostium simultaneously without conflicts.
- **Independent Testing**: Each module can be tested in isolation using its `Test/` directory.
- **Modular Deployment**: If one module fails, the other continues functioning (e.g., Ostium polling can fail without affecting Hyperliquid WebSocket).


## 3. Data Requirements
The following metrics will be collected and served to support the `Trade.tsx` and `Portfolio.tsx` pages.

### A. Market Data (Public)
**General Metrics (Header & Overview):**
*   **Price**: Last traded price.
*   **24h Change**: Percentage change.
*   **24h High/Low**: Highest and lowest prices in the last 24h (Crucial for Trade Header).
*   **24h Volume**: Total trading volume (USDC/Base).
*   **Market Cap**: Circulating Supply * Price.
*   **Mark Price**: Oracle/Index price for liquidations.
*   **Funding Rate**: Current rate & countdown time.
*   **Open Interest**: Total active contracts.

**Trading Components:**
*   **Chart**: OHLCV Candles (History) + Realtime Ticker.
*   **Orderbook**: Real-time Bids & Asks (Price, Size, Total) - *Hyperliquid mostly*.
*   **Recent Trades**: Stream of executed trades (Price, Size, Side, Time).

### B. User Specific Data (Private)
Required for `Portfolio.tsx` and Trade Page Panels.
*   **Balances**: Available USDC, Buying Power, Total Equity.
*   **Positions**:
    *   Entry Price, Mark Price, Liquidation Price.
    *   Size (Base asset), Value (USDC).
    *   Unrealized PnL (ROE %), Margin Types (Cross/Isolated).
    *   Leverage setting.
*   **Orders**: Active Limit/Stop orders (Price, Size, Filled Amount).
*   **History**: Past fills, realized PnL, fees paid.
*   **Account Performance**: Equity curve history (for Portfolio Overview).

### C. Hyperliquid Specific
Since Hyperliquid operates as a CLOB (Central Limit Order Book), we specifically need:
*   **Orderbook**: Real-time snapshot of Bids and Asks (L2 Data).
*   **Recent Trades**: Stream of the last executed trades.

*(Note: Ostium does not use a public Orderbook or Trade stream, as it uses an Oracle-based execution model)*.

## 4. Libraries & Dependencies
To achieve this, we will use the following technology stack:

### Core Framework
*   **fastapi**: For serving the unified WebSocket/REST API to the frontend.
*   **uvicorn**: ASGI server to run FastAPI.
*   **sqlalchemy**: ORM for interacting with the database in `backend/database/dbwebsocket`.
*   **psycopg2-binary**: PostgreSQL adapter for Python.

### Networking & Data
*   **websockets**: For connecting to Hyperliquid's WS feed.
*   **httpx**: For making async HTTP requests (Polling Ostium API).
*   **msgpack**: For decoding Hyperliquid's binary WS messages (performance).
*   **pandas**: For calculating 24h statistics and candle aggregation.

### SDKs (Optional/Reference)
*   **hyperliquid-python-sdk**: (Reference) official SDK for managing signing/execution.
*   **ostium-python-sdk**: (Reference/Usage) for interacting with Ostium contracts/data if API is insufficient.

## 5. Environment Variables
The following environment variables will configure the backend:

### Security
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `JWT_SECRET` | String | *Required* | Secret key for signing JWT tokens |
| `JWT_EXPIRY_HOURS` | Integer | `1` | JWT token expiration time |
| `CORS_ORIGINS` | String | `*` | Comma-separated allowed origins (production: whitelist only) |
| `PRIVY_APP_ID` | String | *Required* | Privy application ID for JWT verification |
| `PRIVY_APP_SECRET` | String | *Required* | Privy app secret for server-side verification |

### Database
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SAVE_TO_DB` | Boolean | `True` | Enable database persistence (use PostgreSQL even in dev) |
| `DATABASE_URL` | String | `postgresql://...` | PostgreSQL connection string |
| `DB_RETENTION_DAYS` | Integer | `7` | Auto-purge data older than N days |
| `DB_POOL_SIZE` | Integer | `20` | Database connection pool size |
| `DB_MAX_OVERFLOW` | Integer | `10` | Max overflow connections beyond pool size |

### Hyperliquid
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HYPERLIQUID_WS_URL` | String | `wss://api.hyperliquid.xyz/ws` | WebSocket endpoint |
| `HYPERLIQUID_API_URL` | String | `https://api.hyperliquid.xyz` | REST API endpoint |
| `HYPERLIQUID_RATE_LIMIT` | Integer | `1200` | Requests per minute limit |

### Ostium
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OSTIUM_API_URL` | String | `https://metadata-backend.ostium.io` | REST API base URL |
| `OSTIUM_POLL_INTERVAL` | Integer | `2` | Polling interval in seconds |
| `OSMO_BUILDER_ADDRESS` | String | `0x...` | Builder fee recipient address |
| `OSMO_BUILDER_FEE_BPS` | Integer | `50` | Builder fee in basis points (0.5% = 50) |

### Bridge Monitoring
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ARBITRUM_RPC_URL` | String | `https://arb1.arbitrum.io/rpc` | Arbitrum RPC endpoint |
| `BRIDGE_CONTRACT_ADDRESS` | String | `0x2df1...` | Hyperliquid Bridge contract address |
| `BRIDGE_POLL_INTERVAL` | Integer | `15` | Bridge event polling interval (seconds) |

### Performance & Scalability
| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REDIS_URL` | String | `redis://localhost:6379/0` | Redis connection for Pub/Sub |
| `REDIS_SENTINEL_ENABLED` | Boolean | `False` | Enable Redis Sentinel for HA (production) |
| `REDIS_SENTINEL_HOSTS` | String | `` | Comma-separated sentinel hosts (e.g., `host1:26379,host2:26379`) |
| `REDIS_USE_STREAMS` | Boolean | `True` | Use Redis Streams instead of Pub/Sub for guaranteed delivery |
| `REDIS_STREAM_MAX_LEN` | Integer | `10000` | Max length of Redis Streams (per symbol) |
| `WS_MAX_CONNECTIONS` | Integer | `1000` | Maximum concurrent WebSocket connections |
| `WS_MESSAGE_QUEUE_SIZE` | Integer | `100` | Message queue size per connection |
| `WS_QUEUE_OVERFLOW_STRATEGY` | String | `drop_oldest` | Queue overflow handling: `drop_oldest`, `drop_newest`, `disconnect` |
| `WS_RECONNECT_POLICY` | String | `auto` | Client reconnection: `auto` (server sends reconnect), `manual` (client decides) |
| `WS_MAX_MESSAGE_SIZE_KB` | Integer | `256` | Maximum WebSocket message size in KB |
| `LOG_LEVEL` | String | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `METRICS_ENABLED` | Boolean | `True` | Enable Prometheus metrics export |
| `METRICS_PORT` | Integer | `9090` | Prometheus metrics endpoint port |

## 6. API Endpoints Plan
The FastAPI backend will expose the following routes:

### Public Endpoints (Market Data)
*   **`GET /`** - Health check & service info
*   **`GET /health`** - Detailed health status (connection states, uptime, last poll times)
*   **`GET /api/markets`** - List all available markets (Hyperliquid + Ostium)
*   **`GET /api/market/{symbol}`** - Get specific market data (price, volume, funding, etc.)
*   **`GET /api/market/{symbol}/candles`** - Get OHLCV candles (`?interval=1m&from=...&to=...`)
*   **`GET /api/market/{symbol}/funding/history`** - Get historical funding rates

### WebSocket Endpoints (Real-time Streams)
*   **`WS /ws/hyperliquid/{symbol}`** - Subscribe to Hyperliquid market stream (orderbook, trades, ticker)
*   **`WS /ws/ostium/{symbol}`** - Subscribe to Ostium market stream (oracle prices)

### Execution Endpoints (Private - Requires Auth)
*   **`POST /api/order/place`** - Place new order (market/limit/stop)
*   **`POST /api/order/cancel`** - Cancel existing order
*   **`POST /api/order/modify`** - Modify order price/size

### User Endpoints (Private - Requires Auth)
*   **`GET /api/user/balance`** - Get user balances
*   **`GET /api/user/positions`** - Get open positions
*   **`GET /api/user/orders`** - Get active orders
*   **`GET /api/user/history`** - Get trade history
*   **`GET /api/user/notifications`** - Get user notifications (paginated)
*   **`PATCH /api/user/notifications/{id}/read`** - Mark notification as read

### Notifications (Real-time)
*   **`WS /ws/notifications`** - Subscribe to user-specific notifications
*   **`POST /api/notifications/preferences`** - Update notification preferences

### Bridge Endpoints
*   **`GET /api/bridge/deposits`** - Check deposit status for user
*   **`WS /ws/bridge/{address}`** - Subscribe to deposit events
*   **`POST /api/sign/construct-payload`** - Generate EIP-712 payload for withdrawals

### Debug Endpoints (Development Only)
*   **`GET /debug/hyperliquid/status`** - Hyperliquid module health & connection status
*   **`GET /debug/ostium/status`** - Ostium module health & latest prices
*   **`GET /debug/db/stats`** - Database statistics (if enabled)

## 7. Error Handling & Resilience
To ensure reliable data streaming, the system implements the following strategies:

### WebSocket Resilience (Hyperliquid)
*   **Auto-Reconnect**: On disconnect, the system will attempt to reconnect with exponential backoff (1s, 2s, 4s, 8s... max 60s).
*   **Heartbeat Management**: Send `ping` every 30 seconds to keep connection alive (Hyperliquid times out at 60s).
*   **Snapshot on Reconnect**: After reconnecting, request fresh snapshot to avoid stale data.
*   **Connection State Tracking**: Track `CONNECTING`, `CONNECTED`, `DISCONNECTED`, `RECONNECTING` states.

### API Resilience (Ostium Polling)
*   **Retry Logic**: On HTTP error, retry up to 3 times before marking as failed.
*   **Circuit Breaker**: After 5 consecutive failures, pause polling for 30 seconds.
*   **Graceful Degradation**: If Ostium API is down, continue serving last known prices with a "stale" flag.

### Rate Limiting
*   **Hyperliquid**: Respect 1200 requests/minute limit (per IP). Track usage internally.
*   **Ostium**: No strict documented limit, but implement 2-second minimum polling interval.

### Frontend Notification
*   When connection issues occur, push status message to frontend via existing WebSocket:
    ```json
    {"type": "system", "status": "reconnecting", "source": "hyperliquid"}
    ```

### WebSocket Queue Overflow Handling
*   **Strategy** (configurable via `WS_QUEUE_OVERFLOW_STRATEGY`):
    *   **`drop_oldest`** (Default): Remove oldest message from queue, add new one.
    *   **`drop_newest`**: Discard incoming message, keep queue intact.
    *   **`disconnect`**: Close connection with code 1008 (Policy Violation) + reason "Queue overflow".
*   **Metrics**: Track overflow events per connection (`osmo_ws_queue_overflows_total`).
*   **Client Warning**: Send system message before disconnect: `{"type": "system", "status": "warning", "message": "Message queue approaching limit"}`.

### Graceful Shutdown
*   **Signal Handling**: Intercept SIGTERM/SIGINT signals for clean shutdown.
*   **Connection Draining**: Send WebSocket close frames to all clients with 1000ms delay.
*   **Flush Pending Writes**: Write all buffered database records before exit.
*   **Timeout**: Force shutdown after 10 seconds if graceful shutdown hangs.

### WebSocket Reconnection Contract (Frontend)
*   **Auto-Reconnect**: Frontend should attempt reconnection with exponential backoff (1s, 2s, 4s, max 30s).
*   **Message Sequencing**: All messages include `seq_num` field (incremental per symbol).
*   **Gap Detection**: Frontend compares received `seq_num` with expected value.
*   **Gap Recovery**: On gap detection, frontend calls `GET /api/market/{symbol}/since/{seq_num}` to fetch missed messages.
*   **Server Reconnection Hint**: Server sends `{"type": "system", "action": "reconnect", "reason": "server_restart"}` before planned shutdown.
*   **Client State**: Frontend maintains connection state: `CONNECTING`, `CONNECTED`, `RECONNECTING`, `DISCONNECTED`.
*   **Max Reconnect Attempts**: After 10 failed attempts, prompt user to refresh page.

### Redis Message Delivery Guarantees
*   **Redis Streams**: Use Redis Streams instead of Pub/Sub for guaranteed message persistence.
*   **Consumer Groups**: Each backend instance is a consumer in a group (enables load balancing).
*   **Acknowledgment**: Messages are acknowledged after successful delivery to WebSocket client.
*   **Pending Messages**: Unacknowledged messages are retried (with 5s timeout).
*   **Stream Trimming**: Limit stream length to 10,000 messages per symbol (configurable via `REDIS_STREAM_MAX_LEN`).
*   **Fallback**: If Redis is unavailable, buffer messages in memory (max 1000 per symbol) and log WARNING.
*   **Message TTL**: Messages older than 60 seconds are dropped (prevent stale data delivery).
*   **Acceptable Loss**: For non-critical data (e.g., ticker updates), allow message loss rate <0.1%.

## 8. Authentication Strategy
For user-specific endpoints (positions, orders, balance):

### Privy Authentication Integration
The frontend uses **Privy** (`@privy-io/react-auth`) for wallet connection. Backend must support Privy's authentication flow:

*   **Step 1**: User authenticates with Privy on frontend (wallet signature or social login).
*   **Step 2**: Frontend receives Privy's JWT token.
*   **Step 3**: Frontend sends Privy JWT in `Authorization: Bearer <token>` header.
*   **Step 4**: Backend verifies Privy JWT using Privy's public API or verification library.
*   **Step 5**: Backend extracts wallet address from verified JWT claims.

### Session Management
*   **Privy JWT**: Frontend sends Privy-issued JWT (short-lived, 1-hour default).
*   **Backend Session**: Optionally issue custom JWT for extended sessions (configurable via `JWT_EXPIRY_HOURS`).
*   **Session Storage**: Store active sessions in Redis with wallet address as key.
*   **Concurrent Sessions**: Allow multiple devices per wallet (track device_id in session).

### Verification Flow
```python
# Pseudo-code for Privy JWT verification
privy_token = request.headers.get("Authorization").replace("Bearer ", "")
verified_claims = privy.verify_token(privy_token, app_id=PRIVY_APP_ID)
wallet_address = verified_claims["wallet"]["address"]
```

### Rate Limiting
*   **Per Wallet**: 100 requests/minute per wallet address.
*   **Per IP**: 1000 requests/minute per IP address.
*   **Implementation**: Use Redis with sliding window algorithm.

### Security Rules
*   **No Private Key Storage**: Backend NEVER stores user private keys.
*   **Privy Handles Auth**: All wallet authentication delegated to Privy.
*   **JWT Validation**: Verify Privy JWT signature and expiry on every protected endpoint.

## 9. Logging & Monitoring Strategy

### Log Levels
*   **DEBUG**: WebSocket raw messages, polling responses (disabled in production).
*   **INFO**: Connection events, successful requests, module startup/shutdown.
*   **WARNING**: Rate limit warnings, stale data, retry attempts.
*   **ERROR**: Connection failures, API errors, unexpected exceptions.

### Log Format
Structured JSON logging for easy parsing:
```json
{
  "timestamp": "2026-01-13T23:39:00Z",
  "level": "INFO",
  "module": "hyperliquid",
  "event": "ws_connected",
  "details": {"url": "wss://api.hyperliquid.xyz/ws"},
  "request_id": "uuid-1234-5678",
  "user_id": "0x...",
  "latency_ms": 45
}
```

### Metrics to Track
*   WebSocket uptime percentage (per module)
*   API request latency (avg, p95, p99)
*   Messages per second throughput
*   Error rate (errors/minute)
*   Active WebSocket connections (gauge)
*   Message queue depth per connection (histogram)
*   Database query latency (per operation type)
*   Redis Pub/Sub lag (time between publish and delivery)

### Metrics Export (Prometheus)
*   **Endpoint**: `GET /metrics` - Prometheus-compatible metrics endpoint
*   **Library**: `prometheus_client` for Python
*   **Metrics Format**:
    ```
    # HELP osmo_ws_connections Active WebSocket connections
    # TYPE osmo_ws_connections gauge
    osmo_ws_connections{module="hyperliquid",symbol="BTC-USD"} 42
    
    # HELP osmo_api_latency_seconds API request latency
    # TYPE osmo_api_latency_seconds histogram
    osmo_api_latency_seconds_bucket{endpoint="/api/market",le="0.1"} 1543
    ```
*   **Grafana Dashboards**: Pre-built dashboards for monitoring (store in `/monitoring/grafana/`)
*   **Alerts**: Configure Prometheus AlertManager for critical thresholds:
    *   WebSocket uptime < 95%
    *   API latency p99 > 500ms
    *   Error rate > 10/minute

## 10. WebSocket Message Format
The backend will send standardized messages to the frontend via WebSocket.

### Market Data Message
```json
{
  "type": "market_update",
  "source": "hyperliquid" | "ostium",
  "symbol": "BTC-PERP",
  "timestamp": 1705180740000,
  "data": {
    "price": "45123.5",
    "volume_24h": "12345678.90",
    "change_24h": "2.34",
    "high_24h": "45500.0",
    "low_24h": "44800.0",
    "funding_rate": "0.0001",
    "open_interest": "98765432.10"
  }
}
```

### Orderbook Update (Hyperliquid Only)
```json
{
  "type": "orderbook",
  "source": "hyperliquid",
  "symbol": "ETH-PERP",
  "timestamp": 1705180740000,
  "bids": [["2450.5", "10.5"], ["2450.0", "5.2"]],
  "asks": [["2451.0", "8.3"], ["2451.5", "12.1"]]
}
```

### Trades Stream (Hyperliquid Only)
```json
{
  "type": "trade",
  "source": "hyperliquid",
  "symbol": "SOL-PERP",
  "timestamp": 1705180740000,
  "price": "105.25",
  "size": "150.0",
  "side": "buy" | "sell"
}
```

### System Status Message
```json
{
  "type": "system",
  "status": "connected" | "reconnecting" | "error",
  "source": "hyperliquid" | "ostium",
  "message": "Connection established"
}
```

## 11. Development Workflow

### Initial Setup
```bash
# 1. Clone repository
cd d:/WorkingSpace/backend/websocket

# 2. Create .env file from template
cp .env.example .env

# 3. Start services with Docker Compose
docker-compose up --build

# Backend will be available at http://localhost:8000
# PostgreSQL will be available at localhost:5432 (if SAVE_TO_DB=True)
```

### Development Mode (Hot Reload)
```bash
# Run with live code reload
docker-compose up

# The container uses volume mounts, so code changes auto-reload
# No need to rebuild after changing Python files
```

### Running Tests
```bash
# Run Hyperliquid module tests
docker-compose exec backend pytest Hyperliquid/Test/

# Run Ostium module tests
docker-compose exec backend pytest Ostium/Test/

# Run all tests with coverage
docker-compose exec backend pytest --cov=. --cov-report=html
```

### Viewing Logs
```bash
# Follow backend logs in real-time
docker-compose logs -f backend

# View PostgreSQL logs
docker-compose logs -f postgres
```

### Accessing Debug Endpoints
```bash
# Check Hyperliquid module status
curl http://localhost:8000/debug/hyperliquid/status

# Check Ostium module status
curl http://localhost:8000/debug/ostium/status

# Check database stats (if enabled)
curl http://localhost:8000/debug/db/stats
```

### Stopping Services
```bash
# Stop and remove containers
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

## 12. Testing Strategy
To ensure system reliability without relying on live markets during CI.

### Tools & Libraries
*   **pytest**: Main testing framework.
*   **pytest-asyncio**: For testing async functions and WebSocket handlers.
*   **respx**: For mocking HTTP requests (Ostium API).
*   **AsyncMock**: For mocking WebSocket connections (Hyperliquid).

### Unit Testing Plan
*   **Hyperliquid Module**:
    *   Mock `websockets.connect`.
    *   Simulate incoming JSON messages (Orderbook/Trades).
    *   Verify data parsing and normalization logic.
    *   Test reconnection logic triggers.
*   **Ostium Module**:
    *   Use `respx` to mock `GET https://metadata-backend.ostium.io/...`.
    *   Test successful price parsing.
    *   Test handling of 429/500 errors (Circuit Breaker logic).
    *   **Polling Optimization Tests**: Run 10 test scenarios with different polling intervals to determine optimal latency vs. resource usage:
        *   **Test Environment**: Run against Ostium **testnet/staging API** (not production) to avoid rate limit impact.
        *   **Test 1**: `50ms` interval (20 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 2**: `100ms` interval (10 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 3**: `200ms` interval (5 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 4**: `250ms` interval (4 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 5**: `500ms` interval (2 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 6**: `750ms` interval (1.33 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 7**: `1000ms` interval (1 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 8**: `1500ms` interval (0.67 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 9**: `2000ms` interval (0.5 req/sec) - Measure: latency, CPU%, API errors
        *   **Test 10**: `3000ms` interval (0.33 req/sec) - Measure: latency, CPU%, API errors
    *   **Metrics to Track**:
        *   **Oracle Staleness**: Time difference between Oracle's last update and our poll timestamp
        *   **Price Change Detection Delay**: Time to detect 0.1% price change
        *   **HTTP Request Latency**: p50, p95, p99 latencies
        *   **CPU Usage**: Average CPU % during polling (isolate from other services)
        *   **Rate Limit Errors**: Count of 429 responses
    *   **Success Criteria**: Find interval where:
        *   Oracle staleness < 500ms on average (measure Oracle's own update timestamp)
        *   API error rate < 1%
        *   CPU usage < 10% (for polling alone)
        *   No rate limit (429) errors
        *   Price change detection delay < 1 second for 0.1% movements
    *   **Expected Optimal Range**: 250ms - 1000ms (based on Oracle update frequency)
    *   **Test Duration**: Run each interval test for 10 minutes minimum to collect statistically significant data

### Integration Testing
*   **WS Endpoint**: Test `ws://localhost:8000/ws` connectivity.
*   **Data Flow**: Verify that internal "mock" data is correctly broadcasted to connected frontend clients.

### Performance Testing
*   **Load Testing**: Simulate 1000+ concurrent WebSocket connections.
*   **Latency Benchmarks**: Measure orderbook update propagation time (target: <50ms p95).
*   **Memory Leak Tests**: Run long-lived WS connections for 24+ hours.
*   **Reconnection Storm**: Simulate all clients disconnecting simultaneously.

### Chaos Engineering Tests
To ensure resilience in production environments:
*   **Container Kill Test**: Randomly kill backend container during active connections (Docker restart).
*   **Network Partition**: Simulate network split between backend and Redis/PostgreSQL.
*   **Resource Starvation**: Limit CPU/memory to test graceful degradation.
*   **Upstream Failure**: Simulate Hyperliquid/Ostium API downtime (verify fallback behavior).
*   **Database Slowdown**: Inject latency in DB queries to test timeout handling.
*   **Redis Failure**: Test behavior when Redis Pub/Sub is unavailable.
*   **Tools**: Use `chaos-mesh`, `toxiproxy`, or Docker resource limits.

### Coverage Targets
*   **Critical Parsers**: 100% Coverage.
*   **Connection Managers**: >80% Coverage.
*   **Error Handlers**: 100% Coverage (Simulate all error types).

## 13. Data Normalization Strategy
To ensure the Frontend receives consistent data regardless of the source.

### Symbol Standardization
All symbols will be converted to a unified `BASE-QUOTE` format.
*   **Hyperliquid**: Raw `BTC` → Normalized `BTC-USD`
*   **Ostium**: Raw `EUR/USD` → Normalized `EUR-USD`
*   **Ostium**: Raw `XAU/USD` → Normalized `XAU-USD`

### Value Standardization
*   **Prices**: Returned as **Strings** to preserve precision (avoid floating point errors).
*   **Sizes**: Returned as **Strings**.
*   **Timestamps**: Unified to **Unix Milliseconds** (Integer).

### Object Schema
```json
// Normalized Trade Object
{
  "source": "hyperliquid",
  "symbol": "BTC-USD",  // Normalized
  "price": "45000.50",  // String
  "size": "0.15",       // String
  "side": "buy",        // Lowercase
  "timestamp": 1705180000123,
  "is_stale": false     // True if data >5s old
}
```

### Data Staleness Handling
*   **Timestamp All Messages**: Every message includes a server-side timestamp.
*   **Stale Flag**: Mark data as `is_stale: true` if older than 5 seconds.
*   **Frontend Timeout**: Frontend should display warning if no update received in 10 seconds.
*   **Health Endpoint**: `/health` reports staleness per symbol.

## 14. Revenue & Integration Strategy

### Ostium Builder Fees
To monetize the platform, we will leverage Ostium's **Builder Fee** system.
*   **Mechanism**: Every trade executed via our backend will include a `builder_address` and `builder_fee` (capped at 0.5%).
*   **Configuration**: Add `OSMO_BUILDER_ADDRESS` to `.env`.
*   **Implementation**: In the execution logic, inject these parameters into the trade payload.
*   **Verification & Audit**:
    *   **Logging**: Log every builder fee injection with structured data:
        ```json
        {
          "event": "builder_fee_injected",
          "user": "0x...",
          "symbol": "EUR-USD",
          "trade_value": "10000.00",
          "builder_fee_bps": 50,
          "builder_address": "0x...",
          "timestamp": 1705180000000
        }
        ```
    *   **Daily Verification**: Cron job runs daily to verify all logged `builder_address` values match `OSMO_BUILDER_ADDRESS`.
    *   **Alert on Mismatch**: Send critical alert if builder address differs from expected (potential compromise).
    *   **Metrics**: Track total builder fees collected per day (`osmo_builder_fees_usd_total`).
    *   **Audit Trail**: Store all builder fee logs in separate table for 1 year (compliance).

### Hyperliquid Bridge Monitoring
To improve user experience, the backend will monitor the Hyperliquid Bridge contract (`0x2df1...`) on Arbitrum.
*   **Goal**: Detect when a user deposits funds and notify the frontend immediately.
*   **Service**: A background task periodically checking for `Deposit` events for registered user addresses.

## 15. Execution Strategy

### Order Placement (Hyperliquid)
While data is read via standard WebSocket, execution requires strictly formatted **POST requests** (or specialized Signed WS messages).
*   **Endpoint**: `POST /exchange` via `https://api.hyperliquid.xyz`.
*   **Payload**: Requires `signature`, `timestamp` (nonce), and `action` (e.g., `{type: "limit", ...}`).
*   **Optimization**: Use a dedicated `aiohttp` session for execution to keep connections warm.

### HyperEVM Interaction
Since Hyperliquid uses a dual-chain architecture (L1 + EVM):
*   **Transfers**: User withdrawals to Arbitrum require signing a specific `WithdrawAction3` payload (EIP-712).
*   **Backend Role**: The backend will provide an endpoint `/api/sign/construct-payload` to help the frontend generate the correct EIP-712 object for the user to sign.

## 16. Historical Data Strategy

To support charting and historical analysis, the backend will generate and store historical candle data.

### Candle Generation
*   **Source**: Generate OHLCV candles from the trade stream (Hyperliquid) and polled prices (Ostium).
*   **Intervals**: Support multiple timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.
*   **Storage**: Use TimescaleDB continuous aggregates for efficient querying.
*   **Backfill**: On first run, backfill historical data from Hyperliquid API's `candleSnapshot` endpoint.
*   **Incremental Backfill**: Detect and fill gaps if server was offline (e.g., missing 10-minute window).
*   **Gap Detection**: Alert if missing candles are detected in the database.
*   **Gap Handling Strategy**:
    *   **Small Gaps** (<5 minutes): Fetch from upstream API if available, otherwise interpolate.
    *   **Large Gaps** (>5 minutes): Fetch from upstream API, mark as `backfilled=true` in DB.
    *   **Permanent Gaps** (upstream unavailable): Insert null candles with `is_gap=true` flag for UI clarity.
    *   **Alert**: Log WARNING and push notification to admin if gaps >30 minutes detected.

### Database Write Optimization
*   **Batch Writes**: Buffer trades and write in batches every 100ms or 1000 records (whichever comes first).
*   **Bulk Insert**: Use PostgreSQL `COPY` or bulk insert for better performance.
*   **Async Writes**: Write to database asynchronously to avoid blocking WebSocket message processing.

### Data Retention Policy
*   **Raw Trades**: 7 days (configurable via `DB_RETENTION_DAYS`).
*   **1-minute Candles**: 30 days.
*   **1-hour Candles**: 1 year.
*   **Daily Candles**: Indefinite.

### Archive Strategy
*   **Cold Storage**: Move old data to S3 or equivalent after retention period.
*   **Aggregated Views**: Keep pre-aggregated views for fast chart rendering.
*   **On-Demand Retrieval**: Fetch archived data only when explicitly requested by user.

### Database Migration Strategy
*   **Migration Tool**: Use **Alembic** for SQLAlchemy schema migrations.
*   **Migration Scripts**: Store in `database/migrations/` directory.
*   **Versioning**: Each migration has timestamp-based version (e.g., `2026_01_14_001_create_trades_table.py`).
*   **Automatic Migration**: On startup, check for pending migrations and apply if `AUTO_MIGRATE=True` (dev only).
*   **Production Migrations**: In production, require manual migration approval:
    ```bash
    # Review pending migrations
    docker-compose exec backend alembic current
    docker-compose exec backend alembic history
    
    # Apply migrations
    docker-compose exec backend alembic upgrade head
    ```
*   **Rollback Strategy**:
    *   Every migration must have a `downgrade()` function.
    *   Test rollback in staging before production deployment.
    *   Document rollback steps in migration docstring.
*   **Zero-Downtime Migrations**:
    *   **Additive Changes**: Add new columns/tables first, backfill data, then remove old schema.
    *   **Column Renames**: Use 3-step process (add new column, dual-write, remove old column).
    *   **Index Creation**: Create indexes with `CONCURRENTLY` option in PostgreSQL (non-blocking).
*   **Migration Testing**:
    *   All migrations tested in CI/CD pipeline against test database.
    *   Run `pytest database/Test/test_migrations.py` to verify migrations are reversible.

## 17. Security Considerations

Security is paramount for a financial application. The following measures will be implemented:

### Input Validation
*   **Schema Validation**: Use Pydantic models to validate all WebSocket messages and API requests.
*   **Symbol Sanitization**: Whitelist allowed symbols to prevent injection attacks.
*   **Rate Limiting**: Enforce strict rate limits per IP and per wallet address.

### Private Key Safety
*   **Never Log Sensitive Data**: NEVER log private keys, API secrets, or full signatures.
*   **Secure Memory**: Clear sensitive data from memory immediately after use.
*   **No Backend Signing**: Users sign all transactions client-side with their wallets.

### CORS Configuration
*   **Development**: Allow `*` for testing.
*   **Staging**: Use separate `CORS_ORIGINS_STAGING` environment variable.
*   **Production**: Whitelist only the production domain (e.g., `https://osmo.finance`).

### Dependency Security
*   **Pinned Versions**: All packages in `requirements.txt` must be pinned to specific versions.
*   **Automated Audits**: Run `pip-audit` in CI/CD pipeline to detect vulnerabilities.
*   **Monthly Updates**: Review and update dependencies monthly for security patches.

### API Key Management
*   **Environment Variables**: Store all API keys and secrets in `.env` (never commit to git).
*   **Quarterly Rotation**: Rotate `JWT_SECRET` and builder API keys every quarter.
*   **Separate Keys**: Use different keys for development, staging, and production environments.

### Deployment Security
*   **HTTPS Only**: All production traffic must use HTTPS (TLS 1.3).
*   **Firewall Rules**: Restrict database and Redis access to backend container only.
*   **Secrets Management**: Use Docker secrets or cloud provider secret managers in production.

### Deployment Rollback Strategy
*   **Docker Image Tagging**: Tag all images with version and commit SHA (e.g., `osmo-backend:v1.2.3-abc1234`).
*   **Image Registry**: Store last 10 production images in container registry.
*   **Rollback Procedure**:
    ```bash
    # Step 1: Identify previous working version
    docker images osmo-backend
    
    # Step 2: Update docker-compose.yml to previous version
    # image: osmo-backend:v1.2.2-xyz9876
    
    # Step 3: Rollback database migrations if needed
    docker-compose exec backend alembic downgrade -1
    
    # Step 4: Restart service with old image
    docker-compose up -d backend
    
    # Step 5: Verify health
    curl http://localhost:8000/health
    ```
*   **Database Rollback**: If new version included migrations, rollback must happen BEFORE container rollback.
*   **Feature Flags**: Use environment variables as feature flags for gradual rollout:
    *   `FEATURE_REDIS_STREAMS=False` (disable new feature if buggy)
    *   `FEATURE_NEW_ORDERBOOK_PARSER=False`
*   **Blue-Green Deployment** (Optional for production):
    *   Run two versions simultaneously (blue=current, green=new).
    *   Switch traffic via load balancer after verification.
    *   Keep blue version running for 1 hour as instant rollback option.
*   **Rollback Time Target**: Complete rollback in under 5 minutes.

## 18. AI Agent Integration

The `backend/agent` service will consume data from the `backend/websocket` service to power an AI trading assistant. The agent uses Langchain and LLM to analyze market data and provide insights.

### Data Access Methods

#### WebSocket Subscription (Real-time)
The AI Agent can subscribe to the same WebSocket streams as the frontend:
*   **Market Updates**: Subscribe to `/ws/hyperliquid/{symbol}` or `/ws/ostium/{symbol}` for real-time price, orderbook, and trade data.
*   **System Status**: Subscribe to system messages for connection health monitoring.
*   **Use Case**: Real-time pattern detection, anomaly detection, live sentiment analysis.

#### REST API Access (Historical)
The AI Agent can query historical data via REST endpoints:
*   **`GET /api/market/{symbol}/candles`** - Retrieve OHLCV data for technical analysis.
*   **`GET /api/market/{symbol}/funding/history`** - Analyze funding rate trends.
*   **`GET /api/user/history`** - Review past trades for performance analysis.
*   **Use Case**: Backtesting strategies, generating performance reports, risk assessment.

### AI Agent Requirements from WebSocket Backend

#### 1. **Tools Integration** (`backend/agent/Tools/`)
The agent needs access to market data fetchers:
*   **`get_current_price(symbol)`** - Fetch latest price from `/api/market/{symbol}`.
*   **`get_orderbook(symbol, depth=10)`** - Fetch orderbook snapshot.
*   **`get_historical_candles(symbol, interval, count)`** - Fetch N recent candles.
*   **`subscribe_to_symbol(symbol, callback)`** - Subscribe to real-time updates.

#### 2. **Knowledge Base** (`backend/agent/Knowledge/`)
Trading pattern definitions and strategy documents stored as JSON:
*   **Pattern Library**: Head & Shoulders, Bull Flag, Support/Resistance levels.
*   **Strategy Manuals**: Mean reversion rules, momentum indicators.
*   **Market Context**: Funding rate interpretations, OI analysis rules.

#### 3. **Memory** (`backend/agent/Memory/`)
Store conversation context and trading decisions:
*   **Short-term Memory**: Remember user's current positions, recent queries.
*   **Long-term Memory**: Track historical advice given, strategy performance.
*   **Database Schema**: `agent_conversations`, `agent_decisions`, `agent_feedback`.

#### 4. **Schema** (`backend/agent/Schema/`)
Pydantic models for structured data exchange:
*   **`MarketDataRequest`** - Request format for querying market data.
*   **`MarketDataResponse`** - Normalized response (matches WebSocket message format).
*   **`TradingSignal`** - Output format for agent's trading recommendations.

### AI-Specific Endpoints

Add these endpoints to the WebSocket backend to support AI Agent workflows:

*   **`POST /api/ai/analyze`** - Send batch of symbols for AI to analyze (returns signals).
*   **`GET /api/ai/context/{symbol}`** - Get comprehensive market context (price, volume, OI, funding, recent trades).
*   **`WS /ws/ai/signals`** - Stream AI-generated trading signals to frontend in real-time.

### Environment Variables for AI Integration

Add to `backend/websocket/.env`:
```bash
# AI Agent Integration
AI_AGENT_API_URL=http://localhost:8001  # Agent service URL
AI_WEBHOOK_SECRET=secure_random_string  # Verify AI agent requests
AI_RATE_LIMIT=100                       # Max AI requests per minute
```

### Security Considerations
*   **Authentication**: AI Agent must authenticate with a service token (different from user JWT).
*   **Rate Limiting**: Separate rate limit pool for AI to prevent resource exhaustion.
*   **Data Isolation**: AI should NOT access private user data without explicit permission.

## 19. Notification System

Real-time notifications keep users informed about critical events and trading activities.

### Notification Types
1.  **Trade Execution**: "Your limit order for BTC-PERP at $45,000 was filled."
2.  **Position Alerts**: "BTC-PERP position approaching liquidation price."
3.  **System Updates**: "Scheduled maintenance in 1 hour."
4.  **AI Signals**: "AI detected bullish pattern on ETH-PERP."

### Delivery Channels
*   **WebSocket**: Real-time push to connected clients (`/ws/notifications`).
*   **Database**: Store all notifications for history (`notifications` table).
*   **Email** (Optional): Critical alerts via email (liquidation warnings).

### Notification Schema
```json
{
  "id": "notif_123",
  "user_address": "0x...",
  "type": "trade_execution",
  "title": "Order Filled",
  "message": "Your limit order for BTC-PERP at $45,000 was filled.",
  "read": false,
  "timestamp": 1705180000000,
  "metadata": {
    "symbol": "BTC-PERP",
    "order_id": "order_456"
  }
}
```

### Notification Preferences
Users can configure notification preferences:
*   **Trade Executions**: On/Off
*   **Liquidation Warnings**: Always On (cannot disable)
*   **AI Signals**: On/Off

### Notification Delivery Reliability
*   **Multi-Channel Delivery**:
    *   **Primary**: WebSocket push (if user connected).
    *   **Fallback**: Store in database for later retrieval (if user offline).
    *   **Critical Alerts**: Email delivery for liquidation warnings (regardless of online status).
*   **Offline Handling**:
    *   All notifications stored in `notifications` table with `delivered` flag.
    *   On WebSocket reconnection, server sends `{"type": "sync_notifications", "unread_count": 5}`.
    *   Frontend calls `GET /api/user/notifications?unread=true` to fetch missed notifications.
*   **Delivery Confirmation**:
    *   Client sends `{"type": "ack_notification", "id": "notif_123"}` after receiving.
    *   Server marks notification as delivered after acknowledgment.
    *   Unacknowledged notifications are resent after 30 seconds (max 3 retries).
*   **Email Notifications** (Critical Only):
    *   **Triggers**: Liquidation warnings, deposit confirmations, security alerts.
    *   **Provider**: Use SendGrid or AWS SES.
    *   **Rate Limit**: Max 10 emails per user per day (prevent spam).
    *   **Opt-Out**: Users can disable non-critical emails (but not liquidation warnings).
*   **Push Notifications** (Optional - Future):
    *   Use Firebase Cloud Messaging (FCM) for mobile app push notifications.
    *   Requires user to grant permission in mobile app.

## 20. Infrastructure Cost Estimates

Estimated monthly operational costs for production deployment:

### Compute Resources
*   **Backend Service** (AWS ECS Fargate or DigitalOcean App Platform):
    *   **Specs**: 2 vCPU, 4GB RAM (auto-scaling 1-3 instances)
    *   **Cost**: $50-150/month

### Database
*   **PostgreSQL + TimescaleDB** (Managed Service):
    *   **Provider**: Timescale Cloud, AWS RDS, or DigitalOcean Managed Database
    *   **Specs**: 2 vCPU, 8GB RAM, 100GB SSD
    *   **Cost**: $100-200/month
*   **Storage Growth**: ~5GB/month (assuming 1000 daily active users)

### Redis
*   **Redis Cloud** or **AWS ElastiCache**:
    *   **Specs**: 1GB RAM (single instance in dev, cluster in prod)
    *   **Cost**: $20-80/month

### Bandwidth
*   **WebSocket Traffic**:
    *   **Assumption**: 1000 concurrent users, 10 messages/sec per user, 500 bytes/message
    *   **Calculation**: 1000 * 10 * 0.5KB * 86400 sec/day = ~432 GB/day = 13 TB/month
    *   **Cost**: $50-150/month (varies by provider; some include generous free tier)
*   **API Polling** (Ostium):
    *   **Negligible**: ~1 req/sec outbound = ~2.6 million requests/month = minimal bandwidth

### Third-Party Services
*   **Email Service** (SendGrid/AWS SES):
    *   **Volume**: ~10,000 emails/month
    *   **Cost**: $10-20/month
*   **Monitoring** (DataDog, New Relic, or self-hosted Grafana):
    *   **Cost**: $0-50/month (free tier or self-hosted)

### Total Estimated Cost
*   **Development**: $200-400/month (single instance, minimal redundancy)
*   **Production** (1000 active users): **$350-700/month**
*   **Production** (10,000 active users): **$800-1500/month** (requires horizontal scaling)

### Cost Optimization Strategies
*   **Use DigitalOcean or Hetzner**: ~30% cheaper than AWS for similar specs.
*   **Self-hosted PostgreSQL**: Save $100/month but requires DevOps expertise.
*   **Redis on same server**: Save $20-80/month (acceptable for dev/staging).
*   **CloudFlare CDN**: Reduce bandwidth costs by 50% with free caching.
*   **Reserved Instances**: 30-50% discount for 1-year commit (AWS/GCP).

### Cost Alerts
*   Set billing alerts at:
    *   **Warning**: $500/month
    *   **Critical**: $800/month
*   Monitor bandwidth usage (primary cost driver) with Prometheus metrics.

---

**Note:** Points System and Leaderboard features are planned but not yet finalized. These will be added in a future iteration.




