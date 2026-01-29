# Review & Reflection

## Post-Trade Analysis

### Trade Review Structure
```
📊 **Trade Review: BTC Long @ $95,000**

**Entry Conditions:**
- Entered at 0.618 Fib level ✅
- RSI was 45 (neutral) ✅
- Trend was up ✅

**What Happened:**
- Price hit TP1 at $97,000 (+2.1%)
- Trailed to $98,500 before reversal
- Final exit at $97,800

**Lessons:**
1. Entry was good (Fib + structure confluence)
2. TP1 partial was correct (secured profit)
3. Could have exited more at TP2 before reversal

**Grade: B+** - Good execution, minor optimization possible
```

### Grading Scale
| Grade | Meaning |
|-------|---------|
| **A** | Excellent entry, exit, and management |
| **B** | Good trade with minor room for improvement |
| **C** | Acceptable, but significant lessons to learn |
| **D** | Poor execution, major mistakes made |
| **F** | Failed trade due to rule violations |

---

## Bias Detection

### Common Trading Biases
| Bias | Detection | Agent Response |
|------|-----------|----------------|
| **Recency Bias** | Overweighting last trade | "Don't let the last loss affect your judgment." |
| **Confirmation Bias** | Only seeing bullish signals | "I notice you're focusing on bullish indicators. Let me also check bearish signals." |
| **Overconfidence** | Too many trades, too large sizes | "You've made 5 trades today. Consider taking a break." |
| **Loss Aversion** | Cutting winners, holding losers | "You tend to take profits too early. Consider using trailing stops." |
| **Anchoring** | Fixated on specific price | "The price you bought at doesn't matter. Focus on current structure." |
| **Sunk Cost** | Holding losers hoping for recovery | "This position is down 10%. The original thesis is invalidated." |

### Bias Correction Prompts
- "⚠️ You've been long on BTC for 3 trades in a row. Have you considered the possibility of reversal?"
- "ℹ️ This is similar to a setup that didn't work last week. Want me to review what was different?"
- "You tend to exit winners quickly but hold losers. Consider reversing this pattern."

---

## Pattern Recognition from History

### User Pattern Detection
Agent tracks:
- Entry accuracy (% of good entries)
- Exit timing (early, on target, late)
- Risk management compliance
- Emotional trading patterns
- Time-of-day performance

### Personalized Insights
- "I notice you often exit too early. Consider letting winners run longer."
- "Your entries are good but SLs are too tight. You got stopped out 3 times before the move."
- "You trade best during London session. Your Asia session trades have 30% lower win rate."

---

## Setup Journaling

### Capture Trade Context
**Tool:** `capture_moment(caption)`

**Stored Data:**
- Chart screenshot
- Current indicators
- Entry/Exit reasoning
- Market context
- User notes

### Journal Entry Structure
```
📝 **Setup Journal Entry**

**Date:** 2026-01-21
**Asset:** BTC/USD
**Timeframe:** 4h

**Market Context:**
- Regime: Uptrend
- Volatility: Normal
- Session: London

**Setup:**
- Entry: $95,000 (Fib 0.618 + OB)
- SL: $93,500 | TP: $100,000
- R:R: 1:3.3

**Reasoning:**
- Clean impulse move from $88k to $98k
- Healthy pullback to 0.618
- Confluent with bullish OB

**Outcome:** [To be filled after trade]
```

---

## Risk Outcome Memory

### Historical Setup Performance
| Setup Type | Win Rate | Avg R:R | Notes |
|------------|----------|---------|-------|
| **Fib 0.618 + HTF Support** | 65% | 1:2.5 | High probability |
| **First Breakout Attempt** | 40% | 1:1.5 | Often fails |
| **Range High Fade** | 60% | 1:1 | Consistent but small |
| **Trend Continuation** | 55% | 1:3 | Works when trend is real |
| **Counter-Trend Reversal** | 35% | 1:4 | Low win, high R:R |

### Expectation Setting
- "Based on historical data, this setup type wins about 60% but typically achieves only 1:1 R:R."
- "This is a reversal play. Expect low win rate but high R:R when it works."

---

## Learning Prompts

### Post-Trade Questions
1. "What did you do well in this trade?"
2. "What would you do differently?"
3. "Was your entry based on plan or emotion?"
4. "Did you follow your risk management rules?"

### Review Triggers
- After 5 trades
- After a losing streak (3+ losses)
- End of week
- After significant profit or loss

---

## Query Examples

**Q: "Review my last trade"**
> "Your last trade was a BTC long at $94,500, closed at $97,200 (+2.8%). 
> 
> **Entry Analysis:** Good - Fib 0.618 + OB confluence ✅
> **Exit Analysis:** Conservative - You exited at TP1, price later hit $99,000
> **Risk Management:** ✅ SL was in place
> 
> **Suggestions:**
> - Next time, consider closing only 50% at TP1 and trailing the rest
> - Your entry timing is consistently good - keep it up
> 
> **Grade: B+**"

**Q: "What patterns do you see in my trading?"**
> "Based on your last 20 trades, I notice:
> 
> ✅ **Strengths:**
> - Entry accuracy is 70% (above average)
> - You follow SL rules consistently
> 
> ⚠️ **Areas to Improve:**
> - You exit winners 40% too early on average
> - Your Asia session trades underperform
> - You tend to overtrade after losses
> 
> **Recommendation:** Let winners run longer with trailing stops"
