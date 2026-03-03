from __future__ import annotations

import importlib
import inspect
from copy import deepcopy
from functools import lru_cache
from typing import Any, Dict, List


ToolSpec = Dict[str, Any]


def _derive_legacy_fallback(path: str) -> str | None:
    dotted = str(path or "").strip()
    if ":" not in dotted:
        return None

    module_name, attr_name = dotted.split(":", 1)
    if module_name.startswith("agent.Tools."):
        legacy_module = module_name.replace("agent.Tools.", "agent.src.tools.legacy.", 1)
        return f"{legacy_module}:{attr_name}"
    if module_name.startswith("Tools."):
        legacy_module = module_name.replace("Tools.", "src.tools.legacy.", 1)
        return f"{legacy_module}:{attr_name}"
    return None


def get_tool_candidate_paths(spec: ToolSpec) -> List[str]:
    paths: List[str] = []
    explicit_paths = spec.get("paths")
    if isinstance(explicit_paths, list):
        for item in explicit_paths:
            text = str(item or "").strip()
            if text and text not in paths:
                paths.append(text)
    else:
        primary = str(spec.get("path") or "").strip()
        if primary:
            paths.append(primary)
            fallback = _derive_legacy_fallback(primary)
            if fallback and fallback not in paths:
                paths.append(fallback)
    return paths


def _auto_description(tool_name: str) -> str:
    label = str(tool_name or "").replace("_", " ").strip()
    if not label:
        return "Tool function."
    return f"Execute {label}."


def _annotation_to_json_type(annotation: Any) -> str | None:
    if isinstance(annotation, str):
        lower = annotation.strip().lower()
        if lower in {"str", "string"}:
            return "string"
        if lower in {"int", "integer"}:
            return "integer"
        if lower in {"float", "number"}:
            return "number"
        if lower in {"bool", "boolean"}:
            return "boolean"
        if lower in {"dict", "mapping", "object"}:
            return "object"
        if lower in {"list", "array", "sequence"}:
            return "array"
        return None

    if annotation in (inspect._empty, Any):
        return None
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        if origin in (list, List):
            return "array"
        if origin in (dict, Dict):
            return "object"
        if origin is tuple:
            return "array"
        if str(origin).endswith("Union"):
            args = [a for a in getattr(annotation, "__args__", []) if a is not type(None)]
            for item in args:
                inferred = _annotation_to_json_type(item)
                if inferred:
                    return inferred
            return None
    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    return None


def _infer_parameters_schema(func: Any) -> Dict[str, Any]:
    try:
        signature = inspect.signature(func)
    except Exception:
        return {"type": "object", "additionalProperties": True}

    props: Dict[str, Any] = {}
    required: List[str] = []
    allow_unknown = False
    injected = {"tool_states", "user_address", "user_id"}

    for name, param in signature.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            allow_unknown = True
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if name.startswith("_"):
            continue

        schema: Dict[str, Any] = {}
        json_type = _annotation_to_json_type(param.annotation)
        if json_type:
            schema["type"] = json_type
        if param.default is not inspect._empty:
            if isinstance(param.default, (str, int, float, bool)):
                schema["default"] = param.default
        props[name] = schema

        if (
            param.default is inspect._empty
            and name not in injected
            and param.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ):
            required.append(name)

    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": True if allow_unknown else False,
    }


def _discover_exported_tools() -> Dict[str, ToolSpec]:
    """
    Build registry from agent.Tools public exports.
    This keeps registry in sync when new tools are added to __all__.
    """
    registry: Dict[str, ToolSpec] = {}
    try:
        tools_module = importlib.import_module("agent.Tools")
    except Exception:
        tools_module = importlib.import_module("Tools")
    export_names = list(getattr(tools_module, "__all__", []) or [])

    for name in export_names:
        obj = getattr(tools_module, str(name), None)
        if not callable(obj):
            continue
        module_name = str(getattr(obj, "__module__", "") or "").strip()
        attr_name = str(getattr(obj, "__name__", name) or "").strip()
        if not module_name or not attr_name:
            continue
        registry[str(name)] = {
            "path": f"{module_name}:{attr_name}",
            "description": _auto_description(str(name)),
            "parameters": _infer_parameters_schema(obj),
        }
    return registry


