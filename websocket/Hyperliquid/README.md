# Hyperliquid Module

This module handles real-time WebSocket connections to Hyperliquid for:
- Market data streaming (orderbook, trades, ticker)
- Subscription management per symbol
- Message parsing (binary and JSON formats)
- Rate limiting (1200 requests/minute)
- Data normalization to unified schema
- Auto-reconnection with exponential backoff

## Status
**Phase 1**: Module structure only (no implementation yet)
**Phase 2**: Full WebSocket client implementation

## Future Structure
```
Hyperliquid/
├── __init__.py              # This file
├── websocket_client.py      # WebSocket connection manager
├── message_parser.py        # Parse Hyperliquid messages
├── subscriptions.py         # Manage symbol subscriptions
├── rate_limiter.py          # Enforce 1200 req/min limit
├── normalizer.py            # Normalize to unified schema
└── Test/                    # Unit tests
    ├── test_websocket.py
    ├── test_parser.py
    └── test_normalizer.py
```
