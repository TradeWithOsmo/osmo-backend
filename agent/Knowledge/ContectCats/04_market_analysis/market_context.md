# Market Context Recognition

## Market Condition Classification

### Primary Conditions
| Condition | Characteristics | Visual Cues | Tools to Use |
|-----------|-----------------|-------------|--------------|
| **Trending** | Clear HH/HL or LH/LL | Diagonal movement, MA stacking | `trend_line`, `parallel_channel`, `fib_retracement` |
| **Ranging** | Horizontal oscillation | Price bouncing between levels | `rectangle`, `horizontal_line` |
| **Transitional** | Changing from one to another | Break of structure, consolidation | Wait + `horizontal_line` |
| **Volatile** | Wide candles, fast moves | ATR > 2x normal | Wider zones, `rectangle` |
| **Quiet** | Tight candles, slow moves | ATR < 0.5x normal | Expect expansion |

### Detection Questions
- "Is price making higher highs/lows or lower highs/lows?"
- "Is there a clear diagonal or horizontal structure?"
- "Has there been a recent break of structure?"
- "What is the ATR relative to average?"

---

## Trending Sub-Types

| Sub-Type | Description | Tool Preference |
|----------|-------------|-----------------|
| **Strong Trend** | Steep angle, little pullback | `ray`, `channel` |
| **Healthy Trend** | 45° angle, clean pullbacks | `trend_line`, `fib_retracement` |
| **Weak Trend** | Shallow, overlapping candles | `horizontal_line`, wait for clarity |

---

## Ranging Sub-Types

| Sub-Type | Description | Tool Preference |
|----------|-------------|-----------------|
| **Clean Range** | Clear highs/lows | `rectangle`, `horizontal_line` |
| **Choppy Range** | Messy, no clear levels | Wait, don't draw |
| **Contracting Range** | Narrowing (triangle) | `triangle_pattern` |

---

## Special Conditions

### Liquidity Sweep Detection
**Signs:**
- Quick spike through level
- Immediate reversal
- Long wick candle

**Agent Response:** "This looks like a liquidity sweep. The break was a fakeout to grab stops."

**Action:** Draw `horizontal_line` at true level, not the wick.

### Fake Breakout Identification
| Real Breakout | Fake Breakout |
|---------------|---------------|
| Closes beyond level | Only wick beyond |
| High volume | Low volume |
| Follow-through candle | Immediate reversal |
| Retest holds | Retest fails |

---

## Market Regime Memory

### Common Regime Patterns
| Regime | Typical Behavior | Drawing Implications |
|--------|------------------|----------------------|
| **Strong Trend, Shallow Pullbacks** | 20-30% retracement max | Fib 0.382-0.5 entries, not 0.618 |
| **Healthy Trend, Deep Pullbacks** | 50-61.8% retracements | Standard Fib levels valid |
| **Wide Range, High Volatility** | Large swings within bounds | Wider zones, not tight lines |
| **Tight Compression** | Narrowing, coiling | Triangle, expect expansion |
| **News-Driven Chaos** | Unpredictable spikes | Avoid drawing, wait for settle |
| **Liquidity Hunt Mode** | Fake breaks, stop runs | Don't trust first break |

---

## Session-Based Patterns

| Session | Time (UTC) | Typical Behavior |
|---------|------------|------------------|
| **Asia (Tokyo)** | 00:00 - 09:00 | Ranging, low volume, accumulation |
| **London** | 07:00 - 16:00 | Trend setting, high volume |
| **New York** | 13:00 - 22:00 | Continuation or reversal, highest volume |
| **London-NY Overlap** | 13:00 - 16:00 | Maximum volatility |

### Session Patterns
| Pattern | Implication |
|---------|-------------|
| "Asia breakouts often fail" | Wait for London confirmation |
| "London sets the trend" | Trade with London direction |
| "NY often tests London high/low" | Expect retest in NY |
| "End-of-day moves fade" | Be cautious of 4PM+ moves |

---

## Context-First Rule

Before drawing anything, determine:
1. **Market condition:** Trending / Ranging / Transitional
2. **Volatility state:** High / Normal / Low
3. **Special conditions:** Liquidity sweep? / Fake breakout?

Then select appropriate tools.

---

## Query Examples

**Q: "Market sekarang cocok pakai trendline atau horizontal?"**
> A: "Let me analyze... I see HH/HL structure on 4h, price above 20/50 EMA stack, clear diagonal movement. This is a **Trending** market, so `trend_line` is appropriate. `horizontal_line` would be better for marking key levels at swing points, but not for defining the structure."

**Q: "What market type is this?"**
> A: "Based on the current chart: Price is oscillating between $94,000 and $98,000 without breaking either level. This is a **Ranging** market. I recommend using `rectangle` to mark the range and `horizontal_line` for support/resistance."
