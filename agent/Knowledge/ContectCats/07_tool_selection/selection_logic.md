# Tool Selection Logic

## Core Principle
*Right tool for the right condition.*

## Context-Tool Matrix

### Primary Mapping

| Market Context | Primary Tools | Avoid |
|----------------|---------------|-------|
| **Strong Trend** | `ray`, `parallel_channel` | `rectangle` |
| **Healthy Trend** | `trend_line`, `fib_retracement` | Static zones |
| **Clean Range** | `rectangle`, `horizontal_line` | `trend_line` |
| **Contracting** | `triangle_pattern` | Force trend direction |
| **Transitional** | Wait + `horizontal_line` | Committing to direction |
| **High Volatility** | Wider zones, `rectangle` | Tight lines |

### Secondary Tools by Purpose

| Purpose | Tool | When |
|---------|------|------|
| Mark level | `horizontal_line` | Key S/R |
| Project future | `ray` | After break |
| Define channel | `parallel_channel` | Clear trend |
| Find entry | `fib_retracement` | After impulse |
| Set target | `fib_trend_ext` | After retracement |
| Show bias | `arrow_up/down` | Quick visual |

## Tool Selection Decision Tree

```
Market Condition?
│
├── TRENDING?
│   ├── Need to mark the trend? → trend_line
│   ├── Need channel bounds? → parallel_channel
│   ├── Need entry on pullback? → fib_retracement
│   └── Need target projection? → fib_trend_ext
│
├── RANGING?
│   ├── Clear bounds? → rectangle
│   ├── Key levels inside? → horizontal_line
│   └── Contracting? → triangle_pattern
│
├── TRANSITIONAL?
│   ├── Wait for clarity
│   └── Mark key levels only → horizontal_line
│
└── BREAKOUT?
    ├── Mark the break level → ray
    └── Project target → fib_trend_ext
```

## Anti-Patterns (Don't Do This)

### Common Misapplications

| Tool | Wrong Context | Why Wrong |
|------|---------------|-----------|
| `pitchfork` | Ranging market | Pitchfork needs trend |
| `trend_line` | In small noise | Creates false signals |
| `fib_retracement` | No clear impulse | Meaningless levels |
| `parallel_channel` | Forced on irregular swings | Channel should be natural |
| `head_and_shoulders` | On unclear structure | Pattern must be obvious |

### Prevention Response

"⚠️ I wouldn't recommend `trend_line` here. The market is ranging, and trendlines break constantly in ranges. Try `rectangle` instead."

## Explanation Framework

When recommending a tool, always explain:
1. **What:** Which tool
2. **Why:** Based on what context
3. **Why not:** What alternatives were rejected

### Example

**Q:** "Kenapa lo nyaranin ray bukan garis penuh?"

**A:** "I recommended `ray` instead of `trend_line` because:
1. The level has been broken, so we're projecting forward, not defining current structure
2. A ray extends infinitely, which is what we want for monitoring future retest
3. A full trend_line would imply the level bounds price on both sides, which isn't the case after a break"
