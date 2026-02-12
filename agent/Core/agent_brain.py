"""
Agent Brain
Core logic for the Osmo AI Agent.
Handles model routing, prompt preparation, and execution.
"""

from dataclasses import asdict
from typing import List, Dict, Any, Optional, Tuple
import json
import re
import asyncio
from langchain_core.messages import AIMessage
from .llm_factory import LLMFactory
from .response_cache import TTLCache
try:
    from .deepagents_runtime import DeepAgentsRuntime
except Exception:  # pragma: no cover - optional dependency at runtime
    DeepAgentsRuntime = None
from ..Orchestrator.runtime import AgenticTradingRuntime
from ..Schema.agent_runtime import ToolResult
from ..Tools.data.knowledge import search_knowledge_base
try:
    from ..Tools.data.memory import add_memory_messages
except Exception:
    from backend.agent.Tools.data.memory import add_memory_messages

class AgentBrain:
    """The central intelligence unit for Osmo."""

    _ALLOWED_HISTORY_ROLES = {"system", "user", "assistant"}
    _TOOL_CHOICE_CONFLICT_MARKERS = (
        "tool choice is none, but model called a tool",
        "tool_choice is none, but model called a tool",
    )
    _NO_TOOL_RETRY_SYSTEM_NOTE = (
        "STRICT OUTPUT MODE: Do not call tools or functions. "
        "Return plain text only using the required <final>/<reasoning> tags."
    )
    _DATA_GAP_CRITICAL_TOOLS = {
        "get_technical_analysis",
        "get_indicators",
        "search_news",
        "search_sentiment",
    }
    _CONFLICT_FALLBACK_CONTENT = (
        "<final>\n"
        "I hit a temporary tool-routing mismatch while generating this answer. "
        "Please retry once; if it repeats, keep plan mode on and strict ReAct enabled so I can proceed step-by-step.\n"
        "</final>\n"
        "<reasoning>\n"
        "- Tool call mode conflicted with no-tool response mode.\n"
        "- Returned safe fallback instead of surfacing provider error.\n"
        "</reasoning>"
    )
    
    def __init__(
        self,
        model_id: str = "anthropic/claude-3.5-sonnet",
        reasoning_effort: Optional[str] = None,
        tool_states: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
    ):
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.tool_states = tool_states or {}
        self.user_context = user_context or {}
        self.runtime = AgenticTradingRuntime()
        self.llm = LLMFactory.get_llm(model_id, reasoning_effort=reasoning_effort)
        self.system_prompt = LLMFactory.get_system_prompt(
            model_id,
            reasoning_effort=reasoning_effort,
            tool_states=tool_states
        )
        self._prompt_cache = TTLCache(ttl_seconds=900, max_items=64)
        self._response_cache = TTLCache(ttl_seconds=600, max_items=128)
        self._provider_fallback_model_id: Optional[str] = None
        self.agent_engine = self._resolve_agent_engine(self.tool_states)
        self.agent_engine_strict = self._resolve_agent_engine_strict(self.tool_states)

    def _supports_multimodal(self) -> bool:
        model = (self.model_id or "").lower()
        multimodal_keywords = (
            "gpt-4o", "gpt-4.1", "gpt-4v", "vision",
            "claude", "gemini", "llava", "qwen-vl", "pixtral",
            "grok-vision", "grok-2-vision"
        )
        return any(k in model for k in multimodal_keywords)

    def _cache_key(self, prefix: str, *parts: str) -> str:
        joined = "|".join(p.strip() for p in parts if p is not None)
        return f"{prefix}:{joined}"

    def _get_cached_prompt(self) -> Optional[str]:
        key = self._cache_key("system_prompt", self.model_id, str(self.reasoning_effort or ""))
        return self._prompt_cache.get(key)

    def _set_cached_prompt(self, value: str) -> None:
        key = self._cache_key("system_prompt", self.model_id, str(self.reasoning_effort or ""))
        self._prompt_cache.set(key, value)

    def _is_predictable_query(self, user_message: str) -> bool:
        text = str(user_message or "").strip().lower()
        return text in {"hi", "hello", "gm", "help"}

    def _cache_response_get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._response_cache.get(key)

    def _cache_response_set(self, key: str, payload: Dict[str, Any]) -> None:
        self._response_cache.set(key, payload)

    def _predictable_response_cache_key(self, user_message: str, tool_states: Dict[str, Any]) -> str:
        market = str(
            tool_states.get("market_symbol")
            or tool_states.get("market")
            or tool_states.get("market_display")
            or ""
        ).strip().upper()
        timeframe = str(tool_states.get("timeframe") or "").strip().upper()
        return self._cache_key(
            "predictable_response",
            self.model_id,
            self._runtime_model_provider(),
            str(user_message or "").strip().lower(),
            market,
            timeframe,
        )

    def _runtime_model_provider(self) -> str:
        return "openrouter"

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

    def _resolve_memory_user_id(self) -> Optional[str]:
        explicit = (
            self.tool_states.get("memory_user_id")
            or self.user_context.get("memory_user_id")
            or self.user_context.get("user_address")
            or self.user_context.get("user_id")
        )
        if explicit is None:
            return None
        value = str(explicit).strip()
        return value or None

    def _resolve_memory_top_k(self) -> int:
        try:
            value = int(self.tool_states.get("memory_top_k", 5) or 5)
        except Exception:
            value = 5
        return max(1, min(value, 12))

    def _is_memory_enabled(self) -> bool:
        return self._parse_bool(self.tool_states.get("memory_enabled"), default=False)

    def _resolve_knowledge_top_k(self) -> int:
        try:
            value = int(self.tool_states.get("knowledge_top_k", 4) or 4)
        except Exception:
            value = 4
        return max(1, min(value, 8))

    def _resolve_knowledge_category(self) -> Optional[str]:
        raw = self.tool_states.get("knowledge_category")
        if raw is None:
            return None
        value = str(raw).strip().lower()
        if value in {"identity", "drawing", "trade", "market", "psychology", "user", "experience"}:
            return value
        return None

    def _is_knowledge_enabled(self) -> bool:
        return self._parse_bool(self.tool_states.get("knowledge_enabled"), default=True)

    def _analysis_intent(self, user_message: str) -> bool:
        text = str(user_message or "").lower()
        return any(
            term in text
            for term in (
                "analysis", "analyze", "setup", "trend", "risk", "market",
                "indicator", "rsi", "macd", "support", "resistance", "entry",
            )
        )

    def _content_low_confidence(self, content: str) -> bool:
        text = str(content or "").lower()
        markers = (
            "data gap",
            "data unavailable",
            "unable to",
            "not enough data",
            "missing evidence",
            "need confirmation",
            "cannot confirm",
            "partial evidence",
            "partial snapshot",
            "timed out",
            "fallback",
            "not completed",
        )
        return any(m in text for m in markers)

    def _extract_confidence_score(self, content: str) -> Optional[float]:
        text = str(content or "")
        ratio_match = re.search(r"confidence\s*[:=]?\s*(\d{1,3})\s*/\s*100", text, re.IGNORECASE)
        if ratio_match:
            try:
                value = float(ratio_match.group(1))
                return max(0.0, min(100.0, value))
            except Exception:
                return None

        pct_match = re.search(r"confidence\s*[:=]?\s*(\d{1,3})\s*%", text, re.IGNORECASE)
        if pct_match:
            try:
                value = float(pct_match.group(1))
                return max(0.0, min(100.0, value))
            except Exception:
                return None

        decimal_match = re.search(r"confidence\s*[:=]?\s*(0(?:\.\d+)?|1(?:\.0+)?)", text, re.IGNORECASE)
        if decimal_match:
            try:
                value = float(decimal_match.group(1)) * 100.0
                return max(0.0, min(100.0, value))
            except Exception:
                return None
        return None

    def _critical_tool_health(self, tool_results: List[Any]) -> Tuple[int, int]:
        critical_total = 0
        critical_ok = 0
        for item in tool_results:
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                ok = bool(item.get("ok"))
            else:
                name = getattr(item, "name", "") or ""
                ok = bool(getattr(item, "ok", False))
            if name not in self._DATA_GAP_CRITICAL_TOOLS:
                continue
            critical_total += 1
            if ok:
                critical_ok += 1
        return critical_ok, critical_total

    def _runtime_tool_results(self, runtime_packet: Dict[str, Any]) -> List[ToolResult]:
        raw = runtime_packet.get("tool_results") or []
        output: List[ToolResult] = []
        if not isinstance(raw, list):
            return output
        for item in raw:
            if isinstance(item, ToolResult):
                output.append(item)
                continue
            if isinstance(item, dict):
                output.append(
                    ToolResult(
                        name=str(item.get("name") or ""),
                        args=item.get("args") if isinstance(item.get("args"), dict) else {},
                        ok=bool(item.get("ok")),
                        data=item.get("data"),
                        error=item.get("error"),
                        latency_ms=int(item.get("latency_ms") or 0),
                    )
                )
        return output

    def _usage_to_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _merge_usage(self, base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        if not extra:
            return merged
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            merged[key] = self._usage_to_int(merged.get(key)) + self._usage_to_int(extra.get(key))
        for key, value in (extra or {}).items():
            if key not in merged:
                merged[key] = value
        return merged

    def _should_rag_fallback(
        self,
        user_message: str,
        content: str,
        runtime_packet: Dict[str, Any],
        tool_states: Dict[str, Any],
    ) -> bool:
        if not self._parse_bool(tool_states.get("knowledge_enabled"), default=True):
            return False
        if str(tool_states.get("rag_mode") or "secondary").strip().lower() not in {"secondary", "fallback"}:
            return False
        if not self._analysis_intent(user_message):
            return False

        tool_results = self._runtime_tool_results(runtime_packet)
        if tool_results and all(not bool(getattr(item, "ok", False)) for item in tool_results):
            return True
        if not tool_results:
            return True

        confidence = self._extract_confidence_score(content)
        if confidence is not None and confidence < 60.0:
            return True

        ok_count = sum(1 for item in tool_results if bool(getattr(item, "ok", False)))
        fail_count = len(tool_results) - ok_count
        if len(tool_results) >= 2 and fail_count > ok_count:
            return True

        critical_ok, critical_total = self._critical_tool_health(tool_results)
        if critical_total > 0 and critical_ok == 0:
            return True

        warnings = runtime_packet.get("warnings") or []
        if warnings:
            warning_text = " ".join(str(item) for item in warnings).lower()
            if any(term in warning_text for term in ("data gap", "missing", "unavailable", "incomplete")):
                return True

        if self._content_low_confidence(content):
            return True
        return False

    async def _run_rag_fallback(self, user_message: str) -> ToolResult:
        try:
            top_k = self._resolve_knowledge_top_k()
            category = self._resolve_knowledge_category()
            result = await search_knowledge_base(
                query=user_message,
                category=category,
                top_k=top_k,
            )
            return ToolResult(
                name="search_knowledge_base",
                args={"query": user_message, "category": category, "top_k": top_k},
                ok=True,
                data=result,
                error=None,
                latency_ms=0,
            )
        except Exception as exc:
            return ToolResult(
                name="search_knowledge_base",
                args={"query": user_message},
                ok=False,
                data={"error": str(exc)},
                error=str(exc),
                latency_ms=0,
            )

    async def _synthesize_with_rag(
        self,
        *,
        user_message: str,
        runtime_context: str,
        rag_result: ToolResult,
        history: Optional[List[Dict[str, Any]]],
        attachments: Optional[List[Dict[str, Any]]],
    ) -> Tuple[str, List[str], Dict[str, Any]]:
        rag_payload = rag_result.data if isinstance(rag_result.data, dict) else {"result": rag_result.data}
        rag_context = json.dumps(rag_payload, ensure_ascii=False, default=str)
        rag_system = (
            "RAG_CONTEXT (secondary knowledge). "
            "Use as framework only. Do not treat as live price evidence.\n"
            f"{rag_context}"
        )

        cached_prompt = self._get_cached_prompt()
        if cached_prompt is None:
            cached_prompt = self.system_prompt
            self._set_cached_prompt(cached_prompt)

        messages = [{"role": "system", "content": cached_prompt}]
        if runtime_context:
            messages.append({"role": "system", "content": runtime_context})
        messages.append({"role": "system", "content": rag_system})
        safe_history = self._sanitize_history(history)
        if safe_history:
            messages.extend(safe_history)
        user_content = user_message
        if attachments:
            user_content = f"{user_message}\n\n[Attachments present; interpret with caution.]"
        messages.append({"role": "user", "content": user_content})

        response = await self._invoke_with_tool_choice_guard(messages)
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
        elif hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {}) or response.response_metadata.get("usage", {})

        raw_content = response.content or ""
        raw_content = await self._maybe_rewrite_for_data_gaps(raw_content, {"tool_results": [rag_result]})

        def extract_tag_block(text: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(text)
            if not match:
                return None, text
            inner = match.group(1).strip()
            cleaned = (text[:match.start()] + text[match.end():]).strip()
            return inner, cleaned

        def strip_tags(text: str) -> str:
            tags = ["<final>", "</final>", "<reasoning>", "</reasoning>", "<reasoning_summary>", "</reasoning_summary>", "<summary>", "</summary>"]
            for t in tags:
                text = text.replace(t, "")
            return text.strip()

        def parse_reasoning_lines(text: Optional[str]) -> List[str]:
            if not text:
                return []
            lines = []
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                lines.append(line)
            return lines

        final_block, after_final = extract_tag_block(raw_content, "final")
        reasoning_block, after_reasoning = extract_tag_block(after_final, "reasoning")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "summary")

        content = final_block if final_block is not None else (after_reasoning or raw_content)
        content = strip_tags(content)
        thoughts = parse_reasoning_lines(reasoning_block)
        if not thoughts:
            thoughts = self._fallback_thoughts_from_runtime({"tool_results": [rag_result]})

        return content, thoughts, usage

    async def _maybe_store_memory_interaction(self, user_message: str, assistant_content: str) -> None:
        if not self._is_memory_enabled():
            return
        user_id = self._resolve_memory_user_id()
        if not user_id:
            return

        user_text = str(user_message or "").strip()
        assistant_text = str(assistant_content or "").strip()
        if not user_text and not assistant_text:
            return

        messages: List[Dict[str, str]] = []
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})

        metadata: Dict[str, Any] = {
            "source": "osmo_agent_chat",
            "model_id": self.model_id,
            "runtime_provider": self._runtime_model_provider(),
        }
        session_id = self.user_context.get("session_id")
        if session_id:
            metadata["session_id"] = session_id

        try:
            await add_memory_messages(user_id=user_id, messages=messages, metadata=metadata)
        except Exception:
            # Best effort only.
            return

    def _build_runtime_tool_states(self) -> Dict[str, Any]:
        state: Dict[str, Any] = dict(self.tool_states or {})
        provider = self._runtime_model_provider()
        state.setdefault("runtime_model_id", self.model_id)
        state.setdefault("runtime_model_provider", provider)
        # Inject user_address for execution tools
        if self.user_context.get("user_address"):
            state["user_address"] = self.user_context.get("user_address")
        state["runtime_flow_mode"] = "sync"
        state["rag_mode"] = "secondary"
        state["agent_engine"] = "deepagents"
        state["agent_engine_strict"] = True
        state.setdefault("planner_source", "ai")
        state.setdefault("planner_model_id", self.model_id)
        state.setdefault("planner_fallback", "none")
        state.setdefault("web_observation_enabled", True)
        state.setdefault("web_observation_mode", "quality")
        state["memory_enabled"] = self._parse_bool(state.get("memory_enabled"), default=False)
        state["knowledge_enabled"] = self._parse_bool(state.get("knowledge_enabled"), default=self._is_knowledge_enabled())
        if state["memory_enabled"]:
            memory_user_id = state.get("memory_user_id") or self._resolve_memory_user_id()
            if memory_user_id:
                state["memory_user_id"] = memory_user_id
            state["memory_top_k"] = self._resolve_memory_top_k()
        if state["knowledge_enabled"]:
            state["knowledge_top_k"] = self._resolve_knowledge_top_k()
            knowledge_category = self._resolve_knowledge_category()
            if knowledge_category:
                state["knowledge_category"] = knowledge_category
        return state

    def _resolve_agent_engine(self, tool_states: Optional[Dict[str, Any]]) -> str:
        return "deepagents"

    def _resolve_agent_engine_strict(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        return True

    def _should_use_deepagents(self) -> bool:
        if self.agent_engine != "deepagents":
            return False
        if DeepAgentsRuntime is None:
            return False
        try:
            return bool(DeepAgentsRuntime.is_available())
        except Exception:
            return False

    async def _chat_via_deepagents(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        attachments: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        if self.agent_engine != "deepagents":
            return None
        if not self._should_use_deepagents():
            raise RuntimeError("Deep Agents engine is required but unavailable.")
        runtime_tool_states = self._build_runtime_tool_states()
        runtime_tool_states["agent_engine"] = "deepagents"
        predictable_cache_key: Optional[str] = None
        if self._is_predictable_query(user_message) and not attachments:
            predictable_cache_key = self._predictable_response_cache_key(user_message, runtime_tool_states)
            cached = self._cache_response_get(predictable_cache_key)
            if isinstance(cached, dict):
                return cached
        runner = DeepAgentsRuntime(
            llm=self.llm,
            system_prompt=self.system_prompt,
            tool_states=runtime_tool_states,
        )
        result = await runner.run_chat(
            user_message=user_message,
            history=history,
            attachments=attachments,
        )
        runtime_packet = result.get("runtime") if isinstance(result, dict) else {}
        if not isinstance(runtime_packet, dict):
            runtime_packet = {}
        runtime_tool_results = self._runtime_tool_results(runtime_packet)
        runtime_packet["tool_results"] = runtime_tool_results

        if self._should_rag_fallback(
            user_message=user_message,
            content=str(result.get("content", "") or ""),
            runtime_packet=runtime_packet,
            tool_states=runtime_tool_states,
        ):
            rag_result = await self._run_rag_fallback(user_message=user_message)
            runtime_tool_results.append(rag_result)
            runtime_packet["tool_results"] = runtime_tool_results
            runtime_packet.setdefault("phases", [])
            if isinstance(runtime_packet.get("phases"), list):
                runtime_packet["phases"].append(
                    {
                        "name": "rag_secondary",
                        "status": "done" if rag_result.ok else "error",
                        "detail": "Secondary RAG fallback triggered after low-confidence primary answer.",
                    }
                )
            if rag_result.ok:
                synthesized_content, synthesized_thoughts, rag_usage = await self._synthesize_with_rag(
                    user_message=user_message,
                    runtime_context=str(runtime_packet.get("runtime_context") or ""),
                    rag_result=rag_result,
                    history=history,
                    attachments=attachments,
                )
                if synthesized_content.strip():
                    result["content"] = synthesized_content
                if synthesized_thoughts:
                    result["thoughts"] = synthesized_thoughts
                result["usage"] = self._merge_usage(
                    result.get("usage") if isinstance(result.get("usage"), dict) else {},
                    rag_usage if isinstance(rag_usage, dict) else {},
                )
            else:
                fallback_note = (
                    " Secondary knowledge lookup failed, so this answer remains based on primary evidence only."
                )
                base_content = str(result.get("content", "") or "")
                if fallback_note.strip() not in base_content:
                    result["content"] = (base_content + fallback_note).strip()

        runtime_packet["tool_results"] = [asdict(item) for item in runtime_tool_results]
        result["runtime"] = runtime_packet
        if predictable_cache_key:
            self._cache_response_set(predictable_cache_key, result)
        try:
            await self._maybe_store_memory_interaction(
                user_message=user_message,
                assistant_content=result.get("content", ""),
            )
            return result
        except Exception:
            # Memory write is best-effort and should not block chat.
            return result

    def _sanitize_history(self, history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if not history:
            return []
        sanitized: List[Dict[str, Any]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            if role not in self._ALLOWED_HISTORY_ROLES:
                continue
            content = item.get("content", "")
            if content is None:
                content = ""
            elif isinstance(content, (dict, tuple, set)):
                content = str(content)
            sanitized.append({"role": role, "content": content})
        return sanitized

    def _is_tool_choice_conflict_error(self, error: Exception) -> bool:
        text = str(error or "").strip().lower()
        if any(marker in text for marker in self._TOOL_CHOICE_CONFLICT_MARKERS):
            return True
        return bool(
            re.search(r"tool[\s_-]*choice[^\n]*none[^\n]*called a tool", text)
            or re.search(r"called a tool[^\n]*tool[\s_-]*choice[^\n]*none", text)
        )

    def _is_rate_limit_error(self, error: Exception) -> bool:
        text = str(error or "").strip().lower()
        markers = (
            "429",
            "rate limit",
            "too many requests",
            "tokens per day",
            "tpd",
            "quota",
            "resource_exhausted",
        )
        return any(marker in text for marker in markers)


    def _build_no_tool_retry_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"role": "system", "content": self._NO_TOOL_RETRY_SYSTEM_NOTE}, *messages]

    def _fallback_thoughts_from_runtime(self, runtime_packet: Dict[str, Any]) -> List[str]:
        tool_results = self._runtime_tool_results(runtime_packet)
        total = len(tool_results)
        ok = sum(1 for item in tool_results if getattr(item, "ok", False))
        failed = max(0, total - ok)
        thoughts: List[str] = []
        if total > 0:
            thoughts.append(f"Executed {total} tool action(s): {ok} success, {failed} failed.")
        if failed > 0:
            thoughts.append("Some evidence is missing due to tool failures; confidence should be reduced.")
        plan = runtime_packet.get("plan")
        if plan is not None:
            intent = getattr(plan, "intent", None)
            if intent:
                thoughts.append(f"Plan intent: {intent}.")
        return thoughts[:4]

    def _collect_failed_data_gaps(self, runtime_packet: Dict[str, Any]) -> tuple[List[str], int]:
        tool_results = self._runtime_tool_results(runtime_packet)
        failed_symbols: List[str] = []
        failed_count = 0
        for item in tool_results:
            name = str(getattr(item, "name", "") or "")
            ok = bool(getattr(item, "ok", False))
            if ok or name not in self._DATA_GAP_CRITICAL_TOOLS:
                continue
            failed_count += 1
            args = getattr(item, "args", {}) or {}
            if isinstance(args, dict):
                sym = args.get("symbol")
                if isinstance(sym, str) and sym.strip() and sym not in failed_symbols:
                    failed_symbols.append(sym.strip())
        return failed_symbols, failed_count

    def _should_rewrite_for_data_gaps(self, content: str, runtime_packet: Dict[str, Any]) -> bool:
        if not content or not content.strip():
            return False
        _, failed_count = self._collect_failed_data_gaps(runtime_packet)
        if failed_count <= 0:
            return False
        has_setup_terms = bool(
            re.search(
                r"\b(entry|stop(?:-loss)?|take[\s-]*profit|tp|sl|invalidation|trigger|close above|close below)\b",
                content,
                re.IGNORECASE,
            )
        )
        has_numbers = bool(re.search(r"\d", content))
        return has_setup_terms and has_numbers

    async def _maybe_rewrite_for_data_gaps(self, raw_content: str, runtime_packet: Dict[str, Any]) -> str:
        if not self._should_rewrite_for_data_gaps(raw_content, runtime_packet):
            return raw_content

        failed_symbols, failed_count = self._collect_failed_data_gaps(runtime_packet)
        symbols_label = ", ".join(failed_symbols) if failed_symbols else "affected symbols"
        revision_prompt = (
            "Rewrite the draft answer to be evidence-safe.\n"
            f"Critical data tools failed ({failed_count}): {symbols_label}.\n"
            "Rules:\n"
            "1) Do not provide precise numeric entry/SL/TP/invalidation for affected symbols.\n"
            "2) Keep guidance conditional and high-level.\n"
            "3) Preserve useful evidence that is actually present.\n"
            "4) Keep concise, codex-like trading style.\n"
            "5) Return exact tags: <final>...</final> and <reasoning>...</reasoning>.\n"
            "6) Reasoning bullets must describe market logic/data gaps, not editing/rewrite process.\n\n"
            "Draft answer:\n"
            f"{raw_content}"
        )
        revision_messages = [
            {
                "role": "system",
                "content": "You are a strict trading-response rewriter. Never add new facts or numbers.",
            },
            {"role": "user", "content": revision_prompt},
        ]
        try:
            revised = await self._invoke_with_tool_choice_guard(revision_messages)
            revised_text = (getattr(revised, "content", None) or "").strip()
            if revised_text:
                return revised_text
        except Exception:
            return raw_content
        return raw_content

    async def _invoke_with_tool_choice_guard(self, messages: List[Dict[str, Any]]):
        try:
            return await self.llm.ainvoke(messages)
        except Exception as error:
            if not self._is_tool_choice_conflict_error(error):
                raise
            retry_messages = self._build_no_tool_retry_messages(messages)
            try:
                return await self.llm.ainvoke(retry_messages)
            except Exception as retry_error:
                if self._is_tool_choice_conflict_error(retry_error):
                    return AIMessage(content=self._CONFLICT_FALLBACK_CONTENT)
                raise

    async def chat(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        DeepAgents-only chat execution path.
        """
        deep_result = await self._chat_via_deepagents(
            user_message=user_message,
            history=history,
            attachments=attachments,
        )
        if deep_result is None:
            raise RuntimeError("Deep Agents runtime returned no result.")
        return deep_result

    async def stream(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None):
        """
        DeepAgents-only stream path.
        """
        progress_phases = (
            ("runtime_start", "Preparing plan and runtime context."),
            ("runtime_wait", "Running tools and composing final answer."),
        )
        progress_idx = 0
        deep_task = asyncio.create_task(
            self._chat_via_deepagents(
                user_message=user_message,
                history=history,
                attachments=attachments,
            )
        )
        try:
            while not deep_task.done():
                if progress_idx < len(progress_phases):
                    name, detail = progress_phases[progress_idx]
                    progress_idx += 1
                    yield {
                        "type": "runtime_phase",
                        "phase": {
                            "name": name,
                            "status": "running",
                            "detail": detail,
                            "meta": {"stage": "think", "synthetic": True},
                        },
                    }
                await asyncio.sleep(0.35)

            deep_result = await deep_task
            if deep_result is None:
                raise RuntimeError("Deep Agents runtime returned no result.")

            runtime = deep_result.get("runtime", {}) or {}
            yield {
                "type": "runtime",
                "runtime": {
                    "plan": runtime.get("plan"),
                    "tool_results": runtime.get("tool_results") or [],
                    "phases": runtime.get("phases") or [],
                },
            }
            for phase in (runtime.get("phases") or []):
                yield {"type": "runtime_phase", "phase": phase}

            content = str(deep_result.get("content", "") or "")
            if content:
                content_len = len(content)
                if content_len > 1800:
                    chunk_size = 180
                elif content_len > 900:
                    chunk_size = 120
                elif content_len > 400:
                    chunk_size = 80
                else:
                    chunk_size = 48
                for i in range(0, content_len, chunk_size):
                    yield {"type": "delta", "content": content[i : i + chunk_size]}
                    await asyncio.sleep(0)

            thoughts = deep_result.get("thoughts", []) or []

            # Inject tool results as structured thoughts for frontend visualization (e.g. HITL cards)
            tool_thoughts = []
            runtime_data = deep_result.get("runtime", {}) or {}
            tool_results = runtime_data.get("tool_results") or []
            for res in tool_results:
                # Safely handle object or dict
                if hasattr(res, "name"):
                    name = res.name
                    data = res.data
                    ok = res.ok
                else:
                    name = res.get("name")
                    data = res.get("data")
                    ok = res.get("ok")

                tool_thoughts.append({
                    "type": "tool",
                    "toolName": name,
                    "title": f"Tool: {name}",
                    "content": f"Executed {name}",
                    "meta": data,
                    "status": "success" if ok else "error"
                })

            all_thoughts = thoughts + tool_thoughts

            if not all_thoughts:
                all_thoughts = self._fallback_thoughts_from_runtime(runtime)

            for item in all_thoughts:
                yield {"type": "thoughts_delta", "thought": item}
                await asyncio.sleep(0)

            if all_thoughts:
                yield {"type": "thoughts", "thoughts": all_thoughts}

            yield {
                "type": "done",
                "content": content,
                "usage": deep_result.get("usage", {}) or {},
                "thoughts": all_thoughts,
            }
        except asyncio.CancelledError:
            if not deep_task.done():
                deep_task.cancel()
            try:
                await deep_task
            except asyncio.CancelledError:
                pass
            raise
        except Exception:
            if not deep_task.done():
                deep_task.cancel()
                try:
                    await deep_task
                except asyncio.CancelledError:
                    pass
            raise
