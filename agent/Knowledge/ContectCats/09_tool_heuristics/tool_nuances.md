# Tool-Specific Usage Heuristics

## Core Principle
*Details matter - each tool has unwritten rules.*

## Horizontal Line Heuristics

### Close vs Wick Debate

| Approach | When to Use | Rationale |
|----------|-------------|-----------|
| **Close-based** | For key levels, S/R zones | Closes are more meaningful than wicks |
| **Wick-based** | For exact rejection points | Shows where orders were filled |
| **Zone (Both)** | For OB/FVG marking | Captures the full reaction area |

### Best Practices
- Use close-based for major levels
- Use wick-based for stop placement
- Prefer zones (`rectangle`) over single lines for S/R

### Example

**Q:** "Kenapa horizontal ini lo tarik di close, bukan wick?"

**A:** "I used the close price for this horizontal line because:
1. This is a major support level, and closes are more significant than wicks for key levels
2. The wick shows where stops were hunted, but the close shows where price truly reversed
3. For stop placement, I would use the wick, but for entry targeting, the close is more reliable"

## Trend Line Heuristics

### Touch Requirements
- Minimum 2 touches to draw
- 3+ touches for confirmation
- Touches should be swing points, not random candles

### Angle Guidelines

| Angle | Interpretation |
|-------|----------------|
| ~45° | Sustainable, healthy trend |
| >60° | Steep, likely to break |
| <30° | Weak, may not hold |

### Common Mistakes
- Forcing line through too many points
- Ignoring significant misses
- Drawing on small noise instead of swings

## Ray Heuristics

### When to Use Ray vs Line

| Scenario | Use |
|----------|-----|
| Defining current trend | `trend_line` |
| Projecting after break | `ray` |
| S/R that extends forward | `ray` |
| Channel bounds | `parallel_channel` |

### Ray Direction
- Start from origin point, extend toward future
- Don't start mid-chart

## Channel Heuristics

### Parallel Channel Rules
- Both lines should be parallel (not forced)
- Channel should contain majority of price action
- Breaks should be significant, not just wicks

### Channel Validity
- **Valid:** Price respects both boundaries
- **Invalid:** One side is never touched

## Fibonacci Heuristics

### Direction Rule
- **Uptrend retracement:** Low to High
- **Downtrend retracement:** High to Low
- **Common mistake:** Drawing backwards

### Impulse Requirement
- Fib needs a clear impulse move
- Don't draw on messy, overlapping candles

## Key Levels Best Practices

### Multiple Timeframe Levels
- HTF levels take priority
- LTF levels should align with HTF
- If conflict, trust HTF

### Level Thickness
- Major levels deserve zones (`rectangle`)
- Minor levels can be single lines
- 0.5-1% zone width for major S/R
