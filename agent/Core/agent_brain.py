"""
Agent Brain compatibility wrapper used by websocket routers.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .reflexion_agent import ReflexionAgent
from .tool_argument_adapter import adapt_tool_arguments, canonicalize_tool_name
from .tool_argument_parser import ToolArgumentParseError, parse_tool_arguments
from .tool_registry import ToolSpec, build_tool_registry, get_tool_candidate_paths

# Add agent roots to Python path so runtime imports work in both layouts:
# - imported as `agent.Core.agent_brain` from websocket service
# - imported as `Core.agent_brain` from local test scripts
project_root = Path(__file__).resolve().parent.parent
agent_src = project_root / "src"
for path in (project_root, agent_src):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

_RuntimeLLMFactory = None
for _factory_import in (
    "agent.src.core.llm_factory:LLMFactory",
    "src.core.llm_factory:LLMFactory",
    "core.llm_factory:LLMFactory",
):
    try:
        _module_name, _attr_name = _factory_import.split(":", 1)
        _module = importlib.import_module(_module_name)
        _RuntimeLLMFactory = getattr(_module, _attr_name)
        break
    except Exception:
        continue

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
logger = logging.getLogger(__name__)

WRITE_TOOLS = {
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
EXECUTION_TOOLS = {
    "place_order",
    "get_positions",
    "adjust_position_tpsl",
    "adjust_all_positions_tpsl",
    "close_position",
    "close_all_positions",
    "reverse_position",
    "cancel_order",
}
MEMORY_TOOLS = {"add_memory", "search_memory", "get_recent_history"}
WEB_TOOLS = {"search_news", "search_sentiment", "search_web_hybrid"}
TOOLS_PAYLOAD_CACHE: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}


def _normalize_model_id(model_id: str) -> str:
    raw = str(model_id or "").strip()
    if raw.startswith("openrouter/"):
        raw = raw.split("/", 1)[1]
    if raw.lower().endswith(":free"):
        raw = raw[:-5]
    return raw


def _extract_content(chunk: Any) -> str:
    """Return plain text content from common chunk shapes."""
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        text = chunk.get("text") or chunk.get("content") or ""
        if isinstance(text, str):
            return text

    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _normalize_usage(payload: Any) -> Dict[str, int]:
    """Normalize usage metadata to prompt/completion token keys."""
    if not isinstance(payload, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt = int(
        payload.get("prompt_tokens")
        or payload.get("input_tokens")
        or payload.get("input_token_count")
        or 0
    )
    completion = int(
        payload.get("completion_tokens")
        or payload.get("output_tokens")
        or payload.get("output_token_count")
        or 0
    )
    total = int(payload.get("total_tokens") or (prompt + completion))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _extract_usage(message: Any) -> Dict[str, int]:
    if message is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    usage_metadata = getattr(message, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        return _normalize_usage(usage_metadata)

    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, dict):
            return _normalize_usage(token_usage)

    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _to_chat_history(history: Optional[List[Dict[str, Any]]]) -> List[BaseMessage]:
    messages: List[BaseMessage] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if not content:
            continue
        if role == "system":
            messages.append(SystemMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


def _load_callable(dotted_path: str) -> Callable[..., Any]:
    module_name, attr_name = dotted_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _normalize_tool_name(value: Any) -> str:
    return str(value or "").strip()


def _classify_tool_error(message: str) -> str:
    text = str(message or "").lower()
    if "parser" in text or "json" in text:
        return "parser_error"
    if "unknown tool" in text:
        return "unknown_tool"
    if "failed to load tool" in text:
        return "load_error"
    if "missing" in text and "argument" in text:
        return "missing_argument"
    if "unsupported" in text and "argument" in text:
        return "unsupported_argument"
    if "404" in text or "not found" in text:
        return "endpoint_not_found"
    if "500" in text or "internal server error" in text:
        return "downstream_internal_error"
    if "offline" in text and "bridge" in text:
        return "bridge_offline"
    return "execution_error"


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"value": str(value)}, ensure_ascii=False)


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


def _reasoning_thoughts(items: List[str]) -> List[Dict[str, Any]]:
    thoughts: List[Dict[str, Any]] = []
    for idx, text in enumerate(items, start=1):
        thoughts.append(
            {
                "type": "reasoning",
                "title": f"Reasoning {idx}",
                "content": text,
                "status": "done",
            }
        )
    return thoughts


def _append_unique_thoughts(
    target: List[Dict[str, Any]], incoming: List[Dict[str, Any]]
) -> None:
    seen = {
        (
            str(item.get("type") or ""),
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("toolName") or ""),
            str(item.get("status") or ""),
        )
        for item in target
        if isinstance(item, dict)
    }
    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("type") or ""),
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("toolName") or ""),
            str(item.get("status") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        target.append(item)


def _thought_identity(item: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        str(item.get("type") or ""),
        str(item.get("title") or ""),
        str(item.get("content") or ""),
        str(item.get("toolName") or ""),
        str(item.get("status") or ""),
    )


def _tool_thought(
    *, name: str, arguments: Dict[str, Any], result_payload: Dict[str, Any]
) -> Dict[str, Any]:
    arg_keys = sorted(str(k) for k in (arguments or {}).keys())
    arg_preview = ", ".join(arg_keys[:6])
    if len(arg_keys) > 6:
        arg_preview += ", ..."

    ok = bool(result_payload.get("ok"))
    if ok:
        content = "Tool executed successfully."
    else:
        error_text = str(result_payload.get("error") or "Tool execution failed.")
        error_type = str(
            result_payload.get("error_type") or _classify_tool_error(error_text)
        )
        content = f"[{error_type}] {error_text}"

    if arg_preview:
        content = f"{content} Args: {arg_preview}."

    return {
        "type": "tool",
        "title": f"Tool {name}",
        "content": content,
        "toolName": name,
        "status": "done" if ok else "failed",
    }


def _fallback_reasoning_thought(reasoning_effort: Any) -> List[Dict[str, Any]]:
    if not _normalize_reasoning_effort(reasoning_effort):
        return []
    return [
        {
            "type": "reasoning",
            "title": "Reasoning Trace",
            "content": "Provider did not expose explicit reasoning tokens for this reply.",
            "status": "done",
        }
    ]


class AgentBrain:
    """Compatibility layer exposing chat()/stream() API used by websocket routes."""

    def __init__(
        self,
        model_id: str,
        reasoning_effort: Optional[str] = None,
        tool_states: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_iterations: int = 10,
    ):
        self.model_id = _normalize_model_id(model_id)
        self.reasoning_effort = reasoning_effort
        self.tool_states = dict(tool_states or {})
        self.user_context = dict(user_context or {})
        self.temperature = float(temperature)
        try:
            self.max_iterations = max(1, min(int(max_iterations), 12))
        except Exception:
            self.max_iterations = 6
        self.llm = None
        self._tool_registry = build_tool_registry()
        self._tool_callable_cache: Dict[str, Callable[..., Any]] = {}

        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError(
                "Missing required environment variable: OPENROUTER_API_KEY"
            )

        if _RuntimeLLMFactory is not None:
            try:
                self.llm = _RuntimeLLMFactory.get_llm(
                    model_id=self.model_id,
                    temperature=self.temperature,
                )
                self.system_prompt = _RuntimeLLMFactory.get_system_prompt(
                    model_id=self.model_id,
                    reasoning_effort=reasoning_effort,
                    tool_states=self.tool_states,
                )
            except Exception:
                self.llm = None
                self.system_prompt = self._build_fallback_system_prompt()
        else:
            self.system_prompt = self._build_fallback_system_prompt()

        retries_raw = (
            self.tool_states.get("max_retries_per_tool")
            if isinstance(self.tool_states, dict)
            else None
        )
        try:
            max_retries_per_tool = int(retries_raw) if retries_raw is not None else 2
        except Exception:
            max_retries_per_tool = 2

        # Runtime is Reflexion-only; AgentBrain remains as a compatibility wrapper.
        self._reflexion_agent = ReflexionAgent(
            model_id=self.model_id,
            tool_states=dict(self.tool_states or {}),
            user_context=dict(self.user_context or {}),
            temperature=self.temperature,
            max_iterations=self.max_iterations,
            max_retries_per_tool=max_retries_per_tool,
        )

    def _build_fallback_system_prompt(self) -> str:
        base = (
            "You are a helpful AI assistant. "
            "Be concise, factual, and clear in your responses."
        )
        if self.reasoning_effort:
            base += f" Reasoning effort: {self.reasoning_effort}."
        return base

    def _build_messages(
        self, user_message: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> List[BaseMessage]:
        messages: List[BaseMessage] = []
        if self.system_prompt:
            messages.append(SystemMessage(content=self.system_prompt))
        messages.extend(_to_chat_history(history))
        messages.append(HumanMessage(content=user_message))
        return messages

    def _build_openrouter_messages(
        self, user_message: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

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

        messages.append({"role": "user", "content": str(user_message or "")})
        return messages

    def _openrouter_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": "Osmo Trading Terminal",
        }

    def _tool_calling_enabled(self) -> bool:
        if not isinstance(self.tool_states, dict):
            return False
        for key in (
            "strict_react",
            "write",
            "execution",
            "web_observation_enabled",
            "memory_enabled",
            "plan_mode",
        ):
            raw = self.tool_states.get(key)
            if isinstance(raw, bool) and raw:
                return True
            if isinstance(raw, str) and raw.strip().lower() in {
                "1",
                "true",
                "on",
                "yes",
            }:
                return True
        return False

    def _state_flag(self, key: str) -> Optional[bool]:
        if not isinstance(self.tool_states, dict):
            return None
        if key not in self.tool_states:
            return None
        raw = self.tool_states.get(key)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "on", "yes"}
        return bool(raw)

    def _resolve_tools_for_payload(self) -> List[str]:
        names = list(self._tool_registry.keys())

        enabled_tools = None
        strict_enabled_tools = False
        if isinstance(self.tool_states, dict):
            raw_enabled = self.tool_states.get("enabled_tools")
            strict_raw = self.tool_states.get("strict_enabled_tools")
            if isinstance(strict_raw, bool):
                strict_enabled_tools = strict_raw
            elif isinstance(strict_raw, str):
                strict_enabled_tools = strict_raw.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
            if isinstance(raw_enabled, list):
                enabled_tools = {
                    canonicalize_tool_name(_normalize_tool_name(item))
                    for item in raw_enabled
                }
                enabled_tools = {item for item in enabled_tools if item}

        if enabled_tools:
            filtered = [name for name in names if name in enabled_tools]
            if strict_enabled_tools:
                if filtered:
                    return filtered
                return list(self._tool_registry.keys())
            # Non-strict mode: tolerate stale frontend allowlists by keeping full registry.
            if filtered and len(filtered) >= len(names):
                return filtered

        write_flag = self._state_flag("write")
        execution_flag = self._state_flag("execution")
        memory_flag = self._state_flag("memory_enabled")
        web_flag = self._state_flag("web_observation_enabled")

        if write_flag is False:
            names = [name for name in names if name not in WRITE_TOOLS]
        if execution_flag is False:
            names = [name for name in names if name not in EXECUTION_TOOLS]
        if memory_flag is False:
            names = [name for name in names if name not in MEMORY_TOOLS]
        if web_flag is False:
            names = [name for name in names if name not in WEB_TOOLS]

        return names

    def _openrouter_tools_payload(self) -> List[Dict[str, Any]]:
        allowed_names = tuple(sorted(self._resolve_tools_for_payload()))
        cached_payload = TOOLS_PAYLOAD_CACHE.get(allowed_names)
        if cached_payload is not None:
            return cached_payload

        payload: List[Dict[str, Any]] = []
        for name in allowed_names:
            spec = self._tool_registry.get(name)
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
        TOOLS_PAYLOAD_CACHE[allowed_names] = payload
        return payload

    def _resolve_tool_iterations(self) -> int:
        raw = (
            self.tool_states.get("max_tool_actions")
            if isinstance(self.tool_states, dict)
            else None
        )
        if raw is None:
            raw = (
                self.tool_states.get("max_react_iterations")
                if isinstance(self.tool_states, dict)
                else None
            )
        try:
            value = int(raw) if raw is not None else self.max_iterations
        except Exception:
            value = self.max_iterations
        return max(1, min(value, 12))

    def _resolve_max_parallel_tools(self) -> int:
        raw = (
            self.tool_states.get("max_parallel_tools")
            if isinstance(self.tool_states, dict)
            else None
        )
        try:
            value = int(raw) if raw is not None else 4
        except Exception:
            value = 4
        return max(1, min(value, 16))

    def _get_tool_callable(self, tool_name: str, spec: ToolSpec) -> Callable[..., Any]:
        cached = self._tool_callable_cache.get(tool_name)
        if cached is not None:
            return cached

        errors: List[str] = []
        for dotted_path in get_tool_candidate_paths(spec):
            try:
                func = _load_callable(dotted_path)
                self._tool_callable_cache[tool_name] = func
                return func
            except Exception as exc:
                errors.append(f"{dotted_path} -> {exc}")
        detail = " | ".join(errors) if errors else "no candidate paths"
        raise RuntimeError(f"Failed to load tool {tool_name}: {detail}")

    def _sync_runtime_tool_state(
        self,
        *,
        tool_name: str,
        call_kwargs: Dict[str, Any],
        result_payload: Any,
    ) -> None:
        if not isinstance(self.tool_states, dict):
            return

        state_evidence: Dict[str, Any] = {}
        if isinstance(result_payload, dict):
            candidate = result_payload.get("state_evidence")
            if isinstance(candidate, dict):
                state_evidence = candidate

        symbol_value = ""
        if tool_name == "set_symbol":
            symbol_value = str(
                call_kwargs.get("target_symbol")
                or call_kwargs.get("symbol")
                or state_evidence.get("symbol")
                or ""
            ).strip()
        elif "symbol" in call_kwargs:
            symbol_value = str(
                state_evidence.get("symbol") or call_kwargs.get("symbol") or ""
            ).strip()
        elif state_evidence.get("symbol"):
            symbol_value = str(state_evidence.get("symbol") or "").strip()

        if symbol_value:
            self.tool_states["market_symbol"] = symbol_value
            self.tool_states["market"] = symbol_value

        timeframe_value = ""
        if tool_name == "set_timeframe":
            timeframe_value = str(
                call_kwargs.get("timeframe") or state_evidence.get("timeframe") or ""
            ).strip()
        elif state_evidence.get("timeframe"):
            timeframe_value = str(state_evidence.get("timeframe") or "").strip()

        if timeframe_value:
            self.tool_states["market_timeframe"] = timeframe_value
            self.tool_states["timeframe"] = [timeframe_value]

    async def _execute_tool_call(
        self,
        *,
        name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        tool_name = canonicalize_tool_name(_normalize_tool_name(name))
        if isinstance(arguments, dict) and arguments.get("__parse_error__"):
            parse_error = str(arguments.get("__parse_error__"))
            logger.warning(
                "Tool parse error before execution: tool=%s error=%s raw=%s",
                tool_name,
                parse_error,
                str(arguments.get("raw_arguments", ""))[:500],
            )
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "parser_error",
                "error": parse_error,
                "parser": {"raw_arguments": arguments.get("raw_arguments")},
            }

        spec = self._tool_registry.get(tool_name)
        if not spec:
            message = f"Unknown tool: {tool_name}"
            logger.warning("Tool lookup failed: %s", message)
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "unknown_tool",
                "error": message,
            }

        if not get_tool_candidate_paths(spec):
            message = f"Tool not configured: {tool_name}"
            logger.error("Tool configuration error: %s", message)
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "config_error",
                "error": message,
            }

        try:
            func = self._get_tool_callable(tool_name, spec)
        except Exception as exc:
            message = str(exc)
            logger.error("Tool load error: tool=%s error=%s", tool_name, message)
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "load_error",
                "error": message,
            }

        kwargs = dict(arguments or {})
        user_address = str(self.user_context.get("user_address") or "").strip()
        signature: Optional[inspect.Signature] = None

        try:
            signature = inspect.signature(func)
            parameters = signature.parameters
            param_names = set(parameters.keys())
            accepts_var_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
            )
        except Exception:
            param_names = set()
            accepts_var_kwargs = True

        kwargs = adapt_tool_arguments(
            tool_name=tool_name,
            arguments=kwargs,
            param_names=param_names,
            tool_states=self.tool_states,
        )

        if "tool_states" in param_names and "tool_states" not in kwargs:
            kwargs["tool_states"] = dict(self.tool_states or {})
        if (
            "user_address" in param_names
            and not kwargs.get("user_address")
            and user_address
        ):
            kwargs["user_address"] = user_address
        if "user_id" in param_names and not kwargs.get("user_id") and user_address:
            kwargs["user_id"] = user_address

        symbol_fallback = str(
            kwargs.get("symbol") or self.tool_states.get("market_symbol", "")
            if isinstance(self.tool_states, dict)
            else ""
        ).strip()
        if "symbol" in param_names and not kwargs.get("symbol") and symbol_fallback:
            kwargs["symbol"] = symbol_fallback

        try:
            parsed_kwargs, parse_meta = parse_tool_arguments(
                tool_name=tool_name,
                arguments=kwargs,
                signature=signature or inspect.signature(func),
                allow_unknown=accepts_var_kwargs,
            )
            kwargs = parsed_kwargs
            if not accepts_var_kwargs and param_names:
                kwargs = {k: v for k, v in kwargs.items() if k in param_names}
            if parse_meta.get("unknown_fields"):
                logger.info(
                    "Tool unknown args dropped: tool=%s unknown=%s",
                    tool_name,
                    parse_meta.get("unknown_fields"),
                )
        except ToolArgumentParseError as exc:
            logger.warning(
                "Tool parser failed: tool=%s details=%s",
                tool_name,
                exc.details,
            )
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "parser_error",
                "error": str(exc),
                "parser": exc.details,
            }
        except Exception as exc:
            logger.warning(
                "Tool parser unexpected error: tool=%s error=%s",
                tool_name,
                str(exc),
            )
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": "parser_error",
                "error": f"Unexpected parser error: {exc}",
            }

        try:
            result = func(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict) and result.get("error"):
                error_text = str(result.get("error"))
                error_type = _classify_tool_error(error_text)
                logger.warning(
                    "Tool runtime returned error payload: tool=%s error_type=%s error=%s",
                    tool_name,
                    error_type,
                    error_text,
                )
                return {
                    "ok": False,
                    "tool": tool_name,
                    "error_type": error_type,
                    "error": error_text,
                    "result": result,
                }
            self._sync_runtime_tool_state(
                tool_name=tool_name,
                call_kwargs=kwargs,
                result_payload=result,
            )
            return {"ok": True, "tool": tool_name, "result": result}
        except Exception as exc:
            error_text = str(exc)
            error_type = _classify_tool_error(error_text)
            logger.exception(
                "Tool execution exception: tool=%s error_type=%s error=%s",
                tool_name,
                error_type,
                error_text,
            )
            return {
                "ok": False,
                "tool": tool_name,
                "error_type": error_type,
                "error": error_text,
            }

    async def _chat_via_openrouter_with_tools(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = self._build_openrouter_messages(
            user_message, history
        )
        tools_payload = self._openrouter_tools_payload()
        max_rounds = self._resolve_tool_iterations()
        max_parallel_tools = self._resolve_max_parallel_tools()
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        executed_tools: List[Dict[str, Any]] = []
        collected_thoughts: List[Dict[str, Any]] = []
        emitted_thoughts: set[Tuple[str, str, str, str, str]] = set()
        tool_sem = asyncio.Semaphore(max_parallel_tools)

        async def _emit(event: Dict[str, Any]) -> None:
            if progress_callback is None:
                return
            try:
                await progress_callback(event)
            except Exception:
                logger.debug("Tool stream progress callback failed", exc_info=True)

        async def _emit_new_thoughts(candidates: List[Dict[str, Any]]) -> None:
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                identity = _thought_identity(item)
                if identity in emitted_thoughts:
                    continue
                emitted_thoughts.add(identity)
                await _emit({"type": "thoughts_delta", "thought": item})

        async with httpx.AsyncClient(timeout=60.0) as client:
            for round_idx in range(max_rounds):
                await _emit(
                    {
                        "type": "runtime_phase",
                        "phase": {
                            "name": "tool_round",
                            "status": "running",
                            "detail": f"Tool round {round_idx + 1}/{max_rounds}",
                            "meta": {
                                "loop": round_idx + 1,
                                "max_rounds": max_rounds,
                                "synthetic": True,
                            },
                        },
                    }
                )
                payload = {
                    "model": self.model_id,
                    "messages": messages,
                    "temperature": self.temperature,
                    "tools": tools_payload,
                    "tool_choice": "auto",
                }
                payload.update(_reasoning_request_fields(self.reasoning_effort))
                response = await client.post(
                    OPENROUTER_CHAT_URL,
                    headers=self._openrouter_headers(),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()

                usage = _normalize_usage(body.get("usage"))
                usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
                usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
                usage_total["total_tokens"] += usage.get("total_tokens", 0)

                choices = body.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                assistant_content = _extract_content(message)
                raw_tool_calls = message.get("tool_calls") or []
                reasoning_texts = _extract_reasoning_texts(
                    [
                        body.get("reasoning"),
                        body.get("reasoning_details"),
                        choices[0].get("reasoning", {}) if choices else {},
                        message.get("reasoning"),
                        message.get("reasoning_content"),
                        message.get("thinking"),
                    ]
                )
                _append_unique_thoughts(
                    collected_thoughts, _reasoning_thoughts(reasoning_texts)
                )
                await _emit_new_thoughts(_reasoning_thoughts(reasoning_texts))

                if not raw_tool_calls:
                    if not collected_thoughts:
                        _append_unique_thoughts(
                            collected_thoughts,
                            _fallback_reasoning_thought(self.reasoning_effort),
                        )
                    return {
                        "content": assistant_content,
                        "usage": usage_total,
                        "thoughts": collected_thoughts,
                        "runtime": {
                            "engine": "openrouter_http_tools",
                            "model_id": self.model_id,
                            "reasoning_effort": self.reasoning_effort,
                            "tool_calls_count": len(executed_tools),
                            "tool_calls": executed_tools[-20:],
                        },
                    }

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content or "",
                        "tool_calls": raw_tool_calls,
                    }
                )

                parsed_calls: List[Tuple[str, str, Dict[str, Any]]] = []
                for call in raw_tool_calls:
                    call_id = str(call.get("id") or "").strip()
                    func = call.get("function") or {}
                    name = _normalize_tool_name(func.get("name"))
                    args_raw = func.get("arguments")
                    args: Dict[str, Any] = {}
                    if isinstance(args_raw, str) and args_raw.strip():
                        try:
                            parsed = json.loads(args_raw)
                            if isinstance(parsed, dict):
                                args = parsed
                        except Exception as exc:
                            args = {
                                "__parse_error__": f"Invalid tool arguments JSON: {exc}",
                                "raw_arguments": args_raw,
                            }
                    elif isinstance(args_raw, dict):
                        args = dict(args_raw)
                    parsed_calls.append((call_id, name, args))

                async def _run_tool_with_limit(
                    idx: int,
                    call_id: str,
                    tool_name: str,
                    tool_args: Dict[str, Any],
                ) -> Tuple[int, str, str, Dict[str, Any], Dict[str, Any]]:
                    async with tool_sem:
                        result = await self._execute_tool_call(
                            name=tool_name, arguments=tool_args
                        )
                        return idx, call_id, tool_name, tool_args, result

                pending = [
                    asyncio.create_task(_run_tool_with_limit(idx, call_id, name, args))
                    for idx, (call_id, name, args) in enumerate(parsed_calls)
                ]
                ordered_tool_results: Dict[
                    int, Tuple[str, str, Dict[str, Any], Dict[str, Any]]
                ] = {}

                for done_task in asyncio.as_completed(pending):
                    try:
                        idx, call_id, name, args, result_payload = await done_task
                    except Exception as exc:
                        idx = -1
                        call_id = ""
                        name = "unknown_tool"
                        args = {}
                        result_payload = {
                            "ok": False,
                            "tool": name,
                            "error_type": "execution_error",
                            "error": str(exc),
                        }

                    if idx >= 0:
                        ordered_tool_results[idx] = (
                            call_id,
                            name,
                            args,
                            result_payload,
                        )

                    phase_status = (
                        "done" if bool(result_payload.get("ok")) else "failed"
                    )
                    await _emit(
                        {
                            "type": "runtime_phase",
                            "phase": {
                                "name": "tool_execution",
                                "status": phase_status,
                                "detail": name,
                                "meta": {
                                    "tool": name,
                                    "loop": round_idx + 1,
                                    "synthetic": True,
                                },
                            },
                        }
                    )

                    tool_thought = _tool_thought(
                        name=name,
                        arguments=args,
                        result_payload=result_payload,
                    )
                    _append_unique_thoughts(collected_thoughts, [tool_thought])
                    await _emit_new_thoughts([tool_thought])

                for idx in sorted(ordered_tool_results.keys()):
                    call_id, name, args, result_payload = ordered_tool_results[idx]
                    executed_tools.append(
                        {
                            "id": call_id,
                            "name": name,
                            "args": args,
                            "result": result_payload,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": _json_dumps(result_payload),
                        }
                    )

        return {
            "content": "I reached the tool-iteration limit before finalizing the answer.",
            "usage": usage_total,
            "thoughts": (
                collected_thoughts or _fallback_reasoning_thought(self.reasoning_effort)
            ),
            "runtime": {
                "engine": "openrouter_http_tools",
                "model_id": self.model_id,
                "reasoning_effort": self.reasoning_effort,
                "tool_calls_count": len(executed_tools),
                "tool_calls": executed_tools[-20:],
                "truncated": True,
            },
        }

    async def _chat_via_openrouter(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model_id,
            "messages": self._build_openrouter_messages(user_message, history),
            "temperature": self.temperature,
        }
        payload.update(_reasoning_request_fields(self.reasoning_effort))

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._openrouter_headers(),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        choices = body.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = _extract_content(message)
        reasoning_texts = _extract_reasoning_texts(
            [
                body.get("reasoning"),
                body.get("reasoning_details"),
                choices[0].get("reasoning", {}) if choices else {},
                message.get("reasoning"),
                message.get("reasoning_content"),
                message.get("thinking"),
            ]
        )
        thoughts = _reasoning_thoughts(reasoning_texts)
        if not thoughts:
            thoughts = _fallback_reasoning_thought(self.reasoning_effort)
        usage = _normalize_usage(body.get("usage"))
        if usage["total_tokens"] == 0:
            usage["completion_tokens"] = max(0, len(content) // 4)
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        return {
            "content": content,
            "usage": usage,
            "thoughts": thoughts,
            "runtime": {
                "engine": "openrouter_http",
                "model_id": self.model_id,
                "reasoning_effort": self.reasoning_effort,
            },
        }

    async def _stream_via_openrouter(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        payload = {
            "model": self.model_id,
            "messages": self._build_openrouter_messages(user_message, history),
            "temperature": self.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(_reasoning_request_fields(self.reasoning_effort))

        chunks: List[str] = []
        reasoning_parts: List[str] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                OPENROUTER_CHAT_URL,
                headers=self._openrouter_headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    raw = await response.aread()
                    detail = raw.decode("utf-8", errors="ignore")
                    raise RuntimeError(
                        f"OpenRouter stream failed ({response.status_code}): {detail}"
                    )

                async for raw_line in response.aiter_lines():
                    line = str(raw_line or "").strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        break

                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue

                    choices = event.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        text = _extract_content(delta)
                        if text:
                            chunks.append(text)
                            yield {"type": "delta", "content": text}
                        reasoning_delta = _extract_reasoning_texts(delta)
                        for thought in reasoning_delta:
                            reasoning_parts.append(thought)
                            yield {"type": "thoughts_delta", "thought": thought}

                    candidate_usage = _normalize_usage(event.get("usage"))
                    if candidate_usage["total_tokens"] > 0:
                        usage = candidate_usage

        combined = "".join(chunks)
        thoughts = _reasoning_thoughts(_extract_reasoning_texts(reasoning_parts))
        if not thoughts:
            thoughts = _fallback_reasoning_thought(self.reasoning_effort)

        if usage["total_tokens"] == 0:
            usage["completion_tokens"] = max(0, len(combined) // 4)
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        if thoughts:
            yield {"type": "thoughts", "thoughts": thoughts}

        yield {
            "type": "done",
            "content": combined,
            "usage": usage,
            "thoughts": thoughts,
        }

    async def chat(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        try:
            session_id = str(self.user_context.get("session_id") or "").strip()
            reflexion = await self._reflexion_agent.chat(
                user_message=user_message,
                history=history,
                session_id=session_id,
            )
            output = str(reflexion.get("response") or "")
            state_summary = (
                reflexion.get("state_summary")
                if isinstance(reflexion.get("state_summary"), dict)
                else {}
            ) or {}
            actions = state_summary.get("actions", {}) or {}
            usage = {
                "prompt_tokens": max(0, len(str(user_message or "")) // 4),
                "completion_tokens": max(0, len(output) // 4),
                "total_tokens": 0,
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

            thoughts: List[Dict[str, Any]] = []
            if state_summary:
                thoughts.append(
                    {
                        "type": "reasoning",
                        "title": "Reflexion Summary",
                        "content": (
                            f"steps={int(state_summary.get('total_steps', 0))}, "
                            f"good={int(actions.get('good', 0))}, "
                            f"errors={int(actions.get('errors', 0))}, "
                            f"retried={int(actions.get('retried', 0))}, "
                            f"reflections={int(state_summary.get('reflections', 0))}"
                        ),
                        "status": "done",
                    }
                )

            return {
                "content": output,
                "usage": usage,
                "thoughts": thoughts,
                "runtime": {
                    "engine": "reflexion_agent",
                    "model_id": self.model_id,
                    "reasoning_effort": self.reasoning_effort,
                    "tool_calls_count": int(
                        reflexion.get("tool_calls")
                        or state_summary.get("total_steps")
                        or 0
                    ),
                    "state_summary": state_summary,
                },
            }
        except Exception as exc:
            raise RuntimeError(f"Reflexion runtime failed: {exc}") from exc

    async def stream(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        chat_task = asyncio.create_task(
            self.chat(
                user_message=user_message,
                history=history,
                attachments=attachments,
            )
        )
        started = time.monotonic()

        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(chat_task), timeout=0.25)
                break
            except asyncio.TimeoutError:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                yield {
                    "type": "status",
                    "stage": "reflexion_loop",
                    "elapsed_ms": elapsed_ms,
                }
            except asyncio.CancelledError:
                chat_task.cancel()
                raise

        runtime = result.get("runtime", {}) or {}
        if runtime:
            yield {"type": "runtime", "runtime": runtime}

        thoughts = result.get("thoughts", []) or []
        if thoughts:
            yield {"type": "thoughts", "thoughts": thoughts}

        content = str(result.get("content") or "")
        chunk_size = 220
        for i in range(0, len(content), chunk_size):
            yield {"type": "delta", "content": content[i : i + chunk_size]}

        yield {
            "type": "done",
            "content": content,
            "usage": result.get("usage", {}) or {},
            "thoughts": thoughts,
        }

    async def process_query(
        self, query: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Legacy compatibility entry point."""
        return await self.chat(user_message=query, history=history, attachments=None)


__all__ = ["AgentBrain"]
