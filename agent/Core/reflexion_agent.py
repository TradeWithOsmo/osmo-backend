"""
Reflexion Agent
==============

A LangChain-powered trading analysis agent that follows the
Reflexion pattern:

    Explore Tools → Plan → Act → Evaluate → Reflect → Perbaiki → Act

The agent behaves like a human professional trader:
  1. SESSION INIT  – discovers all available tools from the registry
  2. PLAN          – builds a step-by-step human-like analysis workflow
  3. LOOP          – executes tools, evaluates results, self-corrects on failure
  4. SYNTHESISE    – delivers a final comparative analysis

Supports both non-streaming (chat) and streaming (Server-Sent Events) modes.
Plugs into the existing AgentBrain / OpenRouter infrastructure without replacing it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# LangChain imports (langchain 0.2.x)
# ---------------------------------------------------------------------------
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# ---------------------------------------------------------------------------
# Internal imports
# ---------------------------------------------------------------------------
# Ensure src/ is on the path (mirrors AgentBrain bootstrap)
_agent_src = Path(__file__).parent.parent / "src"
if str(_agent_src) not in sys.path:
    sys.path.insert(0, str(_agent_src))

from .reflexion_evaluator import ReflexionEvaluator
from .reflexion_memory import (
    ActionStatus,
    AnalysisPhase,
    ReflexionState,
)
from .tool_argument_adapter import adapt_tool_arguments, canonicalize_tool_name
from .tool_argument_parser import ToolArgumentParseError, parse_tool_arguments
from .tool_registry import ToolSpec, build_tool_registry, get_tool_candidate_paths

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Tools that MUST be called at session start (tool discovery phase)
DISCOVERY_TOOLS = {"list_supported_draw_tools", "list_supported_indicator_aliases"}

# Core trading-analysis workflow (in human-natural order)
ANALYSIS_WORKFLOW_TOOLS = [
    "get_price",
    "get_technical_analysis",
    "get_high_low_levels",
    "get_active_indicators",
    "set_timeframe",
    "add_indicator",
    "verify_indicator_present",
    "draw",
    "setup_trade",
]

# Default indicator set a professional trader adds first
DEFAULT_INDICATORS = ["RSI", "MACD"]

# Tools worth contextual quality review even when execution is technically OK.
CONTEXTUAL_REVIEW_TOOLS = {
    "set_timeframe",
    "add_indicator",
    "draw",
    "update_drawing",
    "setup_trade",
    "get_high_low_levels",
    "get_technical_analysis",
}

# Tool categories for the mental model
_TOOL_CATEGORIES: Dict[str, List[str]] = {
    "discovery": [
        "list_supported_draw_tools",
        "list_supported_indicator_aliases",
        "verify_indicator_present",
    ],
    "data": [
        "get_price",
        "get_orderbook",
        "get_funding_rate",
        "get_ticker_stats",
        "get_high_low_levels",
    ],
    "analysis": [
        "get_technical_analysis",
        "get_patterns",
        "get_indicators",
        "get_technical_summary",
        "research_market",
        "compare_markets",
        "scan_market_overview",
    ],
    "chart_read": ["get_active_indicators"],
    "chart_write": [
        "add_indicator",
        "remove_indicator",
        "clear_indicators",
        "set_timeframe",
        "set_symbol",
        "setup_trade",
        "add_price_alert",
        "mark_trading_session",
    ],
    "drawing": [
        "draw",
        "update_drawing",
        "clear_drawings",
    ],
    "navigation": [
        "focus_chart",
        "ensure_mode",
        "pan",
        "zoom",
        "press_key",
        "reset_view",
        "focus_latest",
        "hover_candle",
        "mouse_move",
        "inspect_cursor",
        "set_crosshair",
        "move_crosshair",
    ],
    "execution": [
        "place_order",
        "get_positions",
        "close_position",
        "close_all_positions",
        "reverse_position",
        "cancel_order",
        "adjust_position_tpsl",
        "adjust_all_positions_tpsl",
    ],
    "research": [
        "search_news",
        "search_sentiment",
        "search_web_hybrid",
        "get_whale_activity",
        "search_knowledge_base",
    ],
    "memory": ["add_memory", "search_memory", "get_recent_history"],
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
#
REFLEXION_SYSTEM_PROMPT = """\
You are Osmo, an elite trading analyst. Think and act like a seasoned human trader — direct, precise, no fluff.

Before doing anything, think like a human trader first:
  - Same market? → add indicator → get value → analyse
  - Different market? → set_symbol() → get_active_indicators() → get value → analyse
  - New analysis? → check price → read structure → find levels → configure chart → draw

# PHASE 0 — TOOL DISCOVERY (CONDITIONAL ONLY)
Skip unless user asks about tools or you hit an "unknown" error.
  1. list_supported_draw_tools()        → trend_line, fib_retracement, pitchfork, head_and_shoulders, rectangle, horizontal_line, arrow, elliott_impulse_wave …
  2. list_supported_indicator_aliases() → RSI, MACD, EMA, SMA, Bollinger Bands, SuperTrend, VWAP, Ichimoku, ATR, ADX, OBV, VPVR …
  3. don't use the one that force overlays TradingView - like

# ANALYSIS
Analyse markets like a professional trader: check price, read chart structure, identify key levels, configure indicators (max 2 non-volume; remove old before adding new; never overlay on price pane), and draw findings. For multiple markets, complete each fully before moving to the next, then end with a comparative synthesis.

# SELF-CORRECTION
good → proceed | poor → retry ×2 | error → fix → retry
  Symbol not found     → flip asset_type (crypto ↔ rwa)
  TA unsupported (RWA) → skip TA; use get_price only
  Indicator not found  → list_supported_indicator_aliases first
  draw() needs prices  → get_high_low_levels first
  Execution disabled   → setup_trade() for human review
  Timeout              → retry once

