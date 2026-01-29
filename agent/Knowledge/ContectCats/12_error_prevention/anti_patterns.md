# Error Prevention & Anti-Patterns

## Core Principle
*Prevention > Correction.*

## Overfitting Prevention

### Signs of Overfitting
- Too many lines on chart (>7 drawings)
- Lines that only fit historical data but won't predict future
- Constantly adjusting lines to fit new candles
- Every candle touches some drawing

### Anti-Overfitting Rules
- Maximum 5-7 key drawings per chart
- Draw on HTF first, then LTF
- If you have to adjust a line 3+ times, it's probably wrong

### Agent Prompt
"Your chart has 12 drawings. Would you like me to clean up the less significant ones?"

## Confirmation Bias Prevention

### Signs of Confirmation Bias
- Only drawing lines that support existing view (all bullish or all bearish)
- Ignoring levels that contradict the thesis
- Asking "confirm my bias" questions

### Anti-Bias Rules
- Always draw BOTH support AND resistance
- After bullish thesis, ask: "What would invalidate this?"
- Present counter-arguments

### Agent Prompt
"You've drawn 3 support levels but no resistance. Would you like me to also mark potential resistance for balance?"

## Tool Overuse Prevention

### Signs of Overuse
- Using all available tools on one chart
- Drawing when market is unclear
- Redundant drawings (5 horizontal lines in same zone)

### Simplicity Rules
- 1 tool per purpose is enough
- If you can't see structure, don't force drawings
- Consolidate overlapping levels

### Agent Prompt
"This zone already has a rectangle. Adding a horizontal line inside is redundant."

## Retroactive Drawing Prevention

### Problem
- Drawing lines AFTER price has already moved (hindsight bias)
- "Look, price bounced off my line!" (drawn after the bounce)

### Solution
- Lines should be drawn BEFORE price reaches them
- If drawing after the fact, acknowledge it: "This is retroactive analysis for review"
- Don't claim predictive power for retroactive drawings

## Drawing Quality Checklist

Before finalizing any drawing, check:
- [ ] Is this based on significant price action?
- [ ] Would this be visible on HTF?
- [ ] Can I explain the logic behind this drawing?
- [ ] Is this actionable or just visual noise?
- [ ] Have I considered contrary evidence?

## Overdrawing Detection

**Q:** "Apakah ini overdraw?"

**A:** "Let me check for overdrawing...

Your chart currently has:
- 4 trendlines
- 6 horizontal lines
- 2 rectangles
- 3 Fib retracements

**Total: 15 drawings**

**Yes, this is overdrawing.**

**Recommendation:**
1. Remove older invalid lines
2. Keep only HTF levels
3. Consolidate overlapping levels

Would you like me to suggest which to remove?"

## Chart Cleanup Guidelines

### Keep:
- HTF levels (Daily/Weekly)
- Recent swing points
- Active confluences
- Unbroken key levels

### Remove:
- Broken levels (>3 closes beyond)
- Old drawings from different market phase
- Redundant overlapping drawings
- Noise from LTF

## Prevention Workflow

Before adding a new drawing:
1. **Count current drawings** - Am I at limit (7)?
2. **Check redundancy** - Is this already covered?
3. **Validate purpose** - What decision does this inform?
4. **Consider removal** - Should I remove something old first?
