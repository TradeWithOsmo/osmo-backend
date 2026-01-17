"""
README: Osmo Data Connectors

Complete data connector system for AI agent.
"""

# Osmo Data Connectors

**Status:** Phase 2 Complete ✅

Centralized data connector system providing unified access to 8 data sources for Osmo's AI agent.

---

## Quick Start

```python
from connectors.manager import ConnectorManager, AssetType
from connectors.hyperliquid import HyperliquidConnector
from connectors.chainlink import ChainlinkConnector

# Initialize manager
manager = ConnectorManager()

# Register connectors
manager.register_connector("hyperliquid", HyperliquidConnector({}))
manager.register_connector("chainlink", ChainlinkConnector({}))

# Get BTC price (auto-routed to Hyperliquid)
price = await manager.fetch_data(
    category=DataCategory.MARKET,
    symbol="BTC",
    asset_type=AssetType.CRYPTO
)

print(f"BTC: ${price['data']['price']}")
```

---

## Data Sources (8 Total)

| Source | Type | Purpose | Status |
|--------|------|---------|--------|
| **Hyperliquid** | WebSocket + HTTP | Crypto market data | ✅ Complete |
| **Ostium** | HTTP Polling | RWA price feeds | ✅ Complete |
| **Chainlink** | Oracle (Web3) | Price verification | ✅ Complete |
| **Dune Analytics** | On-chain queries | Whale tracking | ✅ Complete |
| **TradingView** | Frontend receiver | Pre-calculated indicators | ✅ Complete |
| **Web Search** | OpenRouter API | News + sentiment (Grok 2, Perplexity) | ✅ Complete |
| **mem0** | Memory layer | Conversation history + semantic search | 🔄 Next phase |
| **User Preferences** | PostgreSQL | Model selection, spending limits | 🔄 Next phase |

---

## Architecture

```
backend/connectors/
├── base_connector.py       # Abstract base class
├── manager.py              # Smart routing + caching
├── api_routes.py           # FastAPI endpoints
│
├── hyperliquid/            # Crypto connector
├── ostium/                 # RWA connector
├── chainlink/              # Oracle connector
├── dune/                   # On-chain analytics
├── tradingview/            # Indicator receiver
├── web_search/             # Multi-model search
├── memory/                 # (Phase 3)
│
└── data/                   # Category modules
    ├── market/             # prices.py
    ├── indicators/         # receiver.py
    ├── user/               # (Phase 3)
    ├── analytics/          # (Phase 3)
    └── candles/            # (Phase 3)
```

---

## API Endpoints

### TradingView Indicators

**POST** `/api/connectors/tradingview/indicators`
```json
{
  "symbol": "BTC",
  "timeframe": "1H",
  "indicators": {
    "RSI_14": 42.5,
    "MACD_signal": 0.15,
    "EMA_9": 43200
  },
  "chart_screenshot": "data:image/png;base64,...",
  "timestamp": 1705417200000
}
```

**GET** `/api/connectors/tradingview/indicators/{symbol}/{timeframe}`

### Price Data

**GET** `/api/connectors/price/{symbol}?asset_type=crypto`

### Connector Status

**GET** `/api/connectors/status`

---

## Environment Variables

Add to `backend/websocket/.env`:

```bash
# Chainlink
CHAINLINK_RPC_URL=https://arb1.arbitrum.io/rpc
CHAINLINK_BACKUP_RPC=https://arbitrum.llamarpc.com

# Dune Analytics (ALREADY CONFIGURED ✅)
DUNE_API_KEY=sim_ju7v6eGbDcwPAExRM4Xy9cF5ifIkjxc7
DUNE_QUERY_WHALE_TRADES=1234567

# Web Search
OPENROUTER_API_KEY=your_key_here

# Redis (if not using existing)
REDIS_URL=redis://localhost:6379
```

---

## Dependencies

```bash
pip install dune-client==1.5.0
pip install web3==6.15.0
pip install httpx  # For OpenRouter API
```

---

## Usage Examples

See `example_usage.py` for complete examples:
- Basic price fetching
- Real-time subscriptions
- Multi-source aggregation
- TradingView indicators

---

## Next Phase (Phase 3)

- [ ] mem0 memory layer integration
- [ ] User preferences module
- [ ] Comprehensive unit tests
- [ ] Performance optimization
- [ ] Production deployment config

---

**Last Updated:** January 17, 2026  
**Phase:** 2 of 5 - Advanced Connectors **COMPLETE** ✅
