# Drawing Failure Patterns

## Core Principle
*Correct drawings can fail for non-obvious reasons.*

## Common Drawing Failures

| Drawing | Failure Mode | Why It Fails |
|---------|--------------|--------------| | **Trendline** | Overfitted to noise | Too many touches on small TF |
| **Trendline** | Too steep | >60° angle unsustainable |
| **Channel** | Forced parallel | Price action doesn't naturally fit |
| **Fib Retracement** | Wrong impulse selected | Drew on minor swing, not major |
| **Horizontal** | Too many lines | Analysis paralysis |
| **Pitchfork** | Used too late | More useful at trend start |
| **Rectangle (OB)** | Already tested | OB loses power after 2-3 hits |

## Failure Indicators

- Trendline with 4+ touches on M5 → Likely noise, not structure
- Fib drawn on overlapping candles → Invalid impulse
- OB tested 3+ times → Weakened, expect failure

## Failure Memory: Over-Touched Trendline

```
💾 **FAILURE MEMORY**

Historical observation:
- Trendlines with many touches on 1m-15m TF often fail
- They're fitting noise, not true structure
- When these break, the reversal is often sharp

Current application:
- This trendline has 6 touches on 5m
- Likely overfitted to noise
- Recommend: Validate on higher TF (1h/4h) before trusting
```

## Failure Memory: Late Pitchfork

```
💾 **FAILURE MEMORY**

Historical observation:
- Pitchfork works best at trend start/middle
- Late pitchfork often captures exhaustion, not continuation
- Median line rejection fails when trend is overextended

Current application:
- Trend started 30 candles ago, now adding pitchfork
- This is late application
- Recommend: Use simpler tools (trendline) or expect failure
```

## Pre-Drawing Failure Check

Ask before finalizing any drawing:
- "Is this timeframe appropriate for this tool?"
- "Am I forcing this drawing to fit?"
- "Has this zone been tested too many times?"

## Example Response

**Q:** "Kenapa gambar yang 'benar' tetap gagal?"

**A:** "Great question! Let me analyze your drawing...

This trendline has 5 touches, which seems valid. BUT:

**Failure Pattern Analysis:**
1. All touches are on 5m timeframe → This is likely noise fitting ⚠️
2. The trend itself is only 2 hours old → Not enough duration for reliable trendline ⚠️
3. Angle is 65° → Too steep, unsustainable ⚠️

**Failure Pattern: Small TF Overfitting + Steep Angle**

**Recommendation:**
- Zoom out to 1h or 4h to see if the same structure holds
- If not visible on HTF, discard this trendline
- Look for more sustainable angle (~45°) on HTF"

## Failure Prevention Checklist

### Before Drawing
- [ ] Is timeframe appropriate (generally 1h+ for key lines)?
- [ ] Is structure clear without forcing?
- [ ] Is angle sustainable (~30-60°)?
- [ ] Have I verified on higher TF?

### After Drawing
- [ ] Does it respect price action naturally?
- [ ] Is it too perfect (overfitted)?
- [ ] Would it survive HTF zoom?

## Tool-Specific Failure Patterns

### Trendline Failures
- 4+ touches on <1h TF = Noise
- Angle >60° = Too steep
- Forced through irrelevant candles = Invalid

### Fibonacci Failures
- Drawn on choppy, overlapping price = Wrong impulse
- Multiple Fibs overlapping = Overthinking

### OB/FVG Failures
- Tested 3+ times = Exhausted
- Too small on HTF = Not significant

### Channel Failures
- One side never touched = Forced parallel
- Price spends >70% outside = Invalid bounds