# COMMUNICATION
Think out loud, trader-style. "RSI at 74 — overbought. Checking MACD…" "Support at 94,200. Drawing now."
End multi-market with a concise synthesis.
"""

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _normalize_tool_name(name: Any) -> str:
    raw = str(name or "").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    return key


def _load_callable(dotted_path: str) -> Callable[..., Any]:
    module_name, attr_name = dotted_path.rsplit(":", 1)
    mod = __import__(module_name, fromlist=[attr_name])
    return getattr(mod, attr_name)


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


def _trim_result_for_context(result: Any, max_chars: int = 2000) -> str:
    """Compact-serialise a tool result for injection into the LLM context."""
    text = _safe_json_dumps(result)
    if len(text) <= max_chars:
        return text
    # Truncate and note it
    return text[:max_chars] + f"…[truncated, total {len(text)} chars]"


def _format_tool_signature(tool_name: str, args: Dict[str, Any]) -> str:
    name = str(tool_name or "").strip() or "unknown_tool"
    if not isinstance(args, dict) or not args:
        return f"{name}()"

    parts: List[str] = []
    for idx, (key, value) in enumerate(args.items()):
        if idx >= 6:
            parts.append("...")
            break
        raw = _safe_json_dumps(value)
        if len(raw) > 48:
            raw = raw[:45] + "..."
        parts.append(f"{key}={raw}")
    return f"{name}({', '.join(parts)})"


def _normalize_reasoning_effort(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw in {"low", "medium", "high"}:
        return raw
    return None


def _reasoning_request_fields(reasoning_effort: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"include_reasoning": True}
    effort = _normalize_reasoning_effort(reasoning_effort)
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def _normalize_text(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _extract_reasoning_texts(value: Any) -> List[str]:
    results: List[str] = []
    seen: set[str] = set()

    def _append(raw: Any) -> None:
        text = _normalize_text(raw)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        results.append(text)

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            _append(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return

        for key in (
            "reasoning",
            "reasoning_content",
            "reasoning_text",
            "reasoning_details",
            "thinking",
            "analysis",
            "summary",
        ):
            if key in node:
                _walk(node.get(key))

        node_type = str(node.get("type") or "").strip().lower()
        if node_type in {"reasoning", "reasoning_text", "thinking"}:
            for key in ("text", "content", "summary", "details", "value"):
                if key in node:
                    _walk(node.get(key))

    _walk(value)
    return results


def _extract_symbols_from_message(message: str) -> List[str]:
    """
    Heuristic: pull ticker symbols from user message.
    e.g. "Analyse BTC and ETH on 4H" → ["BTC", "ETH"]
    """
    import re

    found: List[str] = []
    # Pattern: 2-6 uppercase letters optionally followed by -USD/-USDT
    for m in re.finditer(
        r"\b([A-Z]{2,8})(?:[-/](?:USD|USDT|EUR|GBP|JPY|CHF|AUD|NZD|USDC))?\b",
        message.upper(),
    ):
        candidate = m.group(1)
        # Skip common English words that match the pattern
        skip = {
            # Articles / prepositions / conjunctions
            "A",
            "AN",
            "THE",
            "AND",
            "OR",
            "BUT",
            "NOR",
            "SO",
            "YET",
            "AT",
            "BY",
            "FOR",
            "FROM",
            "IN",
            "INTO",
            "OF",
            "OFF",
            "ON",
            "OUT",
            "OVER",
            "PER",
            "TO",
            "UP",
            "VIA",
            "WITH",
            # Pronouns / common verbs
            "I",
            "ME",
            "MY",
            "WE",
            "US",
            "OUR",
            "IT",
            "ITS",
            "DO",
            "DID",
            "IS",
            "AM",
            "ARE",
            "WAS",
            "WERE",
            "BE",
            "BEEN",
            "HAS",
            "HAD",
            "GET",
            "GOT",
            "SET",
            "LET",
            "USE",
            "RUN",
            # Action words that look like tickers
            "ANALYZE",
            "ANALYSIS",
            "COMPARE",
            "CHECK",
            "SHOW",
            "GIVE",
            "FIND",
            "LOOK",
            "SCAN",
            "PLOT",
            "DRAW",
            "ADD",
            "LIST",
            "MARKET",
            "MARKETS",
            "TRADE",
            "TRADES",
            "CHART",
            "CHARTS",
            "PRICE",
            "PRICES",
            "SIGNAL",
            "SIGNALS",
            "BOTH",
            "ALL",
            "HIGH",
            "LOW",
            "OPEN",
            "CLOSE",
            "VOLUME",
            "DATA",
            "NOW",
            "THEN",
            "WHEN",
            "WHAT",
            "HOW",
            "WHY",
            "WHICH",
            # Time / units
            "AM",
            "PM",
            "GMT",
            "UTC",
            "DAY",
            "WEEK",
            "HOUR",
            "MIN",
            # Fiat currencies (not base tokens)
            "USD",
            "EUR",
            "GBP",
            "JPY",
            "CHF",
            "CAD",
            "AUD",
            "NZD",
            "USDT",
            "USDC",
            "BUSD",
        }
        full = m.group(0).upper().replace("/", "-").replace("_", "-")
        # Always allow pair notation like EUR-USD or GBP-JPY even if base is fiat
        is_pair = "-" in full
        if candidate not in skip or is_pair:
            if full not in found:
                found.append(full)
    return found[:5]  # cap at 5


def _thought_from_reflexion_event(
    event_type: str, data: str, index: int
) -> Optional[Dict[str, Any]]:
    text = str(data or "").strip()
    if not text:
        return None

    kind = str(event_type or "").strip().lower()
    if kind == "thinking":
        return {
            "type": "thinking",
            "title": f"Thinking {index}",
            "content": text,
            "status": "done",
        }
    if kind == "tool_call":
        return {
            "type": "tool_call",
            "title": f"Tool Call {index}",
            "content": text,
            "status": "done",
        }
    if kind == "tool_result":
        upper = text.upper()
        status = "failed" if ("ERROR" in upper or "FAILED" in upper) else "done"
        return {
            "type": "tool_result",
            "title": f"Tool Result {index}",
            "content": text,
            "status": status,
        }
    if kind == "reflection":
        return {
            "type": "reasoning",
            "title": f"Reflexion {index}",
            "content": text,
            "status": "done",
        }
    return None


def _infer_timeframe_from_message(message: str) -> str:
    import re

    m = re.search(
        r"\b(1m|3m|5m|15m|30m|1[hH]|4[hH]|1[dD]|1[wW]|daily|weekly|hourly)\b",
        message,
        re.IGNORECASE,
    )
    if not m:
        return "1H"
    raw = m.group(1).upper()
    mapping = {
        "DAILY": "1D",
        "WEEKLY": "1W",
        "HOURLY": "1H",
        "4H": "4H",
        "1H": "1H",
        "1D": "1D",
        "1W": "1W",
    }
    return mapping.get(raw, raw)


# ---------------------------------------------------------------------------
# Tool execution (replicates AgentBrain._execute_tool_call)
# ---------------------------------------------------------------------------


class _ToolExecutor:
    """
    Thin wrapper around the tool registry that handles loading,
    argument adaptation, and calling tool functions.
    Mirrors AgentBrain._execute_tool_call without the full Brain overhead.
    """

    def __init__(
        self,
        registry: Dict[str, ToolSpec],
        tool_states: Dict[str, Any],
        user_context: Dict[str, Any],
    ) -> None:
        self._registry = registry
        self._tool_states = tool_states
        self._user_context = user_context
        self._callable_cache: Dict[str, Callable[..., Any]] = {}

    def _get_callable(self, tool_name: str, spec: ToolSpec) -> Callable[..., Any]:
        cached = self._callable_cache.get(tool_name)
        if cached is not None:
            return cached
        errors: List[str] = []
        for path in get_tool_candidate_paths(spec):
            try:
                fn = _load_callable(path)
                self._callable_cache[tool_name] = fn
                return fn
            except Exception as exc:
                errors.append(f"{path} → {exc}")
        raise RuntimeError(f"Cannot load tool '{tool_name}': " + " | ".join(errors))

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        canonical = canonicalize_tool_name(_normalize_tool_name(tool_name))

        spec = self._registry.get(canonical)
        if spec is None:
            return {
                "ok": False,
                "tool": canonical,
                "error": f"Unknown tool: '{canonical}'",
            }

        try:
            func = self._get_callable(canonical, spec)
        except Exception as exc:
            return {"ok": False, "tool": canonical, "error": str(exc)}

        kwargs: Dict[str, Any] = dict(arguments or {})
        user_address = str(self._user_context.get("user_address") or "").strip()

        try:
            sig = inspect.signature(func)
            param_names = set(sig.parameters.keys())
            accepts_var_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except Exception:
            sig = None  # type: ignore[assignment]
            param_names = set()
            accepts_var_kwargs = True

        # Adapt arguments (alias normalisation)
        kwargs = adapt_tool_arguments(
            tool_name=canonical,
            arguments=kwargs,
            param_names=param_names,
            tool_states=self._tool_states,
        )

        # Inject standard runtime params
        if "tool_states" in param_names and "tool_states" not in kwargs:
            kwargs["tool_states"] = dict(self._tool_states)
        if (
            "user_address" in param_names
            and not kwargs.get("user_address")
            and user_address
        ):
            kwargs["user_address"] = user_address
        if "user_id" in param_names and not kwargs.get("user_id") and user_address:
            kwargs["user_id"] = user_address

        # Symbol fallback
        sym_fallback = str(
            kwargs.get("symbol")
            or (
                self._tool_states.get("market_symbol")
                if isinstance(self._tool_states, dict)
                else ""
            )
            or ""
        ).strip()
        if "symbol" in param_names and not kwargs.get("symbol") and sym_fallback:
            kwargs["symbol"] = sym_fallback

        # Parse & coerce arguments
        try:
            if sig is not None:
                parsed, _meta = parse_tool_arguments(
                    tool_name=canonical,
                    arguments=kwargs,
                    signature=sig,
                    allow_unknown=accepts_var_kwargs,
                )
                kwargs = parsed
                if not accepts_var_kwargs and param_names:
                    kwargs = {k: v for k, v in kwargs.items() if k in param_names}
        except ToolArgumentParseError as exc:
            return {
                "ok": False,
                "tool": canonical,
                "error": f"Argument parse error: {exc}",
            }

        # Execute
        try:
            result = func(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict) and result.get("error"):
                return {
                    "ok": False,
                    "tool": canonical,
                    "error": result["error"],
                    "result": result,
                }
            return {"ok": True, "tool": canonical, "result": result}
        except Exception as exc:
            logger.exception("Tool execution error: tool=%s", canonical)
            return {"ok": False, "tool": canonical, "error": str(exc)}


# ---------------------------------------------------------------------------
# Main ReflexionAgent
# ---------------------------------------------------------------------------


class ReflexionAgent:
    """
    Trading analysis agent that implements the Reflexion loop:

        Explore → Plan → Act → Evaluate → Reflect → Perbaiki → Act

    Parameters
    ----------
    model_id : str
        OpenRouter model ID, e.g. ``"anthropic/claude-3.5-sonnet"``.
    tool_states : dict, optional
        Runtime feature flags injected by the websocket router.
    user_context : dict, optional
        User metadata (user_address, preferences …).
    temperature : float
        LLM sampling temperature.
    max_iterations : int
        Maximum outer Reflexion loop iterations (default 12).
    max_retries_per_tool : int
        Maximum retries when a single tool call fails (default 2).
    """

    def __init__(
        self,
        model_id: str,
        tool_states: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.7,
        max_iterations: int = 12,
        max_retries_per_tool: int = 2,
    ) -> None:
        self.model_id = self._clean_model_id(model_id)
        self.tool_states = dict(tool_states or {})
        self.user_context = dict(user_context or {})
        # Backward-compatible aliases used by older helper paths.
        self._tool_states = self.tool_states
        self._user_context = self.user_context
        self.temperature = float(temperature)
        inferred_effort = (
            self.tool_states.get("reasoning_effort")
            if isinstance(self.tool_states, dict)
            else None
        )
        self.reasoning_effort = _normalize_reasoning_effort(
            reasoning_effort or inferred_effort
        )
        self.max_iterations = max(1, min(int(max_iterations), 20))
        self.max_retries_per_tool = max(0, min(int(max_retries_per_tool), 3))
        self.contextual_eval_enabled = self._state_bool(
            "contextual_eval_enabled", default=True
        )
        self.contextual_eval_model_id = self._clean_model_id(
            str(self.tool_states.get("contextual_eval_model_id") or self.model_id)
        )
        self.contextual_eval_temperature = self._state_float(
            "contextual_eval_temperature",
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        )
        self.contextual_eval_min_confidence = self._state_float(
            "contextual_eval_min_confidence",
            default=0.65,
            minimum=0.0,
            maximum=1.0,
        )

        self.api_key: str = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError(
                "Missing required environment variable: OPENROUTER_API_KEY"
            )

        self._registry: Dict[str, ToolSpec] = build_tool_registry()
        self.contextual_eval_tools = self._resolve_contextual_eval_tools()
        self._executor = _ToolExecutor(
            registry=self._registry,
            tool_states=self.tool_states,
            user_context=self.user_context,
        )
        self._evaluator = ReflexionEvaluator()

        # Build the LangChain prompt template (used for message construction)
        self._prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", REFLEXION_SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="history", optional=True),
                ("human", "{user_message}"),
            ]
        )

    # ------------------------------------------------------------------
    # Model ID normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_model_id(model_id: str) -> str:
        raw = str(model_id or "").strip()
        if raw.startswith("openrouter/"):
            raw = raw.split("/", 1)[1]
        if raw.lower().endswith(":free"):
            raw = raw[:-5]
        return raw

    def _state_bool(self, key: str, default: bool = False) -> bool:
        if not isinstance(self.tool_states, dict):
            return default
        if key not in self.tool_states:
            return default
        raw = self.tool_states.get(key)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            value = raw.strip().lower()
            if value in {"1", "true", "yes", "on"}:
                return True
            if value in {"0", "false", "no", "off"}:
                return False
            return default
        return bool(raw)

    def _state_float(
        self,
        key: str,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = self.tool_states.get(key) if isinstance(self.tool_states, dict) else None
        try:
            value = float(raw) if raw is not None else float(default)
        except Exception:
            value = float(default)
        return max(float(minimum), min(float(maximum), value))

    def _resolve_contextual_eval_tools(self) -> List[str]:
        configured = (
            self.tool_states.get("contextual_eval_tools")
            if isinstance(self.tool_states, dict)
            else None
        )
        if isinstance(configured, list):
            resolved = [
                canonicalize_tool_name(_normalize_tool_name(item))
                for item in configured
            ]
            return sorted(
                [name for name in resolved if name and name in self._registry]
            )
        return sorted(
            [name for name in CONTEXTUAL_REVIEW_TOOLS if name in self._registry]
        )

    # ------------------------------------------------------------------
    # HTTP headers for OpenRouter
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": "Osmo Reflexion Agent",
        }

    # ------------------------------------------------------------------
    # Tools payload (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def _build_tools_payload(self) -> List[Dict[str, Any]]:
        """Build OpenAI-style tools list from the registry."""
        payload: List[Dict[str, Any]] = []
        allowed = self._resolve_allowed_tools()
        for name in sorted(allowed):
            spec = self._registry.get(name)
            if not isinstance(spec, dict):
                continue
            parameters = spec.get("parameters") or {
                "type": "object",
                "additionalProperties": True,
            }
            payload.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec.get("description", name),
                        "parameters": parameters,
                    },
                }
            )
        return payload

    def _resolve_allowed_tools(self) -> List[str]:
        """Filter registry by tool_states flags."""
        names = list(self._registry.keys())
        ts = self.tool_states

        write_flag = ts.get("write")
        exec_flag = ts.get("execution")
        mem_flag = ts.get("memory_enabled")
        web_flag = ts.get("web_observation_enabled")

        def _is_false(v: Any) -> bool:
            if isinstance(v, bool):
                return not v
            if isinstance(v, str):
                return v.strip().lower() in {"0", "false", "off", "no"}
            return False

        write_tools = {
            "add_indicator",
            "remove_indicator",
            "clear_indicators",
            "set_timeframe",
            "set_symbol",
            "setup_trade",
            "add_price_alert",
            "mark_trading_session",
            "draw",
            "update_drawing",
            "clear_drawings",
        }
        exec_tools = {
            "place_order",
            "get_positions",
            "adjust_position_tpsl",
            "adjust_all_positions_tpsl",
            "close_position",
            "close_all_positions",
            "reverse_position",
            "cancel_order",
        }
        mem_tools = {"add_memory", "search_memory", "get_recent_history"}
        web_tools = {"search_news", "search_sentiment", "search_web_hybrid"}

        if _is_false(write_flag):
            names = [n for n in names if n not in write_tools]
        if _is_false(exec_flag):
            names = [n for n in names if n not in exec_tools]
        if _is_false(mem_flag):
            names = [n for n in names if n not in mem_tools]
        if _is_false(web_flag):
            names = [n for n in names if n not in web_tools]

        return names

    # ------------------------------------------------------------------
    # Message builders (using LangChain primitives)
    # ------------------------------------------------------------------

    def _build_lc_system_message(self, state: ReflexionState) -> SystemMessage:
        """Build the system message, injecting live agent context."""
        ctx_block = state.build_context_block()
        content = REFLEXION_SYSTEM_PROMPT
        if ctx_block:
            content += f"\n\n<agent_context>\n{ctx_block}\n</agent_context>"

        conversation_style = " ".join(
            str(self.tool_states.get("conversation_style") or "").split()
        ).strip()
        trading_style_profile = " ".join(
            str(
                self.tool_states.get("trading_style")
                or self.tool_states.get("trading_style_profile")
                or ""
            ).split()
        ).strip()
        trading_style_prompt = " ".join(
            str(self.tool_states.get("trading_style_prompt") or "").split()
        ).strip()
        if len(trading_style_prompt) > 800:
            trading_style_prompt = trading_style_prompt[:797] + "..."

        style_lines: List[str] = []
        if conversation_style:
            style_lines.append(f"conversation_style={conversation_style}")
        if trading_style_profile and trading_style_profile.lower() not in {
            "off",
            "none",
            "default",
        }:
            style_lines.append(f"trading_style_profile={trading_style_profile}")
        if trading_style_prompt:
            style_lines.append(f"trading_style_prompt={trading_style_prompt}")

        if style_lines:
            content += (
                "\n\n<style_context>\n"
                + "\n".join(style_lines)
                + "\n</style_context>\n\n"
                + "Apply style_context for analysis tone and structure only. "
                + "Do not mention style profile names in final answer unless explicitly requested."
            )
        return SystemMessage(content=content)

    def _lc_history_to_openrouter(
        self, history: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Convert conversation history to OpenRouter message dicts."""
        messages: List[Dict[str, Any]] = []
        for item in history or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower()
            content = str(item.get("content") or "")
            if not content:
                continue
            if role not in {"system", "assistant", "user"}:
                role = "user"
            messages.append({"role": role, "content": content})
        return messages

    def _build_initial_messages(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        state: ReflexionState,
    ) -> List[Dict[str, Any]]:
        """Construct the full message list for the first LLM call."""
        msgs: List[Dict[str, Any]] = []

        # System prompt with live context
        sys_msg = self._build_lc_system_message(state)
        msgs.append({"role": "system", "content": sys_msg.content})

        # Prior conversation
        msgs.extend(self._lc_history_to_openrouter(history))

        # User turn
        msgs.append({"role": "user", "content": str(user_message or "")})
        return msgs

    # ------------------------------------------------------------------
    # OpenRouter API call
    # ------------------------------------------------------------------

    async def _call_openrouter(
        self,
        messages: List[Dict[str, Any]],
        tools_payload: List[Dict[str, Any]],
        client: httpx.AsyncClient,
    ) -> Dict[str, Any]:
        """Fire a single chat-completion request to OpenRouter."""
        body: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
        }
        body.update(_reasoning_request_fields(self.reasoning_effort))
        if tools_payload:
            body["tools"] = tools_payload
            body["tool_choice"] = "auto"

        resp = await client.post(
            OPENROUTER_CHAT_URL,
            headers=self._headers(),
            json=body,
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Tool call extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tool_calls(
        completion: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Pull tool_calls list from an OpenRouter completion response."""
        choices = completion.get("choices") or []
        if not choices:
            return []
        message = choices[0].get("message") or {}
        return message.get("tool_calls") or []

    @staticmethod
    def _extract_text_content(completion: Dict[str, Any]) -> str:
        """Extract plain text from an OpenRouter completion response."""
        choices = completion.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        return str(content)

    @staticmethod
    def _parse_tool_arguments(raw: Any) -> Dict[str, Any]:
        """Safely parse tool call arguments (string JSON or already a dict)."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    # ------------------------------------------------------------------
    # Tool discovery phase
    # ------------------------------------------------------------------

    async def _run_tool_discovery(
        self,
        state: ReflexionState,
    ) -> None:
        """
        Execute discovery tools and populate state.capabilities.
        Called once at session start before any analysis.
        """
        caps = state.capabilities

        # Run both discovery calls concurrently
        draw_task = self._executor.execute("list_supported_draw_tools", {})
        ind_task = self._executor.execute("list_supported_indicator_aliases", {})
        draw_result, ind_result = await asyncio.gather(draw_task, ind_task)

        # Ingest draw tools
        if isinstance(draw_result, dict) and draw_result.get("ok"):
            payload = draw_result.get("result") or {}
            caps.draw_tools = list(payload.get("tools") or [])
            caps.draw_aliases = list(payload.get("aliases") or [])

        # Ingest indicator aliases
        if isinstance(ind_result, dict) and ind_result.get("ok"):
            payload = ind_result.get("result") or {}
            caps.indicator_aliases = list(payload.get("aliases") or [])
            caps.indicator_canonical = list(payload.get("canonical_names") or [])
            caps.indicator_alias_map = dict(payload.get("alias_map") or {})

        # Categorise all registry tools
        caps.all_tool_names = sorted(self._registry.keys())
        caps.tool_categories = {
            cat: [t for t in tools if t in self._registry]
            for cat, tools in _TOOL_CATEGORIES.items()
        }

        caps.explored = True
        caps.explored_at = time.time()
        state.advance_phase(AnalysisPhase.PRICE_CONTEXT)

        logger.info(
            "[ReflexionAgent] Tool discovery complete: %d draw tools, %d indicators",
            len(caps.draw_tools),
            len(caps.indicator_aliases),
        )

    # ------------------------------------------------------------------
    # Context ingestion helpers
    # ------------------------------------------------------------------

    def _ingest_tool_result(
        self,
        state: ReflexionState,
        tool_name: str,
        args: Dict[str, Any],
        raw_result: Dict[str, Any],
    ) -> None:
        """
        After a successful tool call, feed the result into the ReflexionState
        so subsequent steps have accumulated context (like a trader's notebook).
        """
        symbol = (
            str(
                args.get("symbol")
                or args.get("target_symbol")
                or state.current_symbol
                or ""
            )
            .upper()
            .strip()
        )

        result = (
            raw_result.get("result") if isinstance(raw_result, dict) else raw_result
        )
        timeframe_arg = str(args.get("timeframe") or "").strip()
        if symbol and timeframe_arg:
            ctx = state.get_or_create_symbol(symbol)
            ctx.timeframe = timeframe_arg

        if tool_name == "get_price" and symbol:
            if isinstance(result, dict):
                state.ingest_price_result(symbol, result)

        elif (
            tool_name in {"get_technical_analysis", "get_patterns", "get_indicators"}
            and symbol
        ):
            if isinstance(result, dict):
                state.ingest_ta_result(symbol, result)

        elif tool_name == "get_high_low_levels" and symbol:
            if isinstance(result, dict):
                lookback = int(args.get("lookback") or 20)
                tight = lookback <= 7
                state.ingest_levels_result(symbol, result, tight=tight)

        elif tool_name == "get_active_indicators" and symbol:
            if isinstance(result, dict):
                state.ingest_indicators_result(symbol, result)
                payload_data = (
                    result.get("data", {}) if isinstance(result, dict) else {}
                )
                result_tf = str(
                    payload_data.get("timeframe")
                    or result.get("timeframe")
                    or timeframe_arg
                    or ""
                ).strip()
                if result_tf:
                    ctx = state.get_or_create_symbol(symbol)
                    ctx.timeframe = result_tf

        elif tool_name == "add_indicator" and symbol:
            ind_name = str(args.get("name") or "")
            if ind_name and isinstance(result, dict):
                state.ingest_add_indicator_result(symbol, ind_name, result)

        elif tool_name in {"draw", "update_drawing"} and symbol:
            draw_type = str(args.get("tool") or "shape")
            if isinstance(result, dict):
                state.ingest_drawing_result(symbol, draw_type, result)

        elif tool_name == "set_symbol":
            target = str(args.get("target_symbol") or "").upper().strip()
            if target:
                state.set_active_symbol(target)
                state.advance_phase(AnalysisPhase.PRICE_CONTEXT)
                logger.info("[ReflexionAgent] Switched active symbol → %s", target)

        elif tool_name == "set_timeframe" and symbol:
            tf = str(args.get("timeframe") or "").strip()
            if tf:
                ctx = state.get_or_create_symbol(symbol)
                ctx.timeframe = tf

        elif tool_name == "list_supported_draw_tools":
            if isinstance(result, dict):
                state.capabilities.draw_tools = list(result.get("tools") or [])
                state.capabilities.draw_aliases = list(result.get("aliases") or [])
                state.capabilities.explored = True

        elif tool_name == "list_supported_indicator_aliases":
            if isinstance(result, dict):
                state.capabilities.indicator_aliases = list(result.get("aliases") or [])
                state.capabilities.indicator_alias_map = dict(
                    result.get("alias_map") or {}
                )
                state.capabilities.explored = True

    # ------------------------------------------------------------------
    # Build reflexion injection message
    # ------------------------------------------------------------------

    def _build_reflexion_injection(
        self, state: ReflexionState
    ) -> Optional[Dict[str, Any]]:
        """
        Build a synthetic user message that injects recent reflections and
        accumulated context back into the conversation so the LLM can self-correct.
        Only injected when there are non-empty reflections.
        """
        reflections = state.recent_reflections(3)
        ctx_block = state.build_context_block()

        if not reflections and not ctx_block:
            return None

        lines: List[str] = ["<reflexion_update>"]
        if reflections:
            lines.append("Recent self-corrections:")
            for r in reflections:
                lines.append(f"  • {r}")
        if ctx_block:
            lines.append("Accumulated analysis context:")
            lines.append(ctx_block)
        lines.append("</reflexion_update>")
        lines.append(
            "Based on the corrections above, continue the analysis adapting your approach."
        )

        return {"role": "user", "content": "\n".join(lines)}

    @staticmethod
    def _parse_contextual_verdict(
        raw_text: str,
    ) -> Optional[Tuple[ActionStatus, str, Optional[str], Optional[float]]]:
        text = str(raw_text or "").strip()
        if not text:
            return None

        payload: Optional[Dict[str, Any]] = None
        candidates = [text]
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                payload = parsed
                break

        if not isinstance(payload, dict):
            return None

        status_raw = (
            str(
                payload.get("status")
                or payload.get("decision")
                or payload.get("verdict")
                or ""
            )
            .strip()
            .lower()
        )
        status_map = {
            "good": ActionStatus.GOOD,
            "ok": ActionStatus.GOOD,
            "pass": ActionStatus.GOOD,
            "poor": ActionStatus.POOR,
            "retry": ActionStatus.POOR,
            "weak": ActionStatus.POOR,
            "error": ActionStatus.ERROR,
            "fail": ActionStatus.ERROR,
            "failed": ActionStatus.ERROR,
        }
        status = status_map.get(status_raw)
        if status is None:
            return None

        note = str(
            payload.get("note") or payload.get("reason") or payload.get("message") or ""
        ).strip()
        fix_hint_raw = payload.get("fix_hint")
        if fix_hint_raw is None:
            fix_hint_raw = payload.get("fix")
        if fix_hint_raw is None:
            fix_hint_raw = payload.get("suggestion")
        fix_hint = str(fix_hint_raw).strip() if fix_hint_raw is not None else None
        if fix_hint == "":
            fix_hint = None

        confidence_raw = payload.get("confidence")
        confidence: Optional[float] = None
        if confidence_raw is not None:
            try:
                confidence = float(confidence_raw)
            except Exception:
                confidence = None
        return status, note, fix_hint, confidence

    async def _contextual_critique(
        self,
        *,
        state: ReflexionState,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_result: Any,
        base_note: str,
        client: httpx.AsyncClient,
    ) -> Optional[Tuple[ActionStatus, str, Optional[str]]]:
        if not self.contextual_eval_enabled:
            return None

        canonical = canonicalize_tool_name(_normalize_tool_name(tool_name))
        if canonical not in self.contextual_eval_tools:
            return None

        # Tool-assisted context check: validate indicator actually appears after add.
        if (
            canonical == "add_indicator"
            and "verify_indicator_present" in self._registry
        ):
            symbol = (
                str(tool_args.get("symbol") or state.current_symbol or "")
                .upper()
                .strip()
            )
            indicator_name = str(tool_args.get("name") or "").strip()
            if symbol and indicator_name:
                verify_args: Dict[str, Any] = {"symbol": symbol, "name": indicator_name}
                state_tf = (
                    state.active_ctx.timeframe
                    if state.active_ctx
                    and str(state.active_ctx.timeframe or "").strip()
                    else ""
                )
                tool_states_tf = ""
                if isinstance(self.tool_states, dict):
                    raw_tf = self.tool_states.get("timeframe")
                    if isinstance(raw_tf, list):
                        for item in raw_tf:
                            cand = str(item or "").strip()
                            if cand:
                                tool_states_tf = cand
                                break
                    else:
                        tool_states_tf = str(raw_tf or "").strip()
                timeframe = str(
                    tool_args.get("timeframe") or state_tf or tool_states_tf or ""
                ).strip()
                if timeframe:
                    verify_args["timeframe"] = timeframe
                verify_exec = await self._executor.execute(
                    "verify_indicator_present", verify_args
                )
                verify_actual = (
                    verify_exec.get("result")
                    if isinstance(verify_exec, dict) and verify_exec.get("ok")
                    else verify_exec
                )
                v_status, v_note, v_fix = self._evaluator.evaluate(
                    "verify_indicator_present", verify_args, verify_actual
                )
                if v_status != ActionStatus.GOOD:
                    return v_status, f"Post-check: {v_note}", v_fix

        context_block = state.build_context_block()
        if not context_block:
            return None

        review_payload = {
            "tool_name": canonical,
            "tool_args": tool_args,
            "tool_result": tool_result,
            "base_note": base_note,
            "phase": state.current_phase.value,
            "symbol": state.current_symbol,
            "context_block": context_block,
        }
        review_text = _trim_result_for_context(review_payload, max_chars=2400)

        critic_messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict trading execution critic. "
                    "Judge whether the latest tool action is context-appropriate "
                    "for the current market state. "
                    "Return JSON only with keys: "
                    "status (good|poor|error), note, fix_hint, confidence (0..1). "
                    "Use poor when the action succeeded technically but is contextually weak."
                ),
            },
            {
                "role": "user",
                "content": review_text,
            },
        ]
        body: Dict[str, Any] = {
            "model": self.contextual_eval_model_id,
            "messages": critic_messages,
            "temperature": self.contextual_eval_temperature,
        }
        try:
            resp = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=45.0,
            )
            resp.raise_for_status()
            completion = resp.json()
        except Exception as exc:
            logger.debug("Contextual critic request failed: %s", exc)
            return None

        verdict = self._parse_contextual_verdict(self._extract_text_content(completion))
        if verdict is None:
            return None

        status, note, fix_hint, confidence = verdict
        if status == ActionStatus.GOOD:
            return None

        if (
            confidence is not None
            and confidence < self.contextual_eval_min_confidence
            and status != ActionStatus.ERROR
        ):
            return None

        note_text = note or f"Contextual review flagged `{canonical}`."
        if base_note:
            note_text = f"{note_text} (base_eval: {base_note})"
        return status, note_text, fix_hint

    # ------------------------------------------------------------------
    # Main Reflexion Loop
    # ------------------------------------------------------------------

    async def _reflexion_loop(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        state: ReflexionState,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        Core Reflexion loop:
          EXPLORE → PLAN → ACT → EVALUATE → REFLECT → PERBAIKI → ACT …

        Parameters
        ----------
        stream_callback : callable(event_type, data), optional
            Called for each streamed chunk. event_type is one of:
            "thinking", "tool_call", "tool_result", "reflection", "content"
        """

        def _emit(event_type: str, data: str) -> None:
            if stream_callback:
                try:
                    stream_callback(event_type, data)
                except Exception:
                    pass

        tools_payload = self._build_tools_payload()
        messages = self._build_initial_messages(user_message, history, state)

        # Detect target symbols from user message for state pre-seeding
        symbols_in_msg = _extract_symbols_from_message(user_message)
        for sym in symbols_in_msg:
            state.set_active_symbol(sym)
        if not state.current_symbol and symbols_in_msg:
            state.current_symbol = symbols_in_msg[0].upper()

        # ---- PHASE 0: Tool Discovery ----
        if not state.capabilities.explored:
            _emit("tool_call", "calling list_supported_draw_tools()...")
            _emit("tool_call", "calling list_supported_indicator_aliases()...")
            await self._run_tool_discovery(state)
            draw_preview = ", ".join(state.capabilities.draw_tools[:8]) or "none"
            ind_preview = ", ".join(state.capabilities.indicator_aliases[:12]) or "none"
            _emit(
                "tool_result",
                (
                    "result list_supported_draw_tools(): "
                    f"{len(state.capabilities.draw_tools)} tools -> {draw_preview}"
                ),
            )
            _emit(
                "tool_result",
                (
                    "result list_supported_indicator_aliases(): "
                    f"{len(state.capabilities.indicator_aliases)} aliases -> {ind_preview}"
                ),
            )

        final_content = ""
        seen_model_reasoning: set[str] = set()

        async with httpx.AsyncClient(timeout=120.0) as client:
            for iteration in range(self.max_iterations):
                state.iteration = iteration

                # Inject reflexion context on subsequent iterations
                if iteration > 0:
                    injection = self._build_reflexion_injection(state)
                    if injection:
                        messages.append(injection)
                        _emit("reflection", injection["content"])

                # ---- Call LLM ----
                try:
                    completion = await self._call_openrouter(
                        messages, tools_payload, client
                    )
                except httpx.HTTPStatusError as exc:
                    logger.error("[ReflexionAgent] OpenRouter HTTP error: %s", exc)
                    return f"⚠️ LLM API error ({exc.response.status_code}). Please try again."
                except Exception as exc:
                    logger.error("[ReflexionAgent] OpenRouter call failed: %s", exc)
                    return f"⚠️ LLM call failed: {exc}"

                choices = completion.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                reasoning_texts = _extract_reasoning_texts(
                    [
                        completion.get("reasoning"),
                        completion.get("reasoning_details"),
                        choices[0].get("reasoning", {}) if choices else {},
                        message.get("reasoning"),
                        message.get("reasoning_content"),
                        message.get("thinking"),
                    ]
                )
                for rtext in reasoning_texts:
                    key = rtext.lower()
                    if key in seen_model_reasoning:
                        continue
                    seen_model_reasoning.add(key)
                    display = rtext if len(rtext) <= 700 else (rtext[:697] + "...")
                    _emit("thinking", display)

                tool_calls = self._extract_tool_calls(completion)
                text_content = self._extract_text_content(completion)

                if text_content:
                    _emit("content", text_content)
                    final_content = text_content

                # ---- No tool calls → done ----
                if not tool_calls:
                    logger.info(
                        "[ReflexionAgent] No tool calls on iteration %d → done.",
                        iteration,
                    )
                    break

                # ---- Add assistant message ----
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": tool_calls,
                }
                if text_content:
                    assistant_msg["content"] = text_content
                messages.append(assistant_msg)

                # ---- ACT + EVALUATE + PERBAIKI per tool call ----
                tool_results_msgs: List[Dict[str, Any]] = []

                for tc in tool_calls:
                    tc_id = tc.get("id") or f"call_{iteration}"
                    fn_block = tc.get("function") or {}
                    raw_name = str(fn_block.get("name") or "")
                    raw_args = self._parse_tool_arguments(
                        fn_block.get("arguments") or {}
                    )

                    tool_name = canonicalize_tool_name(_normalize_tool_name(raw_name))
                    _emit(
                        "tool_call",
                        f"calling {_format_tool_signature(tool_name, raw_args)}...",
                    )

                    # ----- ACT -----
                    t_start = time.monotonic()
                    exec_result = await self._executor.execute(tool_name, raw_args)
                    elapsed = (time.monotonic() - t_start) * 1000

                    actual_result = (
                        exec_result.get("result")
                        if exec_result.get("ok")
                        else exec_result
                    )

                    # ----- EVALUATE -----
                    status, note, fix_hint = self._evaluator.evaluate(
                        tool_name, raw_args, actual_result
                    )
                    _emit(
                        "tool_result",
                        f"result: {status.value.upper()} - {note} ({elapsed:.0f}ms)",
                    )

                    if status == ActionStatus.GOOD:
                        contextual = await self._contextual_critique(
                            state=state,
                            tool_name=tool_name,
                            tool_args=raw_args,
                            tool_result=actual_result,
                            base_note=note,
                            client=client,
                        )
                        if contextual is not None:
                            status, note, fix_hint = contextual
                            _emit(
                                "tool_result",
                                f"context review: {status.value.upper()} - {note}",
                            )

                    retry_count = 0

                    # ----- PERBAIKI (retry loop) -----
                    while self._evaluator.should_retry(
                        status, tool_name, retry_count, self.max_retries_per_tool
                    ):
                        reflection = (
                            f"Tool '{tool_name}' returned {status.value}: {note}. "
                            + (f"Fix: {fix_hint}" if fix_hint else "Adjusting params.")
                        )
                        state.add_reflection(reflection)
                        _emit("reflection", f"reflexion: {reflection}")

                        # Build fixed args
                        fixed_args = self._evaluator.apply_fix_to_args(
                            tool_name, raw_args, fix_hint or ""
                        )

                        _emit(
                            "tool_call",
                            f"retry #{retry_count + 1}: calling "
                            f"{_format_tool_signature(tool_name, fixed_args)}...",
                        )

                        exec_result = await self._executor.execute(
                            tool_name, fixed_args
                        )
                        raw_args = fixed_args
                        actual_result = (
                            exec_result.get("result")
                            if exec_result.get("ok")
                            else exec_result
                        )
                        status, note, fix_hint = self._evaluator.evaluate(
                            tool_name, fixed_args, actual_result
                        )
                        if status == ActionStatus.GOOD:
                            contextual_retry = await self._contextual_critique(
                                state=state,
                                tool_name=tool_name,
                                tool_args=fixed_args,
                                tool_result=actual_result,
                                base_note=note,
                                client=client,
                            )
                            if contextual_retry is not None:
                                status, note, fix_hint = contextual_retry

                        retry_count += 1

                        _emit(
                            "tool_result",
                            f"retry result: {status.value.upper()} - {note}",
                        )

                        if status == ActionStatus.GOOD:
                            break

                    # ----- Record action -----
                    action_status = (
                        status
                        if retry_count == 0
                        else (
                            ActionStatus.RETRIED
                            if status == ActionStatus.GOOD
                            else status
                        )
                    )
                    state.record_action(
                        tool_name=tool_name,
                        tool_args=raw_args,
                        result=actual_result,
                        status=action_status,
                        evaluation_note=note,
                        reflection=(
                            state.global_reflections[-1]
                            if state.global_reflections
                            else ""
                        ),
                        retry_count=retry_count,
                    )

                    # ----- Ingest into state context -----
                    self._ingest_tool_result(state, tool_name, raw_args, exec_result)

                    # ----- Build tool result message for next LLM turn -----
                    tool_result_content = _trim_result_for_context(actual_result)
                    tool_results_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": tool_result_content,
                        }
                    )

                # Add all tool results to message history
                messages.extend(tool_results_msgs)

            # End of iteration loop

        summary = state.summary()
        logger.info(
            "[ReflexionAgent] Loop done — steps=%d good=%d errors=%d reflections=%d",
            summary["total_steps"],
            summary["actions"]["good"],
            summary["actions"]["errors"],
            summary["reflections"],
        )

        return final_content

    # ------------------------------------------------------------------
    # Public API: chat (non-streaming)
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "",
    ) -> Dict[str, Any]:
        """
        Run the full Reflexion loop and return the final answer.

        Returns
        -------
        dict with keys:
          - ``response``    : final LLM text
          - ``state_summary``: ReflexionState.summary()
          - ``tool_calls``  : count of tool calls executed
        """
        state = ReflexionState(
            session_id=session_id,
            user_address=str(self.user_context.get("user_address") or ""),
            max_retries=self.max_retries_per_tool,
        )

        collected_chunks: List[str] = []
        collected_thoughts: List[Dict[str, Any]] = []
        seen_thoughts: set[Tuple[str, str]] = set()
        max_collected_thoughts = 120

        def _collect(event_type: str, data: str) -> None:
            if event_type == "content":
                collected_chunks.append(data)
                return

            if len(collected_thoughts) >= max_collected_thoughts:
                return

            item = _thought_from_reflexion_event(
                event_type=event_type,
                data=data,
                index=len(collected_thoughts) + 1,
            )
            if not item:
                return

            identity = (str(item.get("type") or ""), str(item.get("content") or ""))
            if identity in seen_thoughts:
                return
            seen_thoughts.add(identity)
            collected_thoughts.append(item)

        response = await self._reflexion_loop(
            user_message=user_message,
            history=history,
            state=state,
            stream_callback=_collect,
        )

        # Use last collected content if _reflexion_loop returned empty
        if not response and collected_chunks:
            response = collected_chunks[-1]

        return {
            "response": response,
            "state_summary": state.summary(),
            "tool_calls": state.step_counter,
            "thoughts": collected_thoughts,
        }

    # ------------------------------------------------------------------
    # Public API: stream (Server-Sent Events compatible)
    # ------------------------------------------------------------------

    async def stream(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the Reflexion loop as SSE-compatible events.

        Each yielded dict has:
          - ``type``  : "thinking" | "tool_call" | "tool_result" |
                        "reflection" | "content" | "done"
          - ``data``  : string payload
          - ``meta``  : optional dict with extra info
        """
        state = ReflexionState(
            session_id=session_id,
            user_address=str(self.user_context.get("user_address") or ""),
            max_retries=self.max_retries_per_tool,
        )

        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

        def _enqueue(event_type: str, data: str) -> None:
            queue.put_nowait({"type": event_type, "data": data})

        async def _run() -> None:
            try:
                await self._reflexion_loop(
                    user_message=user_message,
                    history=history,
                    state=state,
                    stream_callback=_enqueue,
                )
            except Exception as exc:
                queue.put_nowait(
                    {"type": "error", "data": f"Reflexion loop error: {exc}"}
                )
            finally:
                queue.put_nowait(None)  # sentinel

        task = asyncio.create_task(_run())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        await task  # propagate any exception

        # Final done event with summary
        yield {
            "type": "done",
            "data": "Analysis complete.",
            "meta": state.summary(),
        }

    # ------------------------------------------------------------------
    # Compatibility: process_query (mirrors AgentBrain.process_query)
    # ------------------------------------------------------------------

    async def process_query(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Alias for chat() — drop-in compatibility with AgentBrain callers."""
        return await self.chat(user_message, history=history)


__all__ = ["ReflexionAgent"]
