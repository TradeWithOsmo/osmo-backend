# Risk & Execution Alignment

## Core Principle
*Every drawing should inform a trade decision.*

## Drawing-to-Execution Links

### Entry Zone Mapping

| Drawing | Execution Link |
|---------|----------------|
| `horizontal_line` (Support) | Entry zone, SL below |
| `horizontal_line` (Resistance) | TP target, or short entry |
| `trend_line` | Entry on touch, SL below line |
| `fib_retracement` | Entry at key levels (0.618) |
| `rectangle` (OB/FVG) | Entry inside zone |
| `parallel_channel` | Entry at boundaries |

### Stop Loss Placement

| Drawing | SL Placement |
|---------|--------------|
| `horizontal_line` support | Below the line + buffer |
| `trend_line` | Below the line at entry point |
| `fib_retracement` 0.618 | Below 0.786 or structure low |
| `rectangle` (OB) | Below the OB zone |
| `parallel_channel` | Below lower channel boundary |

## Take Profit Logic

### TP Based on Drawings

| Entry Drawing | TP Drawing |
|---------------|------------|
| Fib 0.618 entry | Fib 1.618 extension |
| Support entry | Next resistance |
| Channel bottom entry | Channel top |
| Range low entry | Range high |

### Multi-TP Strategy
- **TP1:** First resistance / 1:1 R:R
- **TP2:** Next major level / 1.618 Fib
- **TP3:** Extended target / channel boundary

## GP/GL Tripwire Placement

### GP (Generate Profit) Placement

| Location | Purpose |
|----------|---------|
| Just before TP | Check if momentum supports closing |
| At major resistance | Decide pass or fail |
| At Fib level (1.0, 1.272) | Evaluate trend strength |

### GL (Generate Loss) Placement

| Location | Purpose |
|----------|---------|
| Just before SL | Check if it's fakeout or real break |
| At structure point | Evaluate if still valid |
| At OB edge | Check if zone will hold |

## Invalidation Zone Marking

Every entry drawing must have:
- Clear invalidation zone
- "If price closes below [X], the setup is invalid"
- Mark with `rectangle` or `horizontal_line`

## Risk-Reward Calculation

### Minimum Standards
- R:R ratio minimum 1:2
- If drawing-based R:R < 1:2, reconsider entry

### R:R Based on Drawing
```
Entry: $95,000 (trendline touch)
SL: $93,500 (below swing low)
Risk: $1,500

TP1: $97,000 (next resistance)
Reward: $2,000
R:R = 1:1.33

TP2: $99,000 (Fib 1.618)
Reward: $4,000
R:R = 1:2.67 ✅
```

## Example Response

**Q:** "SL gue harus di mana kalau pakai garis ini?"

**A:** "Based on your trendline entry, your SL should be placed below the trendline at the entry point.

**Specifically:**
- Entry: $95,000 (where price touches the trendline)
- SL: $93,500 (below the most recent swing low, also below the trendline)

This gives you:
1. Buffer for fake wicks
2. Exit if the trend is truly broken
3. Risk: $1,500 per position

**Suggested TP:**
- TP1: $97,000 (1:1.33 R:R at next resistance)
- TP2: $99,000 (1:2.67 R:R at Fib 1.618 extension)

Split position 50/50 for both TPs."
