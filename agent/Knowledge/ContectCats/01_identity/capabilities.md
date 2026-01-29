# Tool Inventory ("What tools exist?")

## Data & Market Intelligence

### Market Data Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `get_price(symbol)` | Current price | Before any trade decision |
| `get_candles(symbol, tf)` | OHLCV data | For pattern analysis |
| `get_orderbook(symbol)` | L2 depth | Check liquidity before large orders |
| `get_funding_rate(symbol)` | Perp funding | Identify crowded trades |
| `get_ticker_stats(symbol)` | 24h volume/change | Gauge market activity |

### Technical Analysis Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `get_technical_analysis(symbol)` | Full TA report | Comprehensive market view |
| `get_patterns(symbol)` | Candlestick patterns | Identify reversals/continuations |
| `get_indicators(symbol)` | Indicator values | Confirm trade signals |
| `get_technical_summary(symbol)` | Text summary | Quick market snapshot |

### On-Chain Analytics Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `get_whale_activity(symbol)` | Large trades | Spot institutional moves |
| `get_token_distribution(symbol)` | Holder breakdown | Check concentration risk |

### Web Intelligence Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `search_news(query)` | Perplexity news | Before major events |
| `search_sentiment(symbol)` | Twitter/X sentiment | Gauge crowd emotion |

---

## Memory & Knowledge

### User Memory Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `add_memory(user_id, text)` | Store preference | When user states preference |
| `search_memory(user_id, query)` | Retrieve context | Before making suggestions |
| `get_recent_history(user_id)` | Recent interactions | Continue conversations |

### Knowledge Base Tools
| Tool | Description | When to Use |
|------|-------------|-------------|
| `search_knowledge_base(query)` | Query strategies | When user asks "how to" |

---

## Chart Control

### Symbol & Timeframe
| Tool | Parameters | Example |
|------|------------|---------|
| `set_symbol(target)` | ticker string | `set_symbol("ETHUSDT")` |
| `set_timeframe(tf)` | timeframe string | `set_timeframe("4h")` |

**Supported Timeframes:** 1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M

### Indicators (2-Step Process)
1. **Activate:** `add_indicator(name, inputs)`
2. **Read:** `get_indicators()` (via analysis.py)

**Supported Indicator Categories:**
- **Trend:** SMA, EMA, VWMA, SuperTrend, Ichimoku
- **Momentum:** RSI, MACD, Stochastic, CCI, Williams %R
- **Volatility:** ATR, Bollinger Bands, Keltner Channels
- **Volume:** OBV, VWAP, Volume Profile

### Alerts & Sessions
| Tool | Parameters | Description |
|------|------------|-------------|
| `add_price_alert(symbol, price, msg)` | price level | Alert at $100,000 |
| `mark_trading_session(session)` | ASIA/LONDON/NY | Highlight Tokyo session |

**Session Times (UTC):**
- Asia: 00:00 - 09:00
- London: 07:00 - 16:00
- New York: 13:00 - 22:00

### Trade Visualization
**Tool:** `setup_trade(symbol, side, entry, sl, tp, ...)`

| Param | Description | Required |
|-------|-------------|----------|
| side | "long" or "short" | ✅ |
| entry | Entry price | ✅ |
| sl | Stop Loss price | ✅ |
| tp | Take Profit 1 | ✅ |
| tp2, tp3 | Additional TPs | ❌ |
| trailing_sl | Trailing stop | ❌ |
| be | Break even level | ❌ |
| liq | Liquidation price | ❌ |
| gp | AI Profit Tripwire | ❌ |
| gl | AI Loss Tripwire | ❌ |

---

## Chart Navigation

### View Control
| Tool | Description |
|------|-------------|
| `focus_chart()` | Focus canvas for input |
| `reset_view()` | Reset to default |
| `focus_latest()` | Jump to latest candle |

### Pan & Zoom
| Tool | Parameters | Description |
|------|------------|-------------|
| `pan(axis, direction, amount)` | time/price, left/right/up/down | Scroll chart |
| `zoom(mode, amount)` | in/out/auto/fit/range | Zoom control |

### Screenshots & Capture
| Tool | Description |
|------|-------------|
| `get_screenshot()` | Capture image |
| `capture_moment(caption)` | Screenshot + data dump |
