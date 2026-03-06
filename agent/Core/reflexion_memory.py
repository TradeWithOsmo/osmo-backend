"""
Reflexion Working Memory

Tracks execution state, action history, accumulated context, and reflections
for the Reflexion Agent loop (Act → Evaluate → Reflect → Perbaiki → Act).

Each session gets one ReflexionState instance that lives for the lifetime
of a single agent conversation turn.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ActionStatus(str, Enum):
    """Quality classification of a single tool call result."""

    GOOD = "good"  # Result is complete and high-quality
    POOR = "poor"  # Result returned but data is incomplete / low-quality
    ERROR = "error"  # Tool call failed with an error
    RETRIED = "retried"  # Was repaired and retried after initial failure
    SKIPPED = "skipped"  # Step was intentionally skipped by the planner


class AnalysisPhase(str, Enum):
    """Current phase in the human-like trading analysis workflow."""

    TOOL_EXPLORATION = "tool_exploration"  # Discovering available tools
    PRICE_CONTEXT = "price_context"  # Getting price / candle data
    TECHNICAL_ANALYSIS = "technical_analysis"  # Running TA + patterns
    KEY_LEVELS = "key_levels"  # Computing support / resistance
    CHART_STATE = "chart_state"  # Reading active indicators
    CHART_SETUP = "chart_setup"  # Setting timeframe + adding indicators
    DRAWING = "drawing"  # Drawing shapes on the chart
    MARKET_SWITCH = "market_switch"  # Switching to a different market
    SYNTHESIS = "synthesis"  # Final comparative analysis
    DONE = "done"  # Session complete


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


@dataclass
class ActionRecord:
    """Immutable record of a single tool call and its outcome."""

    step_idx: int
    tool_name: str
    tool_args: Dict[str, Any]
    result: Any
    status: ActionStatus
    evaluation_note: str = ""
    reflection: str = ""  # Reason for retry / correction
    retry_count: int = 0
    phase: AnalysisPhase = AnalysisPhase.PRICE_CONTEXT
    symbol: str = ""  # Market symbol this action was for
    elapsed_ms: float = 0.0  # Wall-clock time for this call

    # Convenience -----------------------------------------------------------------

    @property
    def succeeded(self) -> bool:
        return self.status in (ActionStatus.GOOD, ActionStatus.RETRIED)

    @property
    def failed(self) -> bool:
        return self.status in (ActionStatus.ERROR, ActionStatus.POOR)


@dataclass
class SymbolContext:
    """
    Accumulated data for a single market symbol gathered during analysis.
    Mirrors what a trader would have in their mental "state" for that market.
    """

    symbol: str
    asset_type: str = "crypto"

    # Price layer
    price: Optional[float] = None
    change_pct_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    candles_fetched: bool = False

    # Technical layer
    rsi: Optional[float] = None
    macd: Optional[Dict[str, Any]] = None
    patterns: List[str] = field(default_factory=list)
    ta_summary: str = ""
    ta_raw: Optional[Dict[str, Any]] = None

    # Level layer
    support: Optional[float] = None
    resistance: Optional[float] = None
    midpoint: Optional[float] = None
    support_tight: Optional[float] = None  # Short lookback
    resistance_tight: Optional[float] = None

    # Chart layer
    active_indicators: List[str] = field(default_factory=list)
    added_indicators: List[str] = field(default_factory=list)
    drawings_made: List[str] = field(default_factory=list)
    timeframe: str = ""

    # Completion flags
    price_done: bool = False
    ta_done: bool = False
    levels_done: bool = False
    indicators_verified: bool = False
    drawing_done: bool = False

    @property
    def analysis_complete(self) -> bool:
        return self.price_done and self.ta_done and self.levels_done

    def get_price_display(self) -> str:
        if self.price is None:
            return "N/A"
        if self.price >= 1000:
            return f"${self.price:,.2f}"
        if self.price >= 1:
            return f"${self.price:.4f}"
        return f"${self.price:.8f}"

    def get_level_summary(self) -> str:
        parts: List[str] = []
        if self.resistance is not None:
            parts.append(f"R={self.resistance:.4f}")
        if self.support is not None:
            parts.append(f"S={self.support:.4f}")
        return " | ".join(parts) if parts else "levels not yet computed"


@dataclass
class ToolCapabilities:
    """
    Catalogue of what the agent discovered from the tool registry.
    Built once per session during the TOOL_EXPLORATION phase.
    """

    # Drawing capabilities
    draw_tools: List[str] = field(
        default_factory=list
    )  # e.g. trend_line, fib_retracement
    draw_aliases: List[str] = field(default_factory=list)

    # Indicator capabilities
    indicator_aliases: List[str] = field(default_factory=list)
    indicator_canonical: List[str] = field(default_factory=list)
    indicator_alias_map: Dict[str, str] = field(default_factory=dict)

    # Tool registry
    all_tool_names: List[str] = field(default_factory=list)
    tool_categories: Dict[str, List[str]] = field(default_factory=dict)

    explored: bool = False
    explored_at: float = 0.0

    def get_canonical_indicator(self, alias: str) -> str:
        """Resolve alias (e.g. 'RSI') to TradingView canonical name."""
        return self.indicator_alias_map.get(alias, alias)

    def has_draw_tool(self, tool: str) -> bool:
        name = tool.lower().replace(" ", "_").replace("-", "_")
        return name in self.draw_tools or name in self.draw_aliases

    def has_indicator(self, name: str) -> bool:
        lower = name.lower()
        return any(
            lower == a.lower()
            for a in (self.indicator_aliases + self.indicator_canonical)
        )


# ---------------------------------------------------------------------------
# Core state container
# ---------------------------------------------------------------------------


@dataclass
class ReflexionState:
    """
    Full working memory for a single Reflexion Agent session.

    Lifecycle:
        1. Created fresh for each user message turn.
        2. Populated during TOOL_EXPLORATION phase.
        3. Symbols dict grows as each market is analyzed.
        4. action_history accumulates every tool call (good, poor, error).
        5. global_reflections captures self-critique that feeds back into LLM context.
    """

    # Tool capabilities (loaded lazily on error, not forced) ---------------------
    capabilities: ToolCapabilities = field(default_factory=ToolCapabilities)

    # Current workflow state -----------------------------------------------------
    current_phase: AnalysisPhase = AnalysisPhase.TOOL_EXPLORATION
    current_symbol: str = ""  # Symbol currently being analyzed
    target_symbols: List[str] = field(default_factory=list)  # All symbols to analyze
    completed_symbols: List[str] = field(default_factory=list)

    # Per-symbol accumulated knowledge -------------------------------------------
    symbols: Dict[str, SymbolContext] = field(default_factory=dict)

    # Canvas state — the conductor's eyes on what's already on the chart --------
    canvas_read: bool = False  # True after first get_active_indicators call
    canvas_indicators: List[str] = field(default_factory=list)  # names on chart
    canvas_symbol: str = ""  # symbol the canvas was last read for
    canvas_timeframe: str = ""  # timeframe of last canvas read

    # Action history (complete execution log) ------------------------------------
    action_history: List[ActionRecord] = field(default_factory=list)
    step_counter: int = 0
    iteration: int = 0  # Outer reflexion iteration count
    max_retries: int = 2  # Max retries per tool call

    # Reflections -----------------------------------------------------------------
    global_reflections: List[str] = field(default_factory=list)
    pending_fixes: List[Tuple[str, Dict[str, Any], str]] = field(
        default_factory=list
    )  # (tool_name, new_args, reason)

    # Session metadata ------------------------------------------------------------
    session_id: str = ""
    user_address: str = ""
    created_at: float = field(default_factory=time.time)

    # -------------------------------------------------------------------------
    # Symbol management
    # -------------------------------------------------------------------------

    def get_or_create_symbol(
        self, symbol: str, asset_type: str = "crypto"
    ) -> SymbolContext:
        """Return existing SymbolContext or create a new one."""
        sym = symbol.upper().strip()
        if not sym:
            return SymbolContext(symbol="UNKNOWN")
        if sym not in self.symbols:
            self.symbols[sym] = SymbolContext(symbol=sym, asset_type=asset_type)
        return self.symbols[sym]

    def get_symbol(self, symbol: str) -> Optional[SymbolContext]:
        return self.symbols.get(symbol.upper().strip())

    def set_active_symbol(
        self, symbol: str, asset_type: str = "crypto"
    ) -> SymbolContext:
        """Switch active symbol and ensure context exists."""
        sym = symbol.upper().strip()
        self.current_symbol = sym
        ctx = self.get_or_create_symbol(sym, asset_type=asset_type)
        if sym not in self.completed_symbols and sym not in self.target_symbols:
            self.target_symbols.append(sym)
        return ctx

    def mark_symbol_complete(self, symbol: str) -> None:
        sym = symbol.upper().strip()
        if sym and sym not in self.completed_symbols:
            self.completed_symbols.append(sym)

    @property
    def active_ctx(self) -> Optional[SymbolContext]:
        if not self.current_symbol:
            return None
        return self.symbols.get(self.current_symbol)

    # -------------------------------------------------------------------------
    # Context update helpers (populate SymbolContext from tool results)
    # -------------------------------------------------------------------------

    def ingest_price_result(self, symbol: str, result: Dict[str, Any]) -> None:
        ctx = self.get_or_create_symbol(symbol)
        ctx.price = result.get("price")
        ctx.change_pct_24h = result.get("change_percent_24h") or result.get(
            "change_pct_24h"
        )
        ctx.volume_24h = result.get("volume_24h")
        ctx.high_24h = result.get("high_24h")
        ctx.low_24h = result.get("low_24h")
        ctx.price_done = ctx.price is not None and ctx.price > 0

    def ingest_candles_result(self, symbol: str, result: Dict[str, Any]) -> None:
        ctx = self.get_or_create_symbol(symbol)
        data = result.get("data") or result.get("candles") or result
        if isinstance(data, list) and len(data) > 0:
            ctx.candles_fetched = True

    def ingest_ta_result(self, symbol: str, result: Dict[str, Any]) -> None:
        ctx = self.get_or_create_symbol(symbol)
        ctx.ta_raw = result
        indicators = result.get("indicators", {})
        if isinstance(indicators, dict):
            ctx.rsi = indicators.get("RSI_14") or indicators.get("RSI")
            ctx.macd = {
                k: v for k, v in indicators.items() if "MACD" in k.upper()
            } or None
        patterns = result.get("patterns", [])
        if isinstance(patterns, list):
            ctx.patterns = patterns
        ctx.ta_done = bool(indicators)

    def ingest_levels_result(
        self, symbol: str, result: Dict[str, Any], tight: bool = False
    ) -> None:
        ctx = self.get_or_create_symbol(symbol)
        if result.get("status") == "ok" or (
            result.get("support") is not None and result.get("resistance") is not None
        ):
            if tight:
                ctx.support_tight = result.get("support")
                ctx.resistance_tight = result.get("resistance")
            else:
                ctx.support = result.get("support")
                ctx.resistance = result.get("resistance")
                ctx.midpoint = result.get("midpoint")
                ctx.levels_done = True

    def ingest_indicators_result(self, symbol: str, result: Dict[str, Any]) -> None:
        ctx = self.get_or_create_symbol(symbol)
        payload_data = result.get("data", {}) if isinstance(result, dict) else {}
        active = payload_data.get("active_indicators", [])
        if isinstance(active, list):
            ctx.active_indicators = [str(i) for i in active]

    def ingest_add_indicator_result(
        self, symbol: str, indicator_name: str, result: Dict[str, Any]
    ) -> None:
        ctx = self.get_or_create_symbol(symbol)
        has_error = isinstance(result, dict) and (
            result.get("error") or result.get("status") == "error"
        )
        if not has_error:
            if indicator_name not in ctx.added_indicators:
                ctx.added_indicators.append(indicator_name)

    def ingest_drawing_result(
        self, symbol: str, draw_type: str, result: Dict[str, Any]
    ) -> None:
        ctx = self.get_or_create_symbol(symbol)
        has_error = isinstance(result, dict) and (
            result.get("error") or result.get("status") == "error"
        )
        if not has_error:
            ctx.drawings_made.append(draw_type)
            ctx.drawing_done = True

    # -------------------------------------------------------------------------
    # Action recording
    # -------------------------------------------------------------------------

    def record_action(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        status: ActionStatus,
        evaluation_note: str = "",
        reflection: str = "",
        retry_count: int = 0,
    ) -> ActionRecord:
        record = ActionRecord(
            step_idx=self.step_counter,
            tool_name=tool_name,
            tool_args=tool_args,
            result=result,
            status=status,
            evaluation_note=evaluation_note,
            reflection=reflection,
            retry_count=retry_count,
            phase=self.current_phase,
            symbol=self.current_symbol,
        )
        self.action_history.append(record)
        self.step_counter += 1
        return record

    # -------------------------------------------------------------------------
    # Reflection management
    # -------------------------------------------------------------------------

    def add_reflection(self, reflection: str) -> None:
        """Add a self-critique note if it is not already present."""
        text = str(reflection or "").strip()
        if text and text not in self.global_reflections:
            self.global_reflections.append(text)

    def add_pending_fix(
        self, tool_name: str, fixed_args: Dict[str, Any], reason: str
    ) -> None:
        """Queue a repair action to be attempted on next iteration."""
        self.pending_fixes.append((tool_name, dict(fixed_args), str(reason)))

    def pop_pending_fixes(self) -> List[Tuple[str, Dict[str, Any], str]]:
        fixes = list(self.pending_fixes)
        self.pending_fixes.clear()
        return fixes

    def recent_reflections(self, n: int = 3) -> List[str]:
        return self.global_reflections[-n:] if self.global_reflections else []

    # -------------------------------------------------------------------------
    # Query helpers
    # -------------------------------------------------------------------------

    def last_action_for_tool(self, tool_name: str) -> Optional[ActionRecord]:
        for rec in reversed(self.action_history):
            if rec.tool_name == tool_name:
                return rec
        return None

    def actions_for_symbol(self, symbol: str) -> List[ActionRecord]:
        sym = symbol.upper().strip()
        return [r for r in self.action_history if r.symbol == sym]

    def failed_tools_for_symbol(self, symbol: str) -> List[str]:
        return [r.tool_name for r in self.actions_for_symbol(symbol) if r.failed]

    def retry_count_for_tool(self, tool_name: str, symbol: str = "") -> int:
        count = 0
        for rec in self.action_history:
            if rec.tool_name == tool_name:
                if not symbol or rec.symbol == symbol.upper().strip():
                    count += rec.retry_count
        return count

    def already_succeeded(self, tool_name: str, symbol: str = "") -> bool:
        for rec in self.action_history:
            if rec.tool_name == tool_name and rec.succeeded:
                if not symbol or rec.symbol == symbol.upper().strip():
                    return True
        return False

    # -------------------------------------------------------------------------
    # Phase helpers
    # -------------------------------------------------------------------------

    def advance_phase(self, phase: AnalysisPhase) -> None:
        self.current_phase = phase

    def is_phase(self, phase: AnalysisPhase) -> bool:
        return self.current_phase == phase

    # -------------------------------------------------------------------------
    # Summary / reporting
    # -------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        good = sum(1 for r in self.action_history if r.status == ActionStatus.GOOD)
        poor = sum(1 for r in self.action_history if r.status == ActionStatus.POOR)
        error = sum(1 for r in self.action_history if r.status == ActionStatus.ERROR)
        retried = sum(
            1 for r in self.action_history if r.status == ActionStatus.RETRIED
        )

        symbols_summary: Dict[str, Dict[str, Any]] = {}
        for sym, ctx in self.symbols.items():
            symbols_summary[sym] = {
                "price": ctx.price,
                "rsi": ctx.rsi,
                "support": ctx.support,
                "resistance": ctx.resistance,
                "patterns": ctx.patterns,
                "indicators_added": ctx.added_indicators,
                "drawings_made": ctx.drawings_made,
                "analysis_complete": ctx.analysis_complete,
            }

        return {
            "iteration": self.iteration,
            "phase": self.current_phase.value,
            "total_steps": self.step_counter,
            "actions": {
                "good": good,
                "poor": poor,
                "errors": error,
                "retried": retried,
            },
            "reflections": len(self.global_reflections),
            "symbols_targeted": self.target_symbols,
            "symbols_completed": self.completed_symbols,
            "symbols": symbols_summary,
            "capabilities_explored": self.capabilities.explored,
            "canvas": {
                "read": self.canvas_read,
                "symbol": self.canvas_symbol,
                "timeframe": self.canvas_timeframe,
                "indicators": self.canvas_indicators,
            },
        }

    # -------------------------------------------------------------------------
    # Canvas state management (the conductor's eyes)
    # -------------------------------------------------------------------------

    def update_canvas(
        self, symbol: str, timeframe: str, indicators: List[str]
    ) -> None:
        """Record what the conductor sees on the chart right now."""
        self.canvas_read = True
        self.canvas_symbol = symbol.upper().strip()
        self.canvas_timeframe = timeframe.strip()
        self.canvas_indicators = list(indicators)

    def canvas_has_indicator(self, name: str) -> bool:
        """Check if an indicator is already on the canvas (case-insensitive)."""
        if not self.canvas_read:
            return False
        lower = name.lower()
        return any(lower == ind.lower() for ind in self.canvas_indicators)

    def canvas_matches_symbol(self, symbol: str) -> bool:
        """Check if the canvas is showing the requested symbol."""
        if not self.canvas_read:
            return False
        norm = symbol.upper().strip().replace("/", "-").replace("_", "-")
        canvas_norm = self.canvas_symbol.replace("/", "-").replace("_", "-")
        if norm == canvas_norm:
            return True
        # Handle BTC == BTC-USD
        for a, b in [(norm, canvas_norm), (canvas_norm, norm)]:
            if a.endswith("-USD") and a[:-4] == b:
                return True
            if a.endswith("-USDT") and a[:-5] == b:
                return True
        return False

    # -------------------------------------------------------------------------
    # Context block
    # -------------------------------------------------------------------------

    def build_context_block(self) -> str:
        """
        Build a text block summarising current state.
        Injected into the LLM prompt as <agent_context>.
        """
        lines: List[str] = []

        # Canvas state — what the conductor sees right now
        if self.canvas_read:
            canvas_line = f"[Canvas] {self.canvas_symbol} @ {self.canvas_timeframe}"
            if self.canvas_indicators:
                canvas_line += f" — active: {', '.join(self.canvas_indicators[:8])}"
            else:
                canvas_line += " — clean (no indicators)"
            lines.append(canvas_line)

        if self.capabilities.explored:
            lines.append(
                f"[Tools] {len(self.capabilities.all_tool_names)} available. "
                f"Draw: {len(self.capabilities.draw_tools)}. "
                f"Indicators: {len(self.capabilities.indicator_aliases)} aliases."
            )

        if self.current_symbol:
            lines.append(f"[Active Market] {self.current_symbol}")

        for sym, ctx in self.symbols.items():
            parts = [f"[{sym}]"]
            if ctx.price is not None:
                parts.append(f"Price={ctx.get_price_display()}")
            if ctx.rsi is not None:
                parts.append(f"RSI={ctx.rsi:.1f}")
            if ctx.patterns:
                parts.append(f"Patterns={','.join(ctx.patterns[:3])}")
            parts.append(ctx.get_level_summary())
            if ctx.active_indicators:
                parts.append(f"Indicators=[{','.join(ctx.active_indicators[:5])}]")
            if ctx.drawings_made:
                parts.append(f"Drawings=[{','.join(ctx.drawings_made[-3:])}]")
            lines.append(" ".join(parts))

        if self.global_reflections:
            lines.append("[Reflections]")
            for ref in self.global_reflections[-3:]:
                lines.append(f"  • {ref}")

        return "\n".join(lines) if lines else ""


__all__ = [
    "ActionStatus",
    "AnalysisPhase",
    "ActionRecord",
    "SymbolContext",
    "ToolCapabilities",
    "ReflexionState",
]
