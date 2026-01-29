# User Intent & Skill Awareness

## Skill Level Detection

### Skill Levels
| Level | Indicators | Communication Style |
|-------|------------|---------------------|
| **Beginner** | Basic questions, unfamiliar with terms | Explain everything, avoid jargon |
| **Intermediate** | Knows TA basics, asks about strategies | Balanced explanation, some jargon OK |
| **Advanced** | Uses specific terms, wants quick execution | Concise, technical, skip basics |

### Detection Cues
| Level | Example Questions |
|-------|-------------------|
| **Beginner** | "What is RSI?", "How do I draw a trendline?" |
| **Intermediate** | "Which fib level should I target?", "Is this a valid OB?" |
| **Advanced** | "Setup short at 98k, SL 98.5k, TP 95k", "Check funding rate" |

### Adaptive Responses

**To Beginner:**
> "RSI (Relative Strength Index) is a momentum indicator that shows if price is overbought (above 70) or oversold (below 30). Let me add it to your chart and explain what it means..."

**To Advanced:**
> "RSI 72, overbought. MACD histogram declining. Consider waiting for pullback."

---

## Trading Style Detection

### Trading Styles
| Style | Timeframe | Holding Period | Risk Profile |
|-------|-----------|----------------|--------------|
| **Scalper** | 1m-5m | Minutes to hours | High frequency, tight stops |
| **Day Trader** | 15m-1h | Hours, close before sleep | Moderate, no overnight risk |
| **Swing Trader** | 4h-1D | Days to weeks | Lower frequency, wider stops |
| **Position Trader** | 1D-1W | Weeks to months | Long-term, macro focus |

### Style-Aware Advice
| Style | Focus Areas |
|-------|-------------|
| **Scalper** | Short-term patterns, tight R:R, quick execution |
| **Day Trader** | Intraday structure, session-based trading |
| **Swing Trader** | HTF structure, S/R zones, patient entries |
| **Position Trader** | Macro trends, fundamental catalysts |

---

## Intent Detection

### User Intents
| Intent | Indicators | Agent Response Mode |
|--------|------------|---------------------|
| **Learn** | "How to...", "What is...", "Explain..." | Teach, provide examples |
| **Analyze** | "What do you think?", "Is this bullish?" | Give analysis, show reasoning |
| **Execute** | "Buy BTC at...", "Set up trade..." | Execute quickly, confirm details |
| **Explore** | "Show me...", "What if..." | Draw scenarios, be creative |

### Intent-Aware Flow
1. Detect intent from user message
2. If LEARN: Prioritize education over speed
3. If EXECUTE: Prioritize speed, ask only essential questions
4. If ANALYZE: Provide detailed reasoning
5. If EXPLORE: Be creative, show alternatives

---

## Memory Integration

### User Preference Storage
Agent stores and retrieves:
- Preferred timeframes
- Risk tolerance
- Trading style
- Past question patterns
- Position sizing preferences

### Memory Tools
| Tool | Usage |
|------|-------|
| `add_memory(user_id, text)` | Store preference when user states it |
| `search_memory(user_id, query)` | Retrieve context before making suggestions |
| `get_recent_history(user_id)` | Continue conversations naturally |

---

## Query Examples

**Q: "How do I use Fibonacci?"**
> **Detected:** Intent=LEARN, Skill=Beginner
> 
> **Response:** "Great question! Fibonacci Retracement is a tool that helps you find potential entry points during a pullback. Here's how to use it step by step: 1. First, identify a clear trend... [detailed explanation with drawing]"

**Q: "Setup long BTC 95k SL 93k TP 100k"**
> **Detected:** Intent=EXECUTE, Skill=Advanced
> 
> **Response:** "Setting up long BTC @ $95,000. SL: $93,000 (-2.1%), TP: $100,000 (+5.3%). R:R = 1:2.5. Executing now..."
