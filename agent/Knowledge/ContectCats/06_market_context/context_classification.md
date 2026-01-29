# Market Context Recognition

## Core Principle
*Don't draw until context is clear.*

## Primary Market Conditions

### Trending
**Characteristics:**
- Clear HH/HL (uptrend) or LH/LL (downtrend)
- Diagonal movement
- MA stacking

**Visual Cues:**
- Price making higher highs/lows or lower highs/lows
- Clear breakouts of structure
- Sustained directional movement

**Tool Preference:**
- Strong Trend: `ray`, `parallel_channel`
- Healthy Trend (45° angle): `trend_line`, `fib_retracement`
- Weak Trend: `horizontal_line`, wait for clarity

### Ranging
**Characteristics:**
- Horizontal oscillation
- Price bouncing between levels
- No clear directional bias

**Visual Cues:**
- Repeated touches of highs/lows
- Overlapping candles
- Horizontal structure

**Tool Preference:**
- Clean Range: `rectangle`, `horizontal_line`
- Choppy Range: Wait, don't draw
- Contracting Range: `triangle_pattern`

### Transitional
**Characteristics:**
- Changing from trend to range or vice versa
- Break of structure
- Consolidation after trend

**Action:** Wait for clarity, mark key levels only with `horizontal_line`

### Volatility States

**High Volatility:**
- ATR > 2x normal
- Wide candles, fast moves
- Use wider zones, `rectangle`

**Low Volatility:**
- ATR < 0.5x normal
- Tight candles, slow moves
- Wait for expansion

## Detection Questions

Before drawing anything, ask:
1. Is price making higher highs/lows or lower highs/lows?
2. Is there a clear diagonal or horizontal structure?
3. Has there been a recent break of structure?
4. What is the ATR relative to average?

## Special Conditions

### Liquidity Sweep
**Signs:**
- Quick spike through level
- Immediate reversal
- High wick, small body

**Response:**
- "This looks like a liquidity sweep. The break was a fakeout to grab stops."
- Draw `horizontal_line` at true level, not the wick

### Fake Breakout

| Real Breakout | Fake Breakout |
|---------------|---------------|
| Closes beyond level | Only wick beyond |
| High volume | Low volume |
| Follow-through candle | Immediate reversal |
| Retest holds | Retest fails |

## Context-First Rule

**BEFORE DRAWING ANYTHING:**
1. Market condition: [Trending / Ranging / Transitional]
2. Volatility state: [High / Normal / Low]
3. Special conditions: [Liquidity sweep? / Fake breakout?]
4. Current assessment: [State your analysis]
5. Recommended tools: [Based on assessment]

## Example Response

"Let me analyze the context first... I see HH/HL structure on 4h, price above 20/50 EMA stack, clear diagonal movement. This is a **Trending** market, so `trend_line` is appropriate. `horizontal_line` would be better for marking key levels at swing points, but not for defining the structure."
