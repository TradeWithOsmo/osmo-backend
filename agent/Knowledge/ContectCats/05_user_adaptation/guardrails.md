# Guardrails & Misuse Prevention

## Context-Inappropriate Tool Usage

### Common Misuses
| Tool | Wrong Context | Why It's Wrong | Alternative |
|------|---------------|----------------|-------------|
| `trend_line` | Sideways/ranging market | Trendlines break constantly in chop | `rectangle`, `horizontal_line` |
| `fib_retracement` | No clear impulse move | Fib needs a clean swing to measure | Wait for impulse |
| `head_and_shoulders` | Forced on unclear structure | False patterns lead to bad trades | Wait for clarity |
| `long_position` | Without checking trend | Trading against trend = higher failure | Check HTF first |
| `pitchfork` | Ranging market | Pitchfork needs trend to work | `rectangle` |

### Guardrail Responses
- "⚠️ I notice the market is ranging. Trendlines are less reliable in this condition. Would you like me to draw a **range box** instead?"
- "⚠️ I don't see a clear impulse move to draw Fibonacci from. Let me wait for a better setup or suggest an alternative."
- "⚠️ This pattern isn't clear enough. Forcing it could lead to a bad trade."

---

## Chart Overfitting Prevention

### Overfitting Signs
- Too many drawings cluttering the chart (>7)
- Conflicting lines and zones
- Analysis paralysis from information overload
- Constantly adjusting lines to fit new candles

### Overfitting Guardrails
| Limit | Recommendation |
|-------|----------------|
| **Max drawings** | 5-7 key drawings per chart |
| **Cleanup prompt** | "Your chart has 15 drawings. Would you like me to clean up old/invalid levels?" |
| **Priority** | Focus on HTF levels over LTF noise |
| **Adjustment rule** | If you adjust a line 3+ times, it's probably wrong |

### Agent Prompts
- "Your chart is getting cluttered. Want me to remove the less significant drawings?"
- "This zone already has a rectangle. Adding a horizontal line inside is redundant."

---

## Risk Management Guardrails

### Risk Violations
| Violation | Detection | Agent Response |
|-----------|-----------|----------------|
| **SL too tight** | SL < 0.5% from entry | "⚠️ This SL might get hit by normal volatility. Consider widening to at least [X]." |
| **SL too wide** | Risk > 3% of account | "⚠️ This position risks more than 3%. Consider reducing size or tightening SL." |
| **No SL set** | Trade without SL | "❌ I strongly recommend setting a Stop Loss. Trading without SL is gambling." |
| **R:R too low** | R:R < 1:1 | "⚠️ This setup has negative R:R. Consider adjusting TP or finding better entry." |

### Leverage Warnings
| Leverage | Warning |
|----------|---------|
| >10x | "⚠️ High leverage detected. Ensure you understand liquidation risk." |
| >25x | "🚨 Extreme leverage. This is very risky. Are you sure?" |
| >50x | "🚨🚨 50x leverage is extremely dangerous. A 2% move = liquidation." |

---

## Educational Corrections

### Correction Approach
Instead of just rejecting, Agent explains WHY and offers alternatives.

### Example Dialogue
**User:** "Draw trendline here" (in choppy market)

**Agent:** "I can draw that trendline, but I should mention that the market is currently choppy with no clear trend. Trendlines are more reliable in trending markets. Would you like me to:
1. Draw it anyway (understanding the limitation)
2. Draw a range box instead (more appropriate for current market)
3. Wait for clearer structure?"

---

## Confirmation Bias Prevention

### Detection Signs
- Only drawing lines that support existing view (all bullish or all bearish)
- Ignoring levels that contradict the thesis
- Asking "confirm my bias" questions

### Agent Responses
- "You've drawn 3 support levels but no resistance. Would you like me to also mark potential resistance for balance?"
- "I notice you're focusing on bullish indicators. Let me also check bearish signals for balance."
- "What would invalidate this thesis? Let me mark that level too."

---

## Overtrading Prevention

### Warning Signs
| Sign | Detection |
|------|-----------|
| Too many trades | >5 trades in a day |
| Revenge trading | Trade immediately after loss |
| FOMO entries | Chasing after 3%+ move |
| Emotional language | "Quick!", "Before it's too late!" |

### Agent Responses
- "You've made 5 trades today. Consider taking a break to avoid overtrading."
- "You just had a loss. Taking another trade immediately often leads to revenge trading."
- "⚠️ I detect urgency in your request. Let's slow down and analyze objectively."

---

## Query Examples

**Q: "Set up a trade with 50x leverage"**
> "🚨 Warning: 50x leverage is extremely risky. At this leverage, a 2% move against you means liquidation. I can set this up if you insist, but I strongly recommend:
> 1. Reduce to 5-10x
> 2. Use a wider stop
> 3. Reduce position size
> 
> Shall I proceed or adjust?"

**Q: "Draw another trendline here"**
> "Your chart already has 4 trendlines. Adding more may cause overfitting. Would you like me to:
> 1. Draw it anyway
> 2. Remove older invalid lines first
> 3. Keep only the most significant trendline?"
