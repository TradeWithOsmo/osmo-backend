from __future__ import annotations

import asyncio
import inspect
import json
import re
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from typing import get_type_hints

from ..Orchestrator.tool_orchestrator import ToolOrchestrator
from ..Orchestrator.tool_registry import get_tool_registry
from ..Orchestrator.tool_modes import WRITE_TOOL_NAMES, NAV_TOOL_NAMES, classify_tool_mode
from ..Schema.agent_runtime import ToolCall, ToolResult

try:
    from deepagents import create_deep_agent
except Exception:  # pragma: no cover - optional dependency at runtime
    create_deep_agent = None


class DeepAgentsRuntime:
    """
    Native Deep Agents runtime adapter with Osmo tool registry wiring.
    """

    _WRITE_TOOL_NAMES = set(WRITE_TOOL_NAMES)
    _TRADINGVIEW_NAV_TOOLS = {
        name for name in NAV_TOOL_NAMES
        if name not in {"mouse_move", "mouse_press", "pan", "zoom", "press_key", "set_crosshair", "move_crosshair"}
    }
    _MEMORY_TOOL_NAMES = {"add_memory", "search_memory", "get_recent_history"}
    _NON_RETRYABLE_MARKERS = (
        "unknown tool",
        "requires write mode",
        "allow write",
        "missing required",
        "validation error",
        "invalid argument",
        "blocked by",
        "not supported",
        "unsupported",
    )
    _DEFAULT_ANALYSIS_TOOLS = {
        "get_price",
        "get_candles",
        "get_high_low_levels",
        "get_technical_analysis",
        "get_indicators",
        "get_technical_summary",
        "get_ticker_stats",
        "search_knowledge_base",
        "consult_strategy",
    }
    _OPTIONAL_TOOL_KEYWORDS: Dict[str, tuple[str, ...]] = {
        "search_news": ("news", "headline", "macro", "event"),
        "search_sentiment": ("sentiment", "x.com", "twitter", "social"),
        "get_whale_activity": ("whale", "onchain", "big wallet"),
        "get_token_distribution": ("distribution", "holder", "supply"),
        "get_orderbook": ("orderbook", "depth", "bid ask"),
        "get_funding_rate": ("funding",),
        "get_patterns": ("pattern", "bos", "liquidity", "sweep"),
        "get_high_low_levels": ("high low", "high/low", "support", "resistance", "s/r"),
        "get_active_indicators": ("indicator", "rsi", "macd", "ema", "sma"),
        "consult_strategy": ("strategy", "playbook", "framework", "context", "regime"),
        "get_trade_management_guidance": ("risk", "position size", "trade management"),
        "get_drawing_guidance": ("drawing", "chart draw"),
        "get_chainlink_price": ("oracle", "chainlink"),
    }
    _TRADINGVIEW_INTENT_KEYWORDS = (
        "tradingview",
        "chart",
        "candle",
        "cursor",
        "screenshot",
        "photo chart",
        "focus chart",
        "draw",
        "indicator",
        "set symbol",
        "set timeframe",
    )
    _MARKET_EVIDENCE_KEYWORDS = (
        "analysis",
        "bias",
        "scenario",
        "probability",
        "trading",
        "market",
        "setup",
        "entry",
        "stop",
        "risk",
    )
    _CRYPTO_BASES = {
        "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "MATIC",
        "LINK", "SUI", "APT", "ARB", "ARK", "BERA", "OP",
    }

    def __init__(
        self,
        *,
        llm: Any,
        system_prompt: str,
        tool_states: Optional[Dict[str, Any]] = None,
        tool_timeout_sec: float = 8.0,
    ) -> None:
        self.llm = llm
        self.system_prompt = str(system_prompt or "").strip()
        self.tool_states = dict(tool_states or {})
        self._registry = get_tool_registry()
        self._orchestrator = ToolOrchestrator(
            registry=self._registry,
            tool_timeout_sec=tool_timeout_sec,
        )
        self._captured_results: List[ToolResult] = []
        self._phases: List[Dict[str, Any]] = []
        self._tool_result_cache: Dict[str, ToolResult] = {}
        self._tool_cache_hits: int = 0
        self._max_tool_actions: Optional[int] = self._resolve_max_tool_actions()
        self._model_timeout_sec: float = self._resolve_model_timeout_sec()
        self._write_txn_id: Optional[str] = None

    @classmethod
    def is_available(cls) -> bool:
        return create_deep_agent is not None

    def _phase(self, name: str, details: Optional[Dict[str, Any]] = None) -> None:
        item: Dict[str, Any] = {"name": name}
        if details:
            item.update(details)
        self._phases.append(item)

    def _parse_bool(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "on", "yes"}:
                return True
            if normalized in {"0", "false", "off", "no"}:
                return False
            return default
        return bool(value)

    def _should_expose_tool(self, tool_name: str) -> bool:
        write_enabled = self._parse_bool(self.tool_states.get("write"), default=False)
        memory_enabled = self._parse_bool(self.tool_states.get("memory_enabled"), default=False)
        if not write_enabled and classify_tool_mode(tool_name) == "write":
            return False
        if not memory_enabled and tool_name in self._MEMORY_TOOL_NAMES:
            return False
        return True

    def _is_retryable_error(self, error: Optional[str]) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return True
        return not any(marker in text for marker in self._NON_RETRYABLE_MARKERS)

    def _is_connectivity_error(self, error: Optional[str]) -> bool:
        text = str(error or "").strip().lower()
        markers = (
            "connection attempts failed",
            "unable to connect",
            "connection refused",
            "name resolution",
            "timed out",
            "timeout",
            "network is unreachable",
        )
        return any(marker in text for marker in markers)

    def _max_tool_attempts(self) -> int:
        raw = (
            self.tool_states.get("tool_retry_max")
            or self.tool_states.get("max_tool_retries")
            or 2
        )
        try:
            value = int(raw)
        except Exception:
            value = 2
        return max(1, min(value, 4))

    def _resolve_max_tool_actions(self) -> Optional[int]:
        raw = self.tool_states.get("max_tool_actions")
        if raw is None:
            return None
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"none", "unlimited", "inf", "infinite", "0", "-1"}:
                return None
        try:
            value = int(raw)
        except Exception:
            return None
        if value <= 0:
            return None
        return value

    def _resolve_model_timeout_sec(self) -> float:
        raw = self.tool_states.get("model_timeout_sec")
        if raw is None:
            raw = 120.0 if self._is_compact_profile() else 180.0
        try:
            value = float(raw)
        except Exception:
            value = 120.0 if self._is_compact_profile() else 180.0
        return max(20.0, min(value, 300.0))

    def _normalize_state_symbol(self, value: Any) -> str:
        raw = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
        if not raw:
            return ""
        if "-" in raw:
            base, quote = raw.split("-", 1)
            if quote in {"USD", "USDT"}:
                return f"{base}-USD"
            return f"{base}-{quote}"
        if raw.endswith("USDT") and len(raw) > 4:
            return f"{raw[:-4]}-USD"
        if raw.endswith("USD") and len(raw) > 3:
            return f"{raw[:-3]}-USD"
        return raw

    def _normalize_state_timeframe(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        mapping = {
            "1M": "1m",
            "3M": "3m",
            "5M": "5m",
            "15M": "15m",
            "30M": "30m",
            "1H": "1H",
            "4H": "4H",
            "1D": "1D",
            "1W": "1W",
        }
        return mapping.get(text, text)

    def _enforce_write_precision(self, result: ToolResult) -> ToolResult:
        if not result.ok or not isinstance(result.data, dict):
            return result
        if str(result.data.get("transport") or "").strip().lower() != "tradingview_command":
            return result

        strict = self._parse_bool(self.tool_states.get("strict_write_verification"), default=True)
        if not strict:
            return result

        status = str(result.data.get("status") or "").strip().lower()
        command_result = result.data.get("command_result") if isinstance(result.data.get("command_result"), dict) else {}
        result_status = str(command_result.get("status") or "").strip().lower()
        expected = result.data.get("expected_state") if isinstance(result.data.get("expected_state"), dict) else {}
        evidence = result.data.get("state_evidence") if isinstance(result.data.get("state_evidence"), dict) else {}

        if status not in {"completed", "success", "ok", "done"}:
            result.ok = False
            result.error = f"write command status={status or 'unknown'}"
            result.data["error"] = result.error
            return result
        if result_status and result_status not in {"completed", "success", "ok", "done"}:
            result.ok = False
            result.error = f"write command result_status={result_status}"
            result.data["error"] = result.error
            return result

        missing: List[str] = []
        mismatch: List[str] = []
        for key, expected_value in expected.items():
            if key not in evidence:
                missing.append(key)
                continue
            actual = evidence.get(key)
            if key == "symbol":
                if self._normalize_state_symbol(actual) != self._normalize_state_symbol(expected_value):
                    mismatch.append(key)
            elif key == "timeframe":
                if self._normalize_state_timeframe(actual) != self._normalize_state_timeframe(expected_value):
                    mismatch.append(key)
            elif str(actual or "").strip().lower() != str(expected_value or "").strip().lower():
                mismatch.append(key)

        if missing or mismatch:
            details: List[str] = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if mismatch:
                details.append("mismatch=" + ",".join(mismatch))
            result.ok = False
            result.error = "write verification failed (" + "; ".join(details) + ")"
            result.data["error"] = result.error
        return result

    def _tool_call_cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)}"

    def _tool_accepts_kwarg(self, signature: inspect.Signature, arg_name: str) -> bool:
        if arg_name in signature.parameters:
            return True
        return any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

    def _to_safe_tool_content(self, data: Any, error: Optional[str] = None) -> str:
        """
        Normalize tool output to provider-safe string content for role=tool messages.
        """
        payload: Dict[str, Any] = {}
        if error:
            payload["error"] = str(error)
        if data is None:
            payload.setdefault("result", None)
        elif isinstance(data, (str, int, float, bool)):
            payload.setdefault("result", data)
        elif isinstance(data, dict):
            payload.update(data)
        elif isinstance(data, list):
            payload["items"] = data
        else:
            payload["result"] = str(data)
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _is_compact_profile(self) -> bool:
        raw = self.tool_states.get("tool_profile")
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"compact", "small", "token_saver"}:
                return True
            if normalized in {"full", "all"}:
                return False
        provider = str(self.tool_states.get("runtime_model_provider") or "").strip().lower()
        model_id = str(self.tool_states.get("runtime_model_id") or "").strip().lower()
        if provider == "groq" or model_id.startswith("groq/"):
            return True
        return False

    def _select_tool_names(self, user_message: str) -> set[str]:
        if not self._is_compact_profile():
            return set(self._registry.keys())

        text = str(user_message or "").lower()
        selected = set(self._DEFAULT_ANALYSIS_TOOLS)

        for tool_name, keywords in self._OPTIONAL_TOOL_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                selected.add(tool_name)

        if self._parse_bool(self.tool_states.get("memory_enabled"), default=False):
            selected.update(self._MEMORY_TOOL_NAMES)

        if self._parse_bool(self.tool_states.get("write"), default=False):
            selected.update(self._WRITE_TOOL_NAMES)

        if any(kw in text for kw in self._TRADINGVIEW_INTENT_KEYWORDS):
            selected.update(self._TRADINGVIEW_NAV_TOOLS)
            selected.add("get_active_indicators")

        return selected

    def _build_wrapped_tools(self, *, user_message: str) -> List[Any]:
        wrapped: List[Any] = []
        max_attempts = self._max_tool_attempts()
        selected_tool_names = self._select_tool_names(user_message=user_message)

        for tool_name, tool_fn in self._registry.items():
            if tool_name not in selected_tool_names:
                continue
            if not self._should_expose_tool(tool_name):
                continue
            signature = inspect.signature(tool_fn)

            async def _wrapped(*args: Any, __tool_name: str = tool_name, __sig=signature, **kwargs: Any) -> Any:
                if self._max_tool_actions is not None and len(self._captured_results) >= self._max_tool_actions:
                    self._phase(
                        "tool_budget_reached",
                        {
                            "tool": __tool_name,
                            "stage": "guard",
                            "max_tool_actions": self._max_tool_actions,
                        },
                    )
                    return self._to_safe_tool_content(
                        None,
                        error=(
                            f"Tool action budget reached ({self._max_tool_actions}). "
                            "Summarize with current evidence."
                        ),
                    )

                bound = __sig.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                call_args = dict(bound.arguments)
                if (
                    classify_tool_mode(__tool_name) == "write"
                    and self._write_txn_id
                    and self._tool_accepts_kwarg(__sig, "write_txn_id")
                ):
                    call_args.setdefault("write_txn_id", self._write_txn_id)
                cache_key = self._tool_call_cache_key(__tool_name, call_args)

                cached = self._tool_result_cache.get(cache_key)
                if cached is not None:
                    self._tool_cache_hits += 1
                    self._phase(
                        "tool_cache_hit",
                        {
                            "tool": __tool_name,
                            "stage": "observe",
                            "ok": bool(cached.ok),
                        },
                    )
                    return self._to_safe_tool_content(cached.data, error=cached.error)

                attempt = 0
                while attempt < max_attempts:
                    attempt += 1
                    self._phase(
                        "tool_call",
                        {"tool": __tool_name, "stage": "act", "attempt": attempt, "max_attempts": max_attempts},
                    )
                    result = await self._orchestrator.run_tool(
                        ToolCall(name=__tool_name, args=call_args),
                        tool_states=self.tool_states,
                    )
                    if classify_tool_mode(__tool_name) == "write":
                        result = self._enforce_write_precision(result)
                    self._captured_results.append(result)
                    self._phase(
                        "tool_observe",
                        {
                            "tool": __tool_name,
                            "stage": "observe",
                            "attempt": attempt,
                            "ok": bool(result.ok),
                            "error": result.error if not result.ok else None,
                        },
                    )

                    has_data_error = isinstance(result.data, dict) and bool(result.data.get("error"))
                    if result.ok and not has_data_error:
                        self._tool_result_cache[cache_key] = result
                        return self._to_safe_tool_content(result.data)

                    if attempt >= max_attempts or not self._is_retryable_error(result.error):
                        self._tool_result_cache[cache_key] = result
                        return self._to_safe_tool_content(
                            result.data,
                            error=result.error or f"{__tool_name} failed",
                        )

                return self._to_safe_tool_content(None, error=f"{__tool_name} failed after retries")

            _wrapped.__name__ = tool_name
            _wrapped.__qualname__ = tool_name
            _wrapped.__doc__ = inspect.getdoc(tool_fn) or f"Execute `{tool_name}` tool."
            _wrapped.__signature__ = signature
            try:
                hints = get_type_hints(tool_fn)
            except Exception:
                hints = {}
            if hints:
                _wrapped.__annotations__ = dict(hints)
            wrapped.append(_wrapped)
        return wrapped

    def _build_runtime_prompt(self) -> str:
        strict_react = self._parse_bool(self.tool_states.get("strict_react"), default=True)
        loop_hint = (
            "Strict ReAct policy: Think -> Act (only 1 tool action per iteration) -> Observe -> Think."
            if strict_react
            else "ReAct policy: Think -> Act -> Observe. Keep loops concise and evidence-driven."
        )
        plan_hint = "Planning policy: AI writes the plan first, then executes via looped Think-Act-Observe."
        compact = self._is_compact_profile()
        profile_hint = "Token profile: compact toolset." if compact else "Token profile: full toolset."
        return (
            "You are Osmo, a derivatives-only trading assistant.\n"
            "Core constraints:\n"
            "- Perpetual derivatives only, never suggest spot trades.\n"
            "- Evidence-first: only use values from tool outputs.\n"
            "- RAG snippets are framework guidance, not live market facts.\n"
            "- If required data is missing/failed, lower confidence and avoid precise entry/SL/TP.\n"
            "- Keep response concise and structured per symbol: Bias, Evidence, Confidence, Data gaps.\n"
            "- End with clear next action and risk control.\n\n"
            "Runtime policy (Deep Agents):\n"
            f"- {plan_hint}\n"
            f"- {loop_hint}\n"
            f"- {profile_hint}\n"
            "- When a tool fails, reason briefly about failure, then retry only if retry is likely useful.\n"
            "- Never batch-execute many tools blindly; prioritize sequential evidence checks.\n"
            "- Do not call the same tool with identical arguments more than once unless prior output was unusable.\n"
            "- For market-analysis requests, call at least one live evidence tool before final answer.\n"
        )

    def _normalize_detected_symbol(self, raw: str) -> Optional[str]:
        value = str(raw or "").strip().upper().replace("_", "-").replace("/", "-")
        if not value:
            return None
        if "-" in value:
            base, quote = value.split("-", 1)
            if not base or not quote:
                return None
            return f"{base}-{quote}"
        if value.endswith("USDT") and len(value) > 4:
            return f"{value[:-4]}-USD"
        if value.endswith("USD") and len(value) > 3:
            return f"{value[:-3]}-USD"
        if value.isalpha() and 2 <= len(value) <= 6:
            return f"{value}-USD"
        return None

    def _infer_asset_type(self, symbol: str) -> str:
        pair = str(symbol or "").upper().strip()
        if "-" not in pair:
            return "crypto"
        base, quote = pair.split("-", 1)
        if base in self._CRYPTO_BASES and quote in {"USD", "USDT"}:
            return "crypto"
        if quote in {"USD", "USDT"}:
            return "crypto" if base in self._CRYPTO_BASES else "rwa"
        return "rwa"

    def _extract_symbols(self, user_message: str) -> List[str]:
        text = str(user_message or "").upper().replace("_", "-")
        found: List[str] = []

        pair_pattern = re.compile(r"\b([A-Z]{2,6})[/-]([A-Z]{2,6})\b")
        for base, quote in pair_pattern.findall(text):
            symbol = self._normalize_detected_symbol(f"{base}-{quote}")
            if symbol and symbol not in found:
                found.append(symbol)

        if not found:
            token_pattern = re.compile(r"\b(BTC|ETH|SOL|ARB|ARK|BERA|BNB|XRP|DOGE|ADA|AVAX|LINK|SUI|APT|OP)\b")
            for token in token_pattern.findall(text):
                symbol = self._normalize_detected_symbol(f"{token}-USD")
                if symbol and symbol not in found:
                    found.append(symbol)

        return found[:4]

    def _requires_market_evidence(self, user_message: str) -> bool:
        text = str(user_message or "").lower()
        if any(keyword in text for keyword in self._MARKET_EVIDENCE_KEYWORDS):
            return True
        return bool(self._extract_symbols(user_message))

    def _should_bootstrap_prefetch(self) -> bool:
        """
        Bootstrap prefetch is optional.
        Default OFF to preserve strict Think->Act->Observe behavior.
        """
        raw = self.tool_states.get("bootstrap_prefetch")
        if raw is None:
            return False
        return self._parse_bool(raw, default=False)

    def _build_bootstrap_calls(self, user_message: str) -> List[ToolCall]:
        calls: List[ToolCall] = []
        symbols = self._extract_symbols(user_message)
        for symbol in symbols[:3]:
            asset_type = self._infer_asset_type(symbol)
            calls.append(
                ToolCall(
                    name="get_price",
                    args={"symbol": symbol, "asset_type": asset_type},
                    reason="Bootstrap evidence: fetch baseline live price.",
                )
            )
            if asset_type == "crypto":
                calls.append(
                    ToolCall(
                        name="get_technical_analysis",
                        args={"symbol": symbol, "timeframe": "1D", "asset_type": asset_type},
                        reason="Bootstrap evidence: fetch baseline 1D technical context.",
                    )
                )

        if self._parse_bool(self.tool_states.get("knowledge_enabled"), default=True):
            top_k = self.tool_states.get("knowledge_top_k", 3) or 3
            category = self.tool_states.get("knowledge_category")
            kb_args: Dict[str, Any] = {"query": str(user_message or ""), "top_k": int(top_k)}
            if category:
                kb_args["category"] = str(category)
            calls.append(
                ToolCall(
                    name="search_knowledge_base",
                    args=kb_args,
                    reason="Bootstrap evidence: retrieve framework guidance from KB.",
                )
            )
        return calls[:8]

    async def _run_bootstrap_calls(self, calls: List[ToolCall]) -> None:
        if not calls:
            return
        max_attempts = self._max_tool_attempts()
        for call in calls:
            if self._max_tool_actions is not None and len(self._captured_results) >= self._max_tool_actions:
                self._phase(
                    "tool_budget_reached",
                    {
                        "tool": call.name,
                        "stage": "guard",
                        "max_tool_actions": self._max_tool_actions,
                    },
                )
                break

            cache_key = self._tool_call_cache_key(call.name, call.args)
            cached = self._tool_result_cache.get(cache_key)
            if cached is not None:
                self._tool_cache_hits += 1
                self._captured_results.append(cached)
                self._phase(
                    "tool_cache_hit",
                    {"tool": call.name, "stage": "observe", "ok": bool(cached.ok)},
                )
                continue

            attempt = 0
            final_result: Optional[ToolResult] = None
            while attempt < max_attempts:
                attempt += 1
                self._phase(
                    "tool_call",
                    {"tool": call.name, "stage": "act", "attempt": attempt, "max_attempts": max_attempts},
                )
                result = await self._orchestrator.run_tool(call, tool_states=self.tool_states)
                final_result = result
                self._captured_results.append(result)
                self._phase(
                    "tool_observe",
                    {
                        "tool": call.name,
                        "stage": "observe",
                        "attempt": attempt,
                        "ok": bool(result.ok),
                        "error": result.error if not result.ok else None,
                    },
                )
                has_data_error = isinstance(result.data, dict) and bool(result.data.get("error"))
                if result.ok and not has_data_error:
                    self._tool_result_cache[cache_key] = result
                    break
                if self._is_connectivity_error(result.error):
                    break
                if attempt >= max_attempts or not self._is_retryable_error(result.error):
                    break

            if final_result and final_result.ok and not (isinstance(final_result.data, dict) and final_result.data.get("error")):
                self._tool_result_cache[cache_key] = final_result

    def _build_bootstrap_context(self) -> str:
        if not self._captured_results:
            return ""
        lines: List[str] = []
        for item in self._captured_results[-8:]:
            name = item.name or "tool"
            if item.ok and not (isinstance(item.data, dict) and item.data.get("error")):
                if isinstance(item.data, dict):
                    if "price" in item.data and "symbol" in item.data:
                        lines.append(f"- {name}: {item.data.get('symbol')} price={item.data.get('price')}")
                    elif "summary" in item.data:
                        lines.append(f"- {name}: summary available")
                    elif "results" in item.data:
                        count = len(item.data.get("results") or [])
                        lines.append(f"- {name}: knowledge results={count}")
                    else:
                        lines.append(f"- {name}: ok")
                else:
                    lines.append(f"- {name}: ok")
            else:
                err = item.error or (item.data.get("error") if isinstance(item.data, dict) else "failed")
                lines.append(f"- {name}: failed ({err})")
        if not lines:
            return ""
        return "Bootstrap tool observations:\n" + "\n".join(lines[:10])

    def _all_bootstrap_failed_due_connectivity(self) -> bool:
        if not self._captured_results:
            return False
        any_ok = any(item.ok and not (isinstance(item.data, dict) and item.data.get("error")) for item in self._captured_results)
        if any_ok:
            return False
        return all(self._is_connectivity_error(item.error) for item in self._captured_results)

    def _build_connectivity_fallback_content(self, user_message: str) -> str:
        symbols = self._extract_symbols(user_message)
        if not symbols:
            symbols = ["Requested symbol(s)"]
        sections: List[str] = []
        for symbol in symbols[:4]:
            sections.append(
                (
                    f"### {symbol}\\n"
                    "- Bias: Neutral (data unavailable).\\n"
                    "- Evidence: Live connector unreachable; no validated price/technical snapshot.\\n"
                    "- Confidence: 15/100.\\n"
                    "- Data gaps: price, technicals, and contextual confirmations unavailable."
                )
            )
        section_text = "\\n\\n".join(sections)
        return (
            "Live market connectors are currently unreachable, so this is a safety fallback.\\n\\n"
            f"{section_text}\\n\\n"
            "Risk plan: hold or reduce exposure, avoid new precise entry/SL/TP until data pipeline recovers, "
            "and cap per-trade risk <= 1.5%."
        )

    def _attachments_as_text(self, user_message: str, attachments: Optional[List[Dict[str, Any]]]) -> str:
        if not attachments:
            return user_message
        max_inline_chars = 8000
        lines: List[str] = []
        for item in attachments:
            name = item.get("name") or "attachment"
            mime = item.get("type") or "application/octet-stream"
            data = item.get("data") or item.get("data_url") or ""
            line = f"- {name} ({mime})"
            if data:
                line += f"\n  base64 (truncated): {str(data)[:max_inline_chars]}"
            lines.append(line)
        header = "Attachments:\n" + "\n".join(lines)
        return f"{user_message}\n\n{header}" if user_message else header

    def _sanitize_history(self, history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in history or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            if role not in {"system", "user", "assistant"}:
                continue
            content = item.get("content", "")
            if content is None:
                content = ""
            out.append({"role": role, "content": content})
        return out

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
                        continue
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    parts.append(str(text))
                else:
                    parts.append(str(item))
            return "\n".join(x for x in parts if x)
        return str(content or "")

    def _extract_last_ai(self, result: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        messages = result.get("messages") if isinstance(result, dict) else None
        usage: Dict[str, Any] = {}
        if isinstance(messages, list):
            for message in reversed(messages):
                msg_type = str(getattr(message, "type", "")).lower()
                if msg_type not in {"ai", "assistant"} and "ai" not in message.__class__.__name__.lower():
                    continue
                usage = (
                    getattr(message, "usage_metadata", None)
                    or getattr(message, "response_metadata", {}).get("token_usage", {})
                    or getattr(message, "response_metadata", {}).get("usage", {})
                    or {}
                )
                return self._content_to_text(getattr(message, "content", "")), usage
        return self._content_to_text(result), usage

    def _extract_tag_block(self, text: str, tag: str) -> tuple[Optional[str], str]:
        pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
        match = pattern.search(text)
        if not match:
            return None, text
        inner = match.group(1).strip()
        cleaned = (text[:match.start()] + text[match.end():]).strip()
        return inner, cleaned

    def _strip_tags(self, text: str) -> str:
        tags = [
            "<final>", "</final>",
            "<reasoning>", "</reasoning>",
            "<reasoning_summary>", "</reasoning_summary>",
            "<summary>", "</summary>",
        ]
        out = text
        for tag in tags:
            out = out.replace(tag, "")
        return out.strip()

    def _parse_reasoning_lines(self, text: Optional[str]) -> List[str]:
        if not text:
            return []
        lines: List[str] = []
        for raw in str(text).splitlines():
            line = raw.strip()
            if not line:
                continue
            line = re.sub(r"^[-*]\s+", "", line)
            lines.append(line)
        return lines

    def _fallback_thoughts(self) -> List[str]:
        total = len(self._captured_results)
        ok = sum(1 for item in self._captured_results if item.ok)
        failed = max(0, total - ok)
        thoughts: List[str] = []
        if total > 0:
            unique_tools = sorted({item.name for item in self._captured_results if item.name})
            thoughts.append(
                f"Executed {total} external tool action(s): {ok} success, {failed} failed "
                f"across {len(unique_tools)} tool type(s)."
            )
            if self._tool_cache_hits > 0:
                thoughts.append(f"Avoided duplicate executions via cache: {self._tool_cache_hits} cache hit(s).")
        if failed > 0:
            failed_names = sorted({item.name for item in self._captured_results if not item.ok and item.name})
            if failed_names:
                thoughts.append(
                    "Failures observed on: " + ", ".join(failed_names[:4]) + "; confidence reduced for affected symbols."
                )
            else:
                thoughts.append("Tool failures were observed; confidence should be reduced.")
        if total == 0:
            thoughts.append("No external tools executed; answer may be less grounded.")
        return thoughts[:4]

    def _build_timeout_fallback_content(self, user_message: str = "") -> str:
        summaries: List[str] = []
        symbol_price: Dict[str, Any] = {}
        for item in self._captured_results[-10:]:
            if item.ok and isinstance(item.data, dict):
                if "symbol" in item.data and "price" in item.data:
                    sym = str(item.data.get("symbol") or "").strip().upper()
                    if sym:
                        symbol_price[sym] = item.data.get("price")
                    summaries.append(f"- {item.data.get('symbol')}: price={item.data.get('price')}")
                elif "summary" in item.data:
                    summaries.append("- Technical summary available.")
                elif "results" in item.data:
                    count = len(item.data.get("results") or [])
                    summaries.append(f"- Knowledge results retrieved: {count}.")
            elif not item.ok:
                summaries.append(f"- {item.name}: failed ({item.error or 'unknown error'})")

        requested_symbols = self._extract_symbols(user_message)[:4]
        per_symbol_sections: List[str] = []
        for symbol in requested_symbols:
            price = symbol_price.get(symbol)
            base_conf = 30 if price is not None else 20
            price_line = f"latest price observed={price}" if price is not None else "latest price not confirmed"
            per_symbol_sections.append(
                (
                    f"### {symbol}\n"
                    f"- Evidence: {price_line}; technical/orderflow/news incomplete.\n"
                    f"- 24h scenario tree (fallback): Bull 33% | Base 34% | Bear 33%.\n"
                    f"- 7d scenario tree (fallback): Bull 33% | Base 34% | Bear 33%.\n"
                    f"- confidence={base_conf}/100.\n"
                    "- Invalidation logic: if new live evidence disagrees (trend, funding, orderbook, or news), "
                    "discard this fallback and recompute from fresh data."
                )
            )

        evidence_block = "\n".join(summaries[:8]) if summaries else "- Live model response timed out before synthesis."
        symbol_block = (
            "\n\n".join(per_symbol_sections)
            if per_symbol_sections
            else "### Requested symbols\n- Not confidently synthesized due to timeout before evidence completion."
        )
        return (
            "Model response timed out before full synthesis. "
            "Returning structured fallback with explicit data gaps.\n\n"
            "## Evidence Collected\n"
            f"{evidence_block}\n\n"
            "## Per-Symbol Fallback\n"
            f"{symbol_block}\n\n"
            "## Conditional Hedge Plan (Fallback)\n"
            "- Hedge only after fresh confirmation (price + technicals + context tools).\n"
            "- Per-trade risk cap <= 1.5% equity; total concurrent risk <= 3%.\n"
            "- Reduce size or stay flat when evidence remains conflicting or incomplete.\n"
            "- Do not force precise entry/SL/TP levels until the full tool loop completes."
        )

    async def run_chat(
        self,
        *,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not self.is_available():
            raise RuntimeError("deepagents package is not available in this environment.")

        self._captured_results = []
        self._phases = []
        self._tool_result_cache = {}
        self._tool_cache_hits = 0
        self._write_txn_id = None
        self._phase("engine_start", {"engine": "deepagents"})

        wrapped_tools = self._build_wrapped_tools(user_message=user_message)
        self._phase("tool_registry_ready", {"tool_count": len(wrapped_tools)})
        has_write_tools = any(name in self._WRITE_TOOL_NAMES for name in self._select_tool_names(user_message=user_message))
        if has_write_tools and self._parse_bool(self.tool_states.get("write"), default=False):
            self._write_txn_id = uuid.uuid4().hex
            self._phase("write_txn_start", {"write_txn_id": self._write_txn_id})

        if self._requires_market_evidence(user_message) and self._should_bootstrap_prefetch():
            bootstrap_calls = self._build_bootstrap_calls(user_message)
            await self._run_bootstrap_calls(bootstrap_calls)
            if self._all_bootstrap_failed_due_connectivity():
                self._phase(
                    "bootstrap_unavailable",
                    {"reason": "connectivity_error", "tool_results": len(self._captured_results)},
                )
                raw_content = (
                    "<final>\n"
                    f"{self._build_connectivity_fallback_content(user_message)}\n"
                    "</final>\n"
                    "<reasoning>\n"
                    "- Bootstrap tools failed due to connectivity errors.\n"
                    "- Skipped model synthesis to avoid hallucinated market specifics.\n"
                    "</reasoning>"
                )
                final_block, after_final = self._extract_tag_block(raw_content, "final")
                reasoning_block, after_reasoning = self._extract_tag_block(after_final, "reasoning")
                content = final_block if final_block is not None else (after_reasoning or raw_content)
                content = self._strip_tags(content)
                thoughts = self._parse_reasoning_lines(reasoning_block)
                self._phase("engine_done", {"engine": "deepagents", "tool_results": len(self._captured_results)})
                return {
                    "content": content,
                    "usage": {},
                    "thoughts": thoughts or self._fallback_thoughts(),
                    "runtime": {
                        "engine": "deepagents",
                        "plan": None,
                        "tool_results": [asdict(item) for item in self._captured_results],
                        "phases": list(self._phases),
                    },
                }
        elif self._requires_market_evidence(user_message):
            self._phase("bootstrap_prefetch_skipped", {"reason": "disabled"})

        agent = create_deep_agent(
            model=self.llm,
            tools=wrapped_tools,
            system_prompt=self._build_runtime_prompt(),
        )

        messages = self._sanitize_history(history)
        bootstrap_context = self._build_bootstrap_context()
        if bootstrap_context:
            messages.append({"role": "system", "content": bootstrap_context})
        messages.append(
            {
                "role": "user",
                "content": self._attachments_as_text(user_message, attachments),
            }
        )

        try:
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": messages}),
                timeout=self._model_timeout_sec,
            )
            raw_content, usage = self._extract_last_ai(result if isinstance(result, dict) else {"messages": []})
        except asyncio.TimeoutError:
            self._phase(
                "engine_timeout",
                {"engine": "deepagents", "timeout_sec": self._model_timeout_sec},
            )
            raw_content = (
                "<final>\n"
                f"{self._build_timeout_fallback_content(user_message=user_message)}\n"
                "</final>\n"
                "<reasoning>\n"
                "- Model timed out during synthesis.\n"
                "- Returned evidence-safe fallback with explicit data gaps.\n"
                "</reasoning>"
            )
            usage = {}

        final_block, after_final = self._extract_tag_block(raw_content, "final")
        reasoning_block, after_reasoning = self._extract_tag_block(after_final, "reasoning")
        if not reasoning_block:
            reasoning_block, after_reasoning = self._extract_tag_block(after_reasoning, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, after_reasoning = self._extract_tag_block(after_reasoning, "summary")

        content = final_block if final_block is not None else (after_reasoning or raw_content)
        content = self._strip_tags(content)
        thoughts = self._parse_reasoning_lines(reasoning_block)
        if not thoughts:
            thoughts = self._fallback_thoughts()

        self._phase(
            "engine_done",
            {"engine": "deepagents", "tool_results": len(self._captured_results)},
        )

        return {
            "content": content,
            "usage": usage or {},
            "thoughts": thoughts,
            "runtime": {
                "engine": "deepagents",
                "plan": None,
                "tool_results": [asdict(item) for item in self._captured_results],
                "phases": list(self._phases),
            },
        }
