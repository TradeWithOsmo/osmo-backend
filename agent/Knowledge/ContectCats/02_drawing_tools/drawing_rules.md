# Drawing Rules & Best Practices

## Trendline Drawing Rules

### Definition
A line connecting two or more price points to identify trend direction.

### Rules
1. **Minimum 2 Touches:** A valid trendline needs at least 2 swing points.
2. **More Touches = Stronger:** 3+ touches significantly increase validity.
3. **Body vs Wick:** Prefer connecting candle bodies for "clean" trendlines.
4. **Angle Matters:** 45-degree angles are sustainable; very steep (>60°) often break.
5. **Breakout Confirmation:** Wait for candle CLOSE beyond the line, not just wick.
6. **Retest Entry:** After breakout, wait for price to retest the trendline before entry.

### When NOT to Use
- Ranging/Choppy markets (horizontal movement).
- When forced to skip many candles between touches.

### Angle Guidelines
| Angle | Interpretation |
|-------|----------------|
| ~45° | Sustainable, healthy trend |
| >60° | Steep, likely to break soon |
| <30° | Weak, may not hold |

---

## Fibonacci Retracement Rules

### Definition
Horizontal lines indicating potential support/resistance based on Fibonacci ratios.

### Rules
1. **Start from Impulse:** Draw from the START of a clear impulse move.
2. **Direction Matters:** Uptrend = Low to High. Downtrend = High to Low.
3. **Key Levels:**
   - `0.236` - Shallow pullback (strong trend)
   - `0.382` - Normal pullback
   - `0.5` - Psychological level
   - `0.618` - **Golden Pocket** (Best entry zone)
   - `0.786` - Deep pullback (weak trend)
4. **Confluence is Key:** Fib level + horizontal S/R = high probability zone.
5. **Invalidation:** If price closes BELOW 0.786, the impulse may be over.

### Extensions (for Targets)
| Level | Use Case |
|-------|----------|
| `1.0` | Full retracement (breakeven) |
| `1.272` | Common first target |
| `1.618` | **Primary target** (Golden Extension) |
| `2.0`, `2.618` | Extended targets for strong trends |

---

## Support/Resistance Zone Rules

### Definition
Price areas where buying (support) or selling (resistance) pressure is concentrated.

### Rules
1. **Zones, Not Lines:** S/R is an AREA, not a single price. Use `rectangle`.
2. **More Touches = Stronger:** Each touch reinforces the zone.
3. **Timeframe Hierarchy:** Higher timeframe S/R > Lower timeframe S/R.
4. **Role Reversal:** Broken Support becomes Resistance (and vice versa).
5. **Zone Width:** Width should be 0.5%-2% of price for most assets.
6. **Liquidity Pools:** Major S/R zones often have stop-losses clustered.

### Types of S/R
| Type | Description |
|------|-------------|
| **Structural** | Swing highs/lows |
| **Psychological** | Round numbers ($100, $50,000) |
| **Institutional** | Order Blocks (OB), Fair Value Gaps (FVG) |
| **Dynamic** | Moving Averages, VWAP |

---

## Order Block (OB) Rules

### Definition
The last bullish candle before a strong down move (Bearish OB) or last bearish candle before a strong up move (Bullish OB).

### Rules
1. **Identify Impulse:** Look for a strong, impulsive move (3+ candles in one direction).
2. **Find Origin Candle:** The LAST opposing candle before the impulse.
3. **Mark the Zone:** Use `rectangle` to highlight the candle body.
4. **Entry on Retest:** Wait for price to return to the OB zone.
5. **Mitigation:** Once price fills the OB zone, it's "mitigated" and may not hold again.

### Validity Factors
- OB + Break of Structure (BOS) = higher probability
- OB at Premium/Discount zone = higher probability
- OB tested 3+ times = weakened

---

## Fair Value Gap (FVG) Rules

### Definition
An imbalance zone where price moved so fast that it left a "gap" in the order flow.

### Rules
1. **3-Candle Pattern:** Candle 1 high < Candle 3 low (Bullish FVG).
2. **Mark the Gap:** Use `rectangle` to highlight the gap between Candle 1 and Candle 3.
3. **Expect Fill:** Price often returns to "fill" the gap.
4. **Entry:** Enter when price retests the FVG zone.
5. **Partial vs Full Fill:** Some FVGs only get 50% filled.

---

## Horizontal Line Best Practices

### Close vs Wick Debate
| Approach | When to Use | Rationale |
|----------|-------------|-----------|
| **Close-based** | Key levels, S/R zones | Closes are more meaningful |
| **Wick-based** | Exact rejection points, SL placement | Shows where orders filled |
| **Zone (Both)** | OB/FVG marking | Full reaction area |

### Best Practices
- Use close-based for major levels
- Use wick-based for stop placement
- Prefer zones (`rectangle`) over single lines

---

## Touch Count Validation

| Touches | Validity |
|---------|----------|
| 1 | Not valid (just a point) |
| 2 | Minimum valid (hypothesis) |
| 3+ | Confirmed (strong) |

---

## Pattern Recognition Rules

### Head & Shoulders
1. Clear Left Shoulder, Head (highest), Right Shoulder
2. Neckline connects the two troughs
3. Entry: On neckline break + retest
4. Target: Head-to-Neckline distance projected from breakout

### Triangle Patterns
| Type | Description | Bias |
|------|-------------|------|
| Symmetrical | Converging highs and lows | Neutral |
| Ascending | Flat top, rising lows | Bullish |
| Descending | Flat bottom, falling highs | Bearish |

Breakout usually occurs at 2/3 to 3/4 of triangle length.

### Elliott Wave
1. Impulse: 5 waves (1-2-3-4-5) in trend direction
2. Correction: 3 waves (A-B-C) against trend
3. Wave 3 is never the shortest
4. Wave 4 should not overlap Wave 1
5. Wave 5 often equals Wave 1 in length

---

## Risk/Reward Visualization Rules

### Always Draw R:R Before Entry
1. Use `long_position` or `short_position` for every trade idea
2. Minimum acceptable R:R = 1:2 (Risk 1 to gain 2)
3. Calculate position size based on SL distance

### Visual Checklist
- ✅ Entry clearly marked
- ✅ Stop Loss at logical invalidation
- ✅ Take Profit at logical target