def _explicit_tool_specs() -> Dict[str, ToolSpec]:
    """
    Hand-crafted schemas/descriptions for core tools with strict polymorphism.
    Remaining tools still get auto-discovered path+description.
    """
    return {
        "get_price": {
            "description": "Get latest market price for a symbol.",
        },
        "get_high_low_levels": {
            "description": "Compute support/resistance from candles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "lookback": {"type": "integer"},
                    "asset_type": {"type": "string"},
                },
                "required": ["symbol"],
                "additionalProperties": True,
            },
        },
        "get_technical_analysis": {
            "description": "Run technical analysis summary for a symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "asset_type": {"type": "string"},
                },
                "required": ["symbol"],
                "additionalProperties": True,
            },
        },
        "research_market": {
            "description": "Aggregate market research for a symbol.",
        },
        "scan_market_overview": {
            "description": "Scan broad market overview.",
        },
        "search_news": {
            "description": "Search recent news/articles for a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "mode": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": True,
            },
        },
        "search_sentiment": {
            "description": "Fetch sentiment snapshot for a symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "mode": {"type": "string"},
                    "query": {"type": "string", "description": "Alias for symbol."},
                },
                "required": ["symbol"],
                "additionalProperties": True,
            },
        },
        "search_knowledge_base": {
            "description": "Semantic search on internal knowledge base.",
        },
        "add_memory": {
            "description": "Persist user memory snippet.",
        },
        "search_memory": {
            "description": "Retrieve user memory snippets.",
        },
        "get_recent_history": {
            "description": "Get recent memory history.",
        },
        "get_active_indicators": {
            "description": "Read active TradingView indicators for symbol/timeframe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                },
                "required": ["symbol"],
                "additionalProperties": True,
            },
        },
        "add_indicator": {
            "description": "Add indicator on TradingView chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "name": {"type": "string"},
                    "inputs": {"type": "object"},
                    "force_overlay": {"type": "boolean"},
                    "period": {"type": "number", "description": "Legacy alias; mapped into inputs."},
                },
                "required": ["symbol", "name"],
                "additionalProperties": True,
            },
        },
        "remove_indicator": {
            "description": "Remove indicator from TradingView chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["symbol", "name"],
                "additionalProperties": True,
            },
        },
        "set_timeframe": {
            "description": "Set chart timeframe in TradingView.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string"},
                },
                "required": ["symbol", "timeframe"],
                "additionalProperties": True,
            },
        },
        "set_symbol": {
            "description": "Switch active TradingView symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Current chart symbol (optional)."},
                    "target_symbol": {"type": "string", "description": "New symbol to switch into."},
                    "target_source": {"type": "string"},
                },
                "required": ["target_symbol"],
                "additionalProperties": True,
            },
        },
        "setup_trade": {
            "description": "Draw trade setup on TradingView chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string"},
                    "entry": {"type": "number"},
                    "entry_price": {"type": "number", "description": "Legacy alias for entry."},
                    "sl": {"type": "number"},
                    "tp": {"type": "number"},
                    "validation": {"type": "number"},
                    "invalidation": {"type": "number"},
                    "gp": {"type": "number"},
                    "gl": {"type": "number"},
                },
                "required": ["symbol", "side", "entry", "sl", "tp"],
                "additionalProperties": True,
            },
        },
        "draw": {
            "description": "Draw an object on TradingView chart. Supports: horizontal_line, support, resistance, trend_line, ray, rectangle, fib_retracement, etc. For horizontal lines (support/resistance), only price is needed: [{\"price\": 67000}]. For trend lines, provide time+price: [{\"time\": 1234567890, \"price\": 67000}]. Use 'id' to tag drawings for later updates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "tool": {"type": "string", "description": "Tool type: horizontal_line, support, resistance, trend_line, ray, rectangle, etc."},
                    "points": {"type": "array", "description": "Points array. For horizontal_line: [{\"price\": 67000}]. For trend_line: [{\"time\": ts, \"price\": p}, ...]"},
                    "style": {"type": "object"},
                    "text": {"type": "string"},
                    "id": {"type": "string", "description": "Custom ID for updates, e.g., 'support', 'resistance', 'trailing_sl'"},
                    "line_width": {"type": "number", "description": "Legacy alias to style.linewidth."},
                    "fill": {"description": "Legacy alias to style.filled/fillColor."},
                },
                "required": ["symbol", "tool", "points"],
                "additionalProperties": True,
            },
        },
        "clear_drawings": {
            "description": "Clear drawings from TradingView chart.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
                "additionalProperties": True,
            },
        },
        "place_order": {
            "description": "Place a trading order (policy-gated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol like BTC-USD."},
                    "side": {
                        "type": "string",
                        "description": "Order side: buy/long or sell/short.",
                    },
                    "amount_usd": {
                        "type": "number",
                        "description": "Notional amount in USD.",
                    },
                    "leverage": {"type": "integer", "description": "Leverage multiplier."},
                    "order_type": {
                        "type": "string",
                        "description": "market, limit, stop_market, or stop_limit.",
                    },
                    "price": {"type": "number", "description": "Limit price for limit orders."},
                    "stop_price": {
                        "type": "number",
                        "description": "Trigger price for stop orders.",
                    },
                    "tp": {"type": "number", "description": "Take-profit price."},
                    "sl": {"type": "number", "description": "Stop-loss price."},
                    "gp": {
                        "type": "number",
                        "description": "Validation level (green point).",
                    },
                    "gl": {
                        "type": "number",
                        "description": "Invalidation level (red line).",
                    },
                    "validation": {
                        "type": "number",
                        "description": "Alias for gp (validation level).",
                    },
                    "invalidation": {
                        "type": "number",
                        "description": "Alias for gl (invalidation level).",
                    },
                    "user_address": {
                        "type": "string",
                        "description": "Wallet address. Usually injected from runtime.",
                    },
                    "exchange": {
                        "type": "string",
                        "description": "Target exchange (simulation/onchain).",
                    },
                    "reduce_only": {"type": "boolean"},
                    "post_only": {"type": "boolean"},
                    "time_in_force": {"type": "string"},
                    "trigger_condition": {"type": "string"},
                },
                "required": ["symbol", "side", "amount_usd"],
                "additionalProperties": True,
            },
        },
        "get_positions": {
            "description": "Get current open positions.",
        },
        "close_position": {
            "description": "Close specific position.",
        },
        "close_all_positions": {
            "description": "Close all positions.",
        },
        "reverse_position": {
            "description": "Reverse direction of a position.",
        },
        "cancel_order": {
            "description": "Cancel pending order by id.",
        },
    }


@lru_cache(maxsize=1)
def _build_tool_registry_cached() -> Dict[str, ToolSpec]:
    discovered = _discover_exported_tools()
    explicit = _explicit_tool_specs()

    registry: Dict[str, ToolSpec] = dict(discovered)
    for name, spec in explicit.items():
        merged = dict(registry.get(name, {}))
        merged.update(spec)
        registry[name] = merged

    return dict(sorted(registry.items(), key=lambda item: item[0]))


def build_tool_registry() -> Dict[str, ToolSpec]:
    # Return a detached copy so runtime mutations won't poison cache.
    return deepcopy(_build_tool_registry_cached())
