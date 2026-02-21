"""
Reflexion Agent — Usage Examples
=================================

Demonstrates how to use the ReflexionAgent for human-like trading analysis.

Pattern:  Explore Tools → Plan → Act → Evaluate → Reflect → Perbaiki → Act

Run from the backend/ directory:
    python -m agent.examples.reflexion_usage

Or with a real key:
    OPENROUTER_API_KEY=sk-... python -m agent.examples.reflexion_usage
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_root = Path(__file__).parent.parent.parent  # backend/
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_agent_src = Path(__file__).parent.parent / "src"
if str(_agent_src) not in sys.path:
    sys.path.insert(0, str(_agent_src))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from agent.Core.reflexion_agent import ReflexionAgent
from agent.Core.reflexion_evaluator import ReflexionEvaluator
from agent.Core.reflexion_memory import (
    ActionStatus,
    AnalysisPhase,
    ReflexionState,
)

# ---------------------------------------------------------------------------
# ANSI colours for pretty console output
# ---------------------------------------------------------------------------
_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "magenta": "\033[95m",
    "blue": "\033[94m",
    "dim": "\033[2m",
}


def _c(color: str, text: str) -> str:
    return f"{_C.get(color, '')}{text}{_C['reset']}"


# ---------------------------------------------------------------------------
# Event pretty-printer for the streaming API
# ---------------------------------------------------------------------------

_ICONS: Dict[str, str] = {
    "thinking": "🧠",
    "tool_call": "🔧",
    "tool_result": "📊",
    "reflection": "♻️ ",
    "content": "💬",
    "done": "✅",
    "error": "❌",
}


def _print_event(event: Dict[str, Any]) -> None:
    event_type = str(event.get("type", ""))
    data = str(event.get("data", ""))
    meta = event.get("meta")

    icon = _ICONS.get(event_type, "  ")

    color_map = {
        "thinking": "cyan",
        "tool_call": "blue",
        "tool_result": "green",
        "reflection": "yellow",
        "content": "bold",
        "done": "green",
        "error": "red",
    }
    color = color_map.get(event_type, "reset")

    # Multi-line events get indented nicely
    lines = data.strip().splitlines()
    if not lines:
        return

    print(f"{icon} {_c(color, lines[0])}")
    for line in lines[1:]:
        print(f"   {_c('dim', line)}")

    if event_type == "done" and meta:
        _print_summary(meta)


def _print_summary(summary: Dict[str, Any]) -> None:
    print()
    print(_c("bold", "─── Session Summary ───────────────────────────────────"))
    actions = summary.get("actions", {})
    print(
        f"  Steps: {summary.get('total_steps', 0)}  "
        f"Good: {_c('green', str(actions.get('good', 0)))}  "
        f"Retried: {_c('yellow', str(actions.get('retried', 0)))}  "
        f"Errors: {_c('red', str(actions.get('errors', 0)))}  "
        f"Reflections: {summary.get('reflections', 0)}"
    )
    symbols = summary.get("symbols", {})
    for sym, ctx in symbols.items():
        price = f"${ctx['price']:,.2f}" if ctx.get("price") else "N/A"
        rsi = f"RSI={ctx['rsi']:.1f}" if ctx.get("rsi") else ""
        sup = f"S={ctx['support']:.4f}" if ctx.get("support") else ""
        res = f"R={ctx['resistance']:.4f}" if ctx.get("resistance") else ""
        pats = ",".join(ctx.get("patterns", [])[:3]) or "—"
        inds = ",".join(ctx.get("indicators_added", [])[:4]) or "—"
        drws = ",".join(ctx.get("drawings_made", [])[:4]) or "—"
        print(f"  [{_c('cyan', sym)}] {price}  {rsi}  {sup}  {res}")
        print(f"         Patterns: {pats}")
        print(f"         Indicators added: {inds}")
        print(f"         Drawings: {drws}")
    print(_c("bold", "──────────────────────────────────────────────────────"))
    print()


# ---------------------------------------------------------------------------
# Example 1 — Single Market Analysis (streaming)
# ---------------------------------------------------------------------------


async def example_single_market_streaming() -> None:
    """
    Stream a full BTC analysis on the 4H chart.

    The agent will:
      Phase 0 — discover all draw tools + indicator aliases
      Step  1 — get_price(BTC)
      Step  2 — get_candles(BTC, 4H, 120)
      Step  3 — get_technical_analysis(BTC, 4H)
      Step  4 — get_high_low_levels(BTC, 4H, lookback=20)
      Step  5 — get_active_indicators(BTC, 4H)
      Step  6 — set_timeframe(BTC, 4H)
      Step  7 — add_indicator RSI, MACD, Bollinger Bands, EMA(21)
      Step  8 — draw support / resistance horizontal lines
      Step  9 — draw trend_line based on recent pivots
      Step 10 — synthesise findings
    """
    print()
    print(_c("bold", "━━━  Example 1: Single Market — BTC 4H (streaming)  ━━━"))
    print()

    agent = ReflexionAgent(
        model_id=os.getenv("REFLEXION_MODEL", "anthropic/claude-3.5-sonnet"),
        tool_states={
            "write": True,  # allow chart writes
            "execution": False,  # no live orders
            "memory_enabled": True,
            "web_observation_enabled": True,
        },
        temperature=0.3,  # lower = more deterministic analysis
        max_iterations=15,
        max_retries_per_tool=2,
    )

    user_message = (
        "Analyze BTC on the 4H chart. "
        "Give me a full technical analysis including key support and resistance levels, "
        "RSI momentum reading, and set up the chart with indicators. "
        "Draw the key S/R levels and a trend line on the chart."
    )

    async for event in agent.stream(
        user_message=user_message,
        history=[],
        session_id="demo-btc-4h",
    ):
        _print_event(event)


# ---------------------------------------------------------------------------
# Example 2 — Multi-Market Analysis (BTC + ETH, non-streaming)
# ---------------------------------------------------------------------------


async def example_multi_market_chat() -> None:
    """
    Non-streaming multi-market analysis: BTC and ETH compared.

    The agent will:
      Phase 0 — tool discovery (draw tools + indicators)
      Market 1 (BTC) — full analysis workflow
      Market 2 (ETH) — set_symbol → full analysis workflow
      Synthesis      — comparative analysis, opportunity highlight
    """
    print()
    print(_c("bold", "━━━  Example 2: Multi-Market — BTC + ETH (chat)  ━━━"))
    print()

    agent = ReflexionAgent(
        model_id=os.getenv("REFLEXION_MODEL", "anthropic/claude-3.5-sonnet"),
        tool_states={
            "write": True,
            "execution": False,
            "memory_enabled": False,
        },
        temperature=0.4,
        max_iterations=20,
        max_retries_per_tool=2,
    )

    user_message = (
        "I want a full comparative analysis of BTC and ETH on the 1D timeframe. "
        "For each market: check price, run technical analysis, find S/R levels, "
        "add RSI and MACD indicators on the chart, and draw the support/resistance lines. "
        "Then give me a side-by-side comparison of which market has a better setup."
    )

    print(_c("cyan", "User: ") + user_message)
    print()
    print(_c("dim", "Processing... (this may take 30-90 seconds)"))
    print()

    result = await agent.chat(
        user_message=user_message,
        history=[],
        session_id="demo-multi-btc-eth",
    )

    print(_c("bold", "Agent response:"))
    print(result["response"])
    print()
    _print_summary(result["state_summary"])


# ---------------------------------------------------------------------------
# Example 3 — RWA Market (XAU-USD gold analysis)
# ---------------------------------------------------------------------------


async def example_rwa_market() -> None:
    """
    Gold (XAU-USD) analysis — RWA market on Ostium.

    The agent will auto-detect asset_type='rwa' and skip TA
    for pure fiat pairs, substituting with get_price + search_news.
    This tests the reflexion self-correction for unsupported TA.
    """
    print()
    print(_c("bold", "━━━  Example 3: RWA Market — XAU-USD Gold (streaming)  ━━━"))
    print()

    agent = ReflexionAgent(
        model_id=os.getenv("REFLEXION_MODEL", "anthropic/claude-3.5-sonnet"),
        tool_states={
            "write": True,
            "execution": False,
            "web_observation_enabled": True,  # allow news search
        },
        temperature=0.35,
        max_iterations=12,
        max_retries_per_tool=2,
    )

    user_message = (
        "Analyze XAU-USD (gold) on the daily chart. "
        "Find key price levels, add indicators, draw support/resistance, "
        "and check recent news sentiment around gold."
    )

    async for event in agent.stream(
        user_message=user_message,
        history=[],
        session_id="demo-gold-1d",
    ):
        _print_event(event)


# ---------------------------------------------------------------------------
# Example 4 — Reflexion self-correction demo (dry run)
# ---------------------------------------------------------------------------


async def example_reflexion_self_correction_demo() -> None:
    """
    Demonstrates the evaluator + memory without calling the real LLM.
    Simulates the Reflexion loop manually to show how self-correction works.
    """
    print()
    print(_c("bold", "━━━  Example 4: Reflexion Self-Correction Demo (dry run)  ━━━"))
    print()

    ev = ReflexionEvaluator()

    # --- Scenario: Symbol not found in crypto, auto-fix to rwa ---
    print(_c("cyan", "Scenario A: Symbol not found → auto flip asset_type"))
    bad_args = {"symbol": "AAPL", "asset_type": "crypto"}
    bad_result = {"error": "Symbol 'AAPL' not found in crypto markets."}

    status, note, fix = ev.evaluate("get_price", bad_args, bad_result)
    print(f"  Tool call  : get_price({bad_args})")
    print(f"  Result     : {_c('red', status.value.upper())} — {note}")
    print(f"  Fix hint   : {_c('yellow', fix or 'none')}")

    should = ev.should_retry(status, "get_price", retry_count=0)
    print(f"  Retry?     : {_c('green', str(should))}")

    fixed_args = ev.apply_fix_to_args("get_price", bad_args, fix or "")
    print(f"  Fixed args : {_c('green', str(fixed_args))}")

    good_result = {"price": 192.50, "change_percent_24h": -1.2}
    status2, note2, _ = ev.evaluate("get_price", fixed_args, good_result)
    print(f"  Retry call : get_price({fixed_args})")
    print(f"  Result     : {_c('green', status2.value.upper())} — {note2}")
    print()

    # --- Scenario: draw() missing coordinates → suggest get_high_low_levels first ---
    print(
        _c("cyan", "Scenario B: draw() needs price coords → get_high_low_levels first")
    )
    draw_args = {"symbol": "BTC", "tool": "horizontal_line", "points": []}
    draw_result = {"error": "points required — need valid price coordinates"}

    status, note, fix = ev.evaluate("draw", draw_args, draw_result)
    print(f"  Tool call  : draw({draw_args})")
    print(f"  Result     : {_c('red', status.value.upper())} — {note}")
    print(f"  Fix hint   : {_c('yellow', fix or 'none')}")
    print()

    # --- Scenario: Indicator alias wrong → consult list_supported_indicator_aliases ---
    print(_c("cyan", "Scenario C: Unknown indicator → check aliases"))
    ind_args = {"symbol": "BTC", "name": "RelativeStrengthIndex"}
    ind_result = {"error": "Indicator 'RelativeStrengthIndex' unknown or not found."}

    status, note, fix = ev.evaluate("add_indicator", ind_args, ind_result)
    print(f"  Tool call  : add_indicator({ind_args})")
    print(f"  Result     : {_c('yellow', status.value.upper())} — {note}")
    print(f"  Fix hint   : {_c('yellow', fix or 'none')}")
    print()

    # --- Scenario: State accumulation across steps ---
    print(_c("cyan", "Scenario D: State accumulation across analysis steps"))
    state = ReflexionState(max_retries=2)
    state.set_active_symbol("BTC", "crypto")

    steps: List[tuple] = [
        (
            "get_price",
            {"symbol": "BTC"},
            {"price": 95420.0, "change_percent_24h": 1.8, "volume_24h": 2.1e9},
        ),
        (
            "get_technical_analysis",
            {"symbol": "BTC", "timeframe": "4H"},
            {
                "indicators": {"RSI_14": 67.5, "MACD_12_26_9": 320.5},
                "patterns": ["Bullish Engulfing", "Higher Low"],
            },
        ),
        (
            "get_high_low_levels",
            {"symbol": "BTC", "timeframe": "4H", "lookback": 20},
            {
                "status": "ok",
                "support": 93200.0,
                "resistance": 97500.0,
                "midpoint": 95350.0,
            },
        ),
        ("add_indicator", {"symbol": "BTC", "name": "RSI"}, {"status": "ok"}),
        ("add_indicator", {"symbol": "BTC", "name": "MACD"}, {"status": "ok"}),
        (
            "draw",
            {
                "symbol": "BTC",
                "tool": "horizontal_line",
                "points": [{"time": 1700000000, "price": 93200}],
            },
            {"status": "ok"},
        ),
        (
            "draw",
            {
                "symbol": "BTC",
                "tool": "trend_line",
                "points": [
                    {"time": 1699900000, "price": 91000},
                    {"time": 1700000000, "price": 93200},
                ],
            },
            {"status": "ok"},
        ),
    ]

    for tool, args, result in steps:
        s, n, f = ev.evaluate(tool, args, result)
        state.record_action(tool, args, result, s, n)

        # Ingest into SymbolContext
        if tool == "get_price":
            state.ingest_price_result("BTC", result)
        elif tool == "get_technical_analysis":
            state.ingest_ta_result("BTC", result)
        elif tool == "get_high_low_levels":
            state.ingest_levels_result("BTC", result)
        elif tool == "add_indicator":
            state.ingest_add_indicator_result("BTC", args["name"], result)
        elif tool == "draw":
            state.ingest_drawing_result("BTC", args["tool"], result)

        status_color = "green" if s == ActionStatus.GOOD else "yellow"
        print(f"  {_c(status_color, f'[{s.value}]')} {tool} — {n[:60]}")

    ctx_block = state.build_context_block()
    print()
    print(_c("bold", "  Accumulated context (injected into LLM on next turn):"))
    for line in ctx_block.splitlines():
        print(f"    {_c('dim', line)}")

    summary = state.summary()
    print()
    print(
        f"  Total steps: {summary['total_steps']}  "
        f"Good: {_c('green', str(summary['actions']['good']))}  "
        f"Errors: {_c('red', str(summary['actions']['errors']))}"
    )
    print()


# ---------------------------------------------------------------------------
# Example 5 — Conversation with history (multi-turn)
# ---------------------------------------------------------------------------


async def example_multi_turn_conversation() -> None:
    """
    Multi-turn conversation where the agent builds on previous analysis.
    The agent uses conversation history to avoid re-fetching data it already has.
    """
    print()
    print(_c("bold", "━━━  Example 5: Multi-Turn Conversation  ━━━"))
    print()

    agent = ReflexionAgent(
        model_id=os.getenv("REFLEXION_MODEL", "anthropic/claude-3.5-sonnet"),
        tool_states={"write": True, "execution": False},
        temperature=0.3,
        max_iterations=10,
        max_retries_per_tool=2,
    )

    history: List[Dict[str, Any]] = []

    # Turn 1
    turn1 = "What's the current BTC price and RSI on the 4H chart?"
    print(_c("cyan", f"User [Turn 1]: ") + turn1)
    result1 = await agent.chat(turn1, history=history, session_id="conv-1")
    print(_c("bold", "Agent: ") + result1["response"][:300] + "…")
    history.append({"role": "user", "content": turn1})
    history.append({"role": "assistant", "content": result1["response"]})
    print()

    # Turn 2 — follow-up using context from turn 1
    turn2 = "Based on that RSI reading, should I consider a long position? What's the key invalidation level?"
    print(_c("cyan", f"User [Turn 2]: ") + turn2)
    result2 = await agent.chat(turn2, history=history, session_id="conv-2")
    print(_c("bold", "Agent: ") + result2["response"][:400] + "…")
    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

EXAMPLES = {
    "1": ("Single market BTC 4H streaming", example_single_market_streaming),
    "2": ("Multi-market BTC + ETH chat", example_multi_market_chat),
    "3": ("RWA market XAU-USD gold streaming", example_rwa_market),
    "4": ("Reflexion self-correction demo", example_reflexion_self_correction_demo),
    "5": ("Multi-turn conversation", example_multi_turn_conversation),
}


async def _main() -> None:
    # Pick example from CLI arg or default to dry-run demo
    choice = sys.argv[1] if len(sys.argv) > 1 else "4"

    if choice == "all":
        # Only run the dry-run demo by default when running all
        # (live examples need a real API key and running connectors)
        await example_reflexion_self_correction_demo()
        return

    entry = EXAMPLES.get(choice)
    if entry is None:
        print(
            f"Unknown example '{choice}'. Available: {', '.join(EXAMPLES.keys())} | all"
        )
        print()
        for k, (label, _) in EXAMPLES.items():
            print(f"  {k}  —  {label}")
        print()
        print("Note: Examples 1-3, 5 require OPENROUTER_API_KEY + running connectors.")
        print("      Example 4 is a dry-run that needs no external services.")
        return

    label, fn = entry
    print()
    print(_c("bold", f"Running: {label}"))
    print()

    if choice in ("1", "2", "3", "5"):
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            print(
                _c(
                    "red",
                    "⚠️  OPENROUTER_API_KEY is not set.\n"
                    "   Export it before running live examples:\n"
                    "   export OPENROUTER_API_KEY=sk-or-v1-...",
                )
            )
            print()
            print(_c("dim", "Falling back to dry-run demo (example 4)…"))
            print()
            await example_reflexion_self_correction_demo()
            return

    await fn()


if __name__ == "__main__":
    asyncio.run(_main())
