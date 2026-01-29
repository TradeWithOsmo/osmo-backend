# Adaptation & Re-evaluation

## Core Principle
*Markets change, drawings should too.*

## Break & Retest Logic

### Break Scenarios

| Scenario | Status | Action |
|----------|--------|--------|
| Close beyond line | Potential break | Wait for confirmation |
| 2+ closes beyond | Confirmed break | Update/remove line |
| Break + retest holds | Role reversal confirmed | Keep line with new role |
| Break + fails retest | Failed break | Remove line, reassess |

### Role Reversal Handling
- Old support becomes new resistance (and vice versa)
- After break, wait for retest to confirm
- If retest holds, line is still valid with opposite role
- Change line color/style to indicate role change

## Fake Break Detection

### Indicators

| Indicator | Real Break | Fake Break |
|-----------|------------|------------|
| Candle close | Beyond level | Back inside |
| Volume | High volume | Low volume |
| Follow-through | Yes | Immediate reversal |
| Context | With trend | Against trend |

### Fake Break Response

"This appears to be a fake break (liquidity sweep). The line remains valid. Price may actually reverse strongly from here."

## Timeframe Conflict Resolution

### Conflict Types

| Conflict | Example | Resolution |
|----------|---------|------------|
| HTF bullish, LTF bearish | Daily up, 1h down | Wait for LTF to align |
| HTF bearish, LTF bullish | Daily down, 1h up | Avoid or trade with caution |
| Line valid on HTF, broken on LTF | - | HTF takes precedence |

### MTF Drawing Sync
- Draw on HTF first
- LTF drawings should respect HTF structure
- If LTF breaks line but HTF doesn't close below, it's likely a fake break

## Re-evaluation Triggers

### When to Re-evaluate
- Price reaches a key drawing
- New swing high/low forms
- Significant time passes without touch
- Major news event
- Timeframe change

### Re-evaluation Workflow

```
🔄 **DRAWING RE-EVALUATION**

Drawing: Trendline from $88k to $92k
Last evaluation: 3 days ago

Current status check:
1. Is line still being respected? [Yes/No]
2. Any new swing points to incorporate? [Yes/No]
3. Has there been a break attempt? [Yes/No]
4. Has context changed (trend→range)? [Yes/No]

If any "Yes" concerns → Update or remove drawing.
```

## Break Analysis Example

**Q:** "Harga tembus garis, ini invalid atau fake break?"

**A:** "Let me analyze the break...

**Analysis:**
1. Candle closed beyond the line? Yes, but only 1 close
2. Volume on break? Below average
3. Follow-through? No, next candle reversed
4. Context? This was against the HTF trend

**Verdict: This is likely a FAKE BREAK (liquidity sweep).**

The line remains valid.

**Recommendations:**
1. Wait for a retest of the line from below
2. If retest holds, it confirms the fake break and entry opportunity
3. SL below the wick low ($XX,XXX)"

## Drawing Lifecycle Management

### Lifecycle States
1. **New** (0-2 touches) - Hypothesis
2. **Active** (3-5 touches) - Confirmed
3. **Aging** (No touch in 7+ days) - Monitor for relevance
4. **Broken** (Multiple closes beyond) - Archive/Remove
5. **Role Reversed** (Broken + retest holds) - Update role

### Maintenance Schedule
- **Daily:** Check for breaks on active drawings
- **Weekly:** Remove broken/obsolete drawings
- **Monthly:** Review all drawings for relevance

## Update vs Remove Decision

### Update If:
- New swing point strengthens the line
- Minor adjustment (<5%) makes line stronger
- Role reversal confirmed

### Remove If:
- Multiple clean breaks (3+)
- No longer respected (0 touches in 14 days)
- Market phase changed (trend→range)
- Better drawing available

## Agent Proactive Maintenance

Agent should automatically:
1. Check drawing validity when price approaches
2. Notify when drawing becomes aged
3. Suggest removal of broken drawings
4. Update roles after confirmed reversals
