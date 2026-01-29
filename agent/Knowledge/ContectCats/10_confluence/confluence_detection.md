# Multi-Tool Confluence Logic

## Core Principle
*1 tool = hypothesis, 2+ tools = confirmation.*

## Confluence Framework

### Confluence Strength Levels

| Confluences | Strength | Action |
|-------------|----------|--------|
| 1 tool | Weak | Hypothesis only |
| 2 tools | Moderate | Consider entry |
| 3+ tools | Strong | High-probability setup |

### Confluence Types
- **Price + Fib:** Horizontal S/R at Fib level
- **Trend + Fib:** Trendline + 0.618 meet at same point
- **Multiple TF:** Same level on 4h and Daily
- **Pattern + Level:** Head & Shoulders neckline at major S/R

## High-Probability Combinations

| Combination | Confluence Type | Strength |
|-------------|-----------------|----------|
| `trend_line` + `fib_retracement` | Diagonal + level | Strong |
| `horizontal_line` + `fib_retracement` | Double level | Very Strong |
| `parallel_channel` + `fib_retracement` | Channel boundary + Fib | Strong |
| `rectangle` (OB) + `horizontal_line` | Zone + key level | Strong |
| `trend_line` + `horizontal_line` | Diagonal + horizontal | Strong |

## Confluence Presentation Format

```
📊 **Confluence Analysis**

Entry zone: $94,000 - $94,500

Confluences present:
1. ✅ Daily Support level (+15)
2. ✅ Fib 0.618 level (+15)
3. ✅ Bullish OB zone (+10)
4. ✅ Previous breakout retest (+10)

**Total Confluence Score: 50 points**
**Zone Strength: Very Strong**
```

## Confluence Detection Workflow

### After Each Drawing
1. Check: "Does this overlap with anything else?"
2. If yes, highlight the confluence zone
3. Calculate confluence score
4. Inform user proactively

### Example Behavior

"I've drawn the Fib retracement. I notice the 0.618 level coincides with the previous horizontal support at $94,000. This is a strong confluence zone."

## Scoring System

### Point Values
- Daily/Weekly level: +15 points
- 4h level: +10 points
- Fib golden ratio (0.618): +15 points
- Order Block: +10 points
- Previous breakout/retest: +10 points
- Trendline: +10 points
- Pattern completion: +15 points

### Strength Categories
- 0-20 points: Weak
- 21-40 points: Moderate
- 41-60 points: Strong
- 61+ points: Very Strong

## Example Response

**Q:** "Area ini kuat karena apa aja?"

**A:** "This zone ($94,000-$94,500) is strong because of multiple confluences:

1. Daily horizontal support - price bounced here 3 times before (+15)
2. Fib 0.618 from the recent impulse (+15)
3. Previous breakout level (role reversal) (+10)
4. Order Block from the strong bullish candle on Jan 15 (+10)

**Total: 50 points**

That's 4 confluences, making this a **very high-probability entry zone**."

## Proactive Confluence Notification

When user draws a tool, Agent should automatically:
1. Check for existing overlapping tools
2. If found, announce confluence
3. Provide scoring
4. Suggest if this strengthens or weakens the thesis
