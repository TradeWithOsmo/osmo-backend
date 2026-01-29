# Trade Management Rules

## Entry Line Rules

### Definition
The price at which you enter the trade.

### Placement Logic
1. **Limit Entry (Preferred):** Place at key S/R zones, OB, FVG for better R:R.
2. **Market Entry:** Only when momentum is strong and you MUST enter NOW.
3. **Confirmation Entry:** Wait for a signal (candle pattern, indicator cross) at your level.

### Common Mistakes
- Chasing price (entering after the move started)
- Entering without a plan (no TP/SL already defined)

---

## Stop Loss (SL) Rules

### Definition
The price at which you EXIT with a loss to protect capital.

### Placement Logic
| Position | SL Placement |
|----------|--------------|
| **LONG** | Below the last swing low or Order Block |
| **SHORT** | Above the last swing high or Order Block |

### ATR-Based Stop
SL = Entry - (ATR × 1.5 to 2.0) for volatility-adjusted stops.

### Critical Rules
- **Never Too Tight:** Avoid SL that gets hit by normal market noise.
- **Never Too Wide:** SL should not risk more than 1-2% of account per trade.

### Golden Rule
> "Place SL where your trade idea is INVALIDATED, not where you're comfortable losing."

---

## Take Profit (TP) Rules

### Definition
The price at which you EXIT with profit.

### Multi-Target Strategy
| Target | Location | Action |
|--------|----------|--------|
| **TP1** (Conservative) | 1:1 R:R or first resistance | Close 25-50% |
| **TP2** (Primary) | Fib 1.618 or major S/R | Close 25-50% |
| **TP3** (Aggressive) | 2.0/2.618 or next HTF level | Close remaining |

### Placement Logic
1. **Fib Extensions:** 1.272, 1.618, 2.0 are common targets
2. **S/R Levels:** Previous swing highs/lows
3. **Psychological Levels:** Round numbers ($100, $50,000)

### Common Mistakes
- TP too close (cutting winners early)
- TP too far (never reached, trade reverses)
- No TP at all (greed leads to giving back profits)

---

## Trailing Stop Rules

### Definition
A dynamic SL that moves WITH price to lock in profits.

### When to Activate
1. **After TP1 Hit:** Once you've secured partial profit, trail the remaining
2. **Strong Momentum:** When trend is clearly in your favor
3. **New Structure Formed:** Move SL to the new swing point

### Trailing Methods
| Method | Description |
|--------|-------------|
| **Fixed Pips** | Trail by X pips/points behind price |
| **ATR-Based** | Trail by 1-2 ATR behind current price |
| **Structure-Based** | Move SL to each new swing point |
| **Moving Average** | Trail below/above key MA (e.g., 20 EMA) |

### Important
Never trail so tight that normal pullbacks stop you out.

---

## Break Even (BE) Rules

### Definition
Moving SL to Entry price to eliminate risk.

### When to Move to BE
1. **After TP1 Hit:** Standard practice after first target is reached
2. **Price Shows Strength:** Clear continuation signal after entry
3. **2:1 R Reached:** Even if TP1 not hit, move to BE after 2R in profit

### Caution
- Don't move to BE too early (you'll get stopped out on normal retest)
- Move to BE + a few pips to cover fees/spread

---

## Liquidation Price Rules

### Definition
The price at which your position is FORCIBLY CLOSED by the exchange (leverage trading).

### When to Display
1. **Always for Leveraged Trades:** Display Liq price as a warning line
2. **High Leverage (>10x):** CRITICAL to monitor

### Rule
> "If SL is close to Liq price, reduce leverage or position size."

---

## GP (Generate Profit Decision) - AI Tripwire

### Definition
A level where the Agent pauses to RE-ANALYZE before taking profit.

### Visual
Green Dashed Line labeled "AI-GP"

### Placement Logic
1. **Before TP:** Place GP slightly before TP to check if momentum supports closing
2. **At Key Resistance:** Place at S/R to decide "break or bounce?"
3. **At Fib Level:** Place at 1.618 to evaluate "extend targets or close?"

### Agent Logic at GP
| Scenario | Agent Response |
|----------|----------------|
| RSI overbought (>70) | "Closing 50% at TP1" |
| Trend still strong | "Moving TP to 2.0 extension" |
| Volume declining | "Taking partial profit" |

**Goal:** Prevent premature profit-taking OR letting profits reverse.

---

## GL (Generate Loss Decision) - AI Tripwire

### Definition
A level where the Agent pauses to RE-ANALYZE before cutting loss.

### Visual
Red Dashed Line labeled "AI-GL"

### Placement Logic
1. **Before SL:** Place GL slightly before SL to check for fakeouts
2. **At Key Support:** Place at structure to decide "valid break or liquidity hunt?"
3. **At Previous Low/High:** Place at swing point for re-evaluation

### Agent Logic at GL
| Scenario | Agent Response |
|----------|----------------|
| Low volume break | "This might be a fakeout. Holding position" |
| BOS confirmed | "Break of Structure confirmed. Cutting loss" |
| Quick reversal | "Liquidity grab detected. Price likely resumes" |

**Goal:** Prevent premature stop-outs from fakeouts OR holding losers too long.

---

## Full Trade Setup Flow

### Order of Placement
1. **Entry** - Where you get in
2. **SL** - Where your idea is wrong
3. **TP1/TP2/TP3** - Where you take profits
4. **GL** - AI checkpoint before SL
5. **GP** - AI checkpoint before TP
6. **Liq** - Exchange's kill zone (if leveraged)
7. **BE** - Activated after TP1 hit
8. **Trailing** - Activated in strong trends

### Visual Example (Long Trade)
```
------- TP3 (Extended Target) -------
------- TP2 (Primary Target) -------
------- GP (AI Profit Check) ------- (Dashed Green)
------- TP1 (Conservative) -------
======= ENTRY =======
------- GL (AI Loss Check) ------- (Dashed Red)
------- SL (Stop Loss) -------
------- Liq (Liquidation) ------- (If leveraged)
```

---

## Query Examples

**Q: "When should I use Trailing Stop?"**
> A: "Activate trailing after TP1 is hit or when clear momentum is in your favor. Use structure-based trailing for best results."

**Q: "Where should I put my SL?"**
> A: "Place SL below the last swing low for longs, above last swing high for shorts. The SL should be at the point where your trade thesis is INVALIDATED, not just where you're comfortable losing."

**Q: "What is GP/GL?"**
> A: "GP (Generate Profit) and GL (Generate Loss) are AI decision points. I pause at these levels to re-analyze before closing. At GP, I check if profit-taking makes sense. At GL, I check if the loss is a real break or just a fakeout."
