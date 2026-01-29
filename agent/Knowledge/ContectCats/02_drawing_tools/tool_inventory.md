# Drawing Tool Inventory

## Lines (7 tools)

| Tool | Points | Description | When to Use |
|------|--------|-------------|-------------|
| `trend_line` | 2 | Finite line between points | Trending markets, connecting swing points |
| `ray` | 2 | Infinite line from A through B | S/R projection, breakout levels |
| `extended` | 2 | Infinite both directions | Extended trend analysis |
| `arrow` | 2 | Line with arrowhead | Pointing to key areas |
| `horizontal_line` | 1 (price) | Full-width horizontal | Key price levels, S/R |
| `vertical_line` | 1 (time) | Full-height vertical | Key time events |
| `parallel_channel` | 3 | Two parallel diagonal lines | Channel trading |

---

## Zones (3 tools)

| Tool | Points | Description | When to Use |
|------|--------|-------------|-------------|
| `rectangle` | 2 (corners) | Box/Zone | Range bounds, OB, FVG, S/R zones |
| `circle` | 2 (center, edge) | Circular area | Highlight specific area |
| `ellipse` | 2 | Oval area | Highlight larger zones |

---

## Patterns (3 tools)

| Tool | Points | Description | When to Use |
|------|--------|-------------|-------------|
| `triangle_pattern` | 3 | Triangle formation | Compression/consolidation |
| `head_and_shoulders` | 5 | Reversal pattern | Trend reversal identification |
| `elliott_impulse_wave` | 5 | Wave count (1-2-3-4-5) | Wave analysis |

---

## Fibonacci & Advanced (4 tools)

| Tool | Points | Description | When to Use |
|------|--------|-------------|-------------|
| `fib_retracement` | 2 | Retracement levels | Find pullback entries |
| `fib_trend_ext` | 2 | Extension levels | Find profit targets |
| `pitchfork` | 3 | Median line tool | Trend channels with median |
| `gann_box` | 2 | Time/Price grid | Time & price symmetry |

---

## Annotations (6 tools)

| Tool | Description | When to Use |
|------|-------------|-------------|
| `text` | Plain text label | Notes, labels |
| `balloon` | Callout bubble | Highlight with explanation |
| `note` | Sticky note | Extended notes |
| `icon` | Symbol marker | Quick markers |
| `arrow_up` | Up arrow | Bullish signal |
| `arrow_down` | Down arrow | Bearish signal |

---

## Position Planning (4 tools)

| Tool | Description | When to Use |
|------|-------------|-------------|
| `long_position` | Long trade R:R box | Visualize long setup |
| `short_position` | Short trade R:R box | Visualize short setup |
| `price_range` | Measure price delta | Calculate pip/point moves |
| `date_range` | Measure time duration | Calculate time spans |

---

## Core Interface

### Primary Functions
| Tool | Description |
|------|-------------|
| `draw(tool, points, style, id)` | Create any shape |
| `update_drawing(id, points, style)` | Modify existing shape |
| `clear_drawings()` | Remove all shapes |

### Style Parameters
| Parameter | Values | Description |
|-----------|--------|-------------|
| `color` | "#RRGGBB" | Line/shape color |
| `line_style` | solid, dashed, dotted | Line style |
| `line_width` | 1-5 | Line thickness |
| `fill_color` | "#RRGGBBAA" | Fill with opacity |
| `font_size` | 10-24 | Text size |

---

## Context-Based Selection

### Market Phase → Tool Selection
| Phase | Primary Tools | Avoid |
|-------|---------------|-------|
| **Trending** | `trend_line`, `parallel_channel`, `fib_retracement` | `rectangle` |
| **Ranging** | `rectangle`, `horizontal_line` | `trend_line` |
| **Consolidating** | `triangle_pattern` | Force direction |
| **Breakout** | `ray`, `fib_trend_ext` | Static lines |
| **Reversal** | `head_and_shoulders`, `fib_retracement` | Trend continuation |

### Quick Decision Tree
```
What is market doing?
├── Trending? → trend_line, channel, pitchfork
├── Ranging? → rectangle, horizontal_line
├── Compressing? → triangle_pattern
├── Pulling back? → fib_retracement
├── Reversing? → head_and_shoulders
└── ALWAYS → long_position/short_position for R:R
```
