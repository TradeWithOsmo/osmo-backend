"""
Agent Brain
Core logic for the Osmo AI Agent.
Handles model routing, prompt preparation, and execution.
"""

from dataclasses import asdict
from typing import List, Dict, Any, Optional
import re
from langchain_core.messages import AIMessage
from .llm_factory import LLMFactory
try:
    from .deepagents_runtime import DeepAgentsRuntime
except Exception:  # pragma: no cover - optional dependency at runtime
    DeepAgentsRuntime = None
from ..Orchestrator.runtime import AgenticTradingRuntime
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
        self._groq_key_index = 0
        self.agent_engine = self._resolve_agent_engine(self.tool_states)
        self.agent_engine_strict = self._resolve_agent_engine_strict(self.tool_states)

    def _supports_multimodal(self) -> bool:
        model = (self.model_id or "").lower()
        if model.startswith("groq/"):
            return False
        multimodal_keywords = (
            "gpt-4o", "gpt-4.1", "gpt-4v", "vision",
            "claude", "gemini", "llava", "qwen-vl", "pixtral",
            "grok-vision", "grok-2-vision"
        )
        return any(k in model for k in multimodal_keywords)

    def _runtime_model_provider(self) -> str:
        model = str(self.model_id or "").strip().lower()
        if model.startswith("groq/"):
            return "groq"
        if "/" in model:
            return "openrouter"
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
        state.setdefault("planner_source", "ai")
        state.setdefault("planner_model_id", self.model_id)
        state.setdefault("planner_fallback", "none")
        state.setdefault("web_observation_enabled", provider in {"groq", "openrouter"})
        state.setdefault("web_observation_mode", "speed" if provider == "groq" else "quality")
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
        states = tool_states or {}
        raw = str(states.get("agent_engine") or states.get("runtime_engine") or "legacy").strip().lower()
        if raw in {"deepagents", "deep_agents", "deep-agent", "deep"}:
            return "deepagents"
        return "legacy"

    def _resolve_agent_engine_strict(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        states = tool_states or {}
        raw = states.get("agent_engine_strict")
        if raw is None:
            return self.agent_engine == "deepagents"
        return self._parse_bool(raw, default=self.agent_engine == "deepagents")

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
            if self.agent_engine_strict:
                raise RuntimeError("Deep Agents engine is required but unavailable.")
            return None
        runtime_tool_states = self._build_runtime_tool_states()
        runtime_tool_states["agent_engine"] = "deepagents"
        while True:
            runner = DeepAgentsRuntime(
                llm=self.llm,
                system_prompt=self.system_prompt,
                tool_states=runtime_tool_states,
            )
            try:
                result = await runner.run_chat(
                    user_message=user_message,
                    history=history,
                    attachments=attachments,
                )
                break
            except Exception as deep_error:
                if self._maybe_rotate_to_next_groq_key(deep_error):
                    continue
                if self.agent_engine_strict:
                    raise
                return None
        try:
            await self._maybe_store_memory_interaction(
                user_message=user_message,
                assistant_content=result.get("content", ""),
            )
            return result
        except Exception:
            if self.agent_engine_strict:
                raise
            return None

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

    def _maybe_rotate_to_next_groq_key(self, error: Exception) -> bool:
        model = str(self.model_id or "").strip().lower()
        if not model.startswith("groq/"):
            return False
        if not self._is_rate_limit_error(error):
            return False
        keys = LLMFactory.groq_api_keys()
        if not keys:
            return False
        if self._groq_key_index >= len(keys) - 1:
            return False
        self._groq_key_index += 1
        self.llm = LLMFactory.get_llm(
            self.model_id,
            reasoning_effort=self.reasoning_effort,
            groq_key_index=self._groq_key_index,
        )
        return True

    def _build_no_tool_retry_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"role": "system", "content": self._NO_TOOL_RETRY_SYSTEM_NOTE}, *messages]

    def _fallback_thoughts_from_runtime(self, runtime_packet: Dict[str, Any]) -> List[str]:
        tool_results = runtime_packet.get("tool_results") or []
        if not isinstance(tool_results, list):
            return []
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
        tool_results = runtime_packet.get("tool_results") or []
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
            while self._maybe_rotate_to_next_groq_key(error):
                try:
                    return await self.llm.ainvoke(messages)
                except Exception as switched_error:
                    error = switched_error
            if not self._is_tool_choice_conflict_error(error):
                raise
            retry_messages = self._build_no_tool_retry_messages(messages)
            try:
                return await self.llm.ainvoke(retry_messages)
            except Exception as retry_error:
                if self._is_tool_choice_conflict_error(retry_error):
                    return AIMessage(content=self._CONFLICT_FALLBACK_CONTENT)
                raise

    async def _astream_with_tool_choice_guard(self, messages: List[Dict[str, Any]]):
        yielded_any = False
        try:
            async for chunk in self.llm.astream(messages):
                yielded_any = True
                yield chunk
        except Exception as error:
            while not yielded_any and self._maybe_rotate_to_next_groq_key(error):
                switched_yielded = False
                try:
                    async for switched_chunk in self.llm.astream(messages):
                        switched_yielded = True
                        yield switched_chunk
                    return
                except Exception as rotated_error:
                    if switched_yielded:
                        raise
                    error = rotated_error
            if not self._is_tool_choice_conflict_error(error):
                raise
            retry_messages = self._build_no_tool_retry_messages(messages)
            try:
                retry_response = await self.llm.ainvoke(retry_messages)
                yield retry_response
            except Exception as retry_error:
                if not self._is_tool_choice_conflict_error(retry_error):
                    raise
                yield AIMessage(content=self._CONFLICT_FALLBACK_CONTENT)
        
    async def chat(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Processes a user message and returns the response with metadata.
        """
        deep_result = await self._chat_via_deepagents(
            user_message=user_message,
            history=history,
            attachments=attachments,
        )
        if deep_result is not None:
            return deep_result

        def build_user_content(message: str, files: Optional[List[Dict[str, Any]]], allow_multimodal: bool):
            if not files:
                return message

            MAX_INLINE_CHARS = 8000

            def attachments_as_text() -> str:
                lines = []
                for f in files:
                    name = f.get("name") or "attachment"
                    mime = f.get("type") or "application/octet-stream"
                    data = f.get("data") or f.get("data_url") or ""
                    line = f"- {name} ({mime})"
                    if data:
                        line += f"\n  base64 (truncated): {data[:MAX_INLINE_CHARS]}"
                    lines.append(line)
                header = "Attachments:\n" + "\n".join(lines)
                return f"{message}\n\n{header}" if message else header

            has_image = any((f.get("type") or "").startswith("image/") and (f.get("data") or f.get("data_url")) for f in files)
            if not allow_multimodal or not has_image:
                return attachments_as_text()

            parts: List[Dict[str, Any]] = []
            if message:
                parts.append({"type": "text", "text": message})
            else:
                parts.append({"type": "text", "text": "User attached files."})

            for f in files:
                name = f.get("name") or "attachment"
                mime = f.get("type") or "application/octet-stream"
                data = f.get("data") or f.get("data_url") or ""

                if mime.startswith("image/") and data:
                    parts.append({"type": "image_url", "image_url": {"url": data}})
                else:
                    label = f"[Attachment: {name} ({mime})]"
                    if data:
                        label += f"\nData (base64, truncated): {data[:MAX_INLINE_CHARS]}"
                    parts.append({"type": "text", "text": label})

            return parts
        def extract_tag_block(text: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(text)
            if not match:
                return None, text
            inner = match.group(1).strip()
            cleaned = (text[:match.start()] + text[match.end():]).strip()
            return inner, cleaned

        def strip_tags(text: str) -> str:
            tags = [
                "<final>", "</final>",
                "<reasoning>", "</reasoning>",
                "<reasoning_summary>", "</reasoning_summary>",
                "<summary>", "</summary>"
            ]
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

        runtime_packet: Dict[str, Any] = {"plan": None, "tool_results": [], "runtime_context": ""}
        runtime_tool_states = self._build_runtime_tool_states()
        try:
            runtime_packet = await self.runtime.prepare(
                user_message=user_message,
                history=history,
                tool_states=runtime_tool_states,
                user_context=self.user_context,
            )
        except Exception as runtime_error:
            runtime_packet["runtime_context"] = f"AGENT_RUNTIME_ERROR: {runtime_error}"

        # Prepare messages
        messages = [{"role": "system", "content": self.system_prompt}]
        runtime_context = runtime_packet.get("runtime_context") or ""
        if runtime_context:
            messages.append({"role": "system", "content": runtime_context})

        safe_history = self._sanitize_history(history)
        if safe_history:
            messages.extend(safe_history)

        user_content = build_user_content(user_message, attachments, self._supports_multimodal())
        messages.append({"role": "user", "content": user_content})
        
        # Call LLM
        response = await self._invoke_with_tool_choice_guard(messages)
        
        # Extract metadata if available (handle multiple formats for compatibility)
        usage = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = response.usage_metadata
        elif hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('token_usage', {}) or response.response_metadata.get('usage', {})

        raw_content = response.content or ""
        raw_content = await self._maybe_rewrite_for_data_gaps(raw_content, runtime_packet)
        final_block, after_final = extract_tag_block(raw_content, "final")
        reasoning_block, after_reasoning = extract_tag_block(after_final, "reasoning")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "summary")

        # Fallback: some providers may include reasoning in metadata
        if not reasoning_block and hasattr(response, "additional_kwargs"):
            reasoning_block = response.additional_kwargs.get("reasoning") or response.additional_kwargs.get("reasoning_content")

        content = final_block if final_block is not None else (after_reasoning or raw_content)
        content = strip_tags(content)
        thoughts = parse_reasoning_lines(reasoning_block)
        if not thoughts:
            thoughts = self._fallback_thoughts_from_runtime(runtime_packet)
        await self._maybe_store_memory_interaction(user_message=user_message, assistant_content=content)

        return {
            "content": content,
            "usage": usage,
            "thoughts": thoughts,
            "runtime": {
                "plan": asdict(runtime_packet["plan"]) if runtime_packet.get("plan") else None,
                "tool_results": [asdict(item) for item in (runtime_packet.get("tool_results") or [])],
                "phases": runtime_packet.get("phases") or [],
            }
        }

    async def stream(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None):
        """
        Streams the model response. Yields dict events:
          - {"type": "delta", "content": "..."}
          - {"type": "thoughts", "thoughts": [ ... ]}
          - {"type": "done", "content": "...", "usage": {...}, "thoughts": [...]}
        """
        deep_result = await self._chat_via_deepagents(
            user_message=user_message,
            history=history,
            attachments=attachments,
        )
        if deep_result is not None:
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
                yield {"type": "delta", "content": content}
            thoughts = deep_result.get("thoughts", []) or []
            for item in thoughts:
                yield {"type": "thoughts_delta", "thought": item}
            if thoughts:
                yield {"type": "thoughts", "thoughts": thoughts}
            yield {
                "type": "done",
                "content": content,
                "usage": deep_result.get("usage", {}) or {},
                "thoughts": thoughts,
            }
            return

        def build_user_content(message: str, files: Optional[List[Dict[str, Any]]], allow_multimodal: bool):
            if not files:
                return message

            MAX_INLINE_CHARS = 8000

            def attachments_as_text() -> str:
                lines = []
                for f in files:
                    name = f.get("name") or "attachment"
                    mime = f.get("type") or "application/octet-stream"
                    data = f.get("data") or f.get("data_url") or ""
                    line = f"- {name} ({mime})"
                    if data:
                        line += f"\n  base64 (truncated): {data[:MAX_INLINE_CHARS]}"
                    lines.append(line)
                header = "Attachments:\n" + "\n".join(lines)
                return f"{message}\n\n{header}" if message else header

            has_image = any((f.get("type") or "").startswith("image/") and (f.get("data") or f.get("data_url")) for f in files)
            if not allow_multimodal or not has_image:
                return attachments_as_text()

            parts: List[Dict[str, Any]] = []
            if message:
                parts.append({"type": "text", "text": message})
            else:
                parts.append({"type": "text", "text": "User attached files."})

            for f in files:
                name = f.get("name") or "attachment"
                mime = f.get("type") or "application/octet-stream"
                data = f.get("data") or f.get("data_url") or ""

                if mime.startswith("image/") and data:
                    parts.append({"type": "image_url", "image_url": {"url": data}})
                else:
                    label = f"[Attachment: {name} ({mime})]"
                    if data:
                        label += f"\nData (base64, truncated): {data[:MAX_INLINE_CHARS]}"
                    parts.append({"type": "text", "text": label})

            return parts
        def extract_tag_block(text: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(text)
            if not match:
                return None, text
            inner = match.group(1).strip()
            cleaned = (text[:match.start()] + text[match.end():]).strip()
            return inner, cleaned

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

        runtime_packet: Dict[str, Any] = {"plan": None, "tool_results": [], "runtime_context": ""}
        runtime_tool_states = self._build_runtime_tool_states()
        try:
            runtime_packet = await self.runtime.prepare(
                user_message=user_message,
                history=history,
                tool_states=runtime_tool_states,
                user_context=self.user_context,
            )
        except Exception as runtime_error:
            runtime_packet["runtime_context"] = f"AGENT_RUNTIME_ERROR: {runtime_error}"

        messages = [{"role": "system", "content": self.system_prompt}]
        runtime_context = runtime_packet.get("runtime_context") or ""
        if runtime_context:
            messages.append({"role": "system", "content": runtime_context})
        safe_history = self._sanitize_history(history)
        if safe_history:
            messages.extend(safe_history)
        user_content = build_user_content(user_message, attachments, self._supports_multimodal())
        messages.append({"role": "user", "content": user_content})

        yield {
            "type": "runtime",
            "runtime": {
                "plan": asdict(runtime_packet["plan"]) if runtime_packet.get("plan") else None,
                "tool_results": [asdict(item) for item in (runtime_packet.get("tool_results") or [])],
                "phases": runtime_packet.get("phases") or [],
            },
        }
        for phase in (runtime_packet.get("phases") or []):
            yield {"type": "runtime_phase", "phase": phase}

        TAGS = [
            "<final>", "</final>",
            "<reasoning>", "</reasoning>",
            "<reasoning_summary>", "</reasoning_summary>",
            "<summary>", "</summary>"
        ]
        TAG_SET = {t.lower() for t in TAGS}

        tag_buffer = ""
        in_tag = False
        inside_reasoning = False
        content_buffer = ""
        full_text = ""
        reasoning_meta = ""
        thoughts: List[str] = []
        last_usage = {}
        reason_line_buffer = ""

        async for chunk in self._astream_with_tool_choice_guard(messages):
            if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                last_usage = chunk.usage_metadata
            elif hasattr(chunk, 'response_metadata'):
                last_usage = chunk.response_metadata.get('token_usage', {}) or chunk.response_metadata.get('usage', {}) or last_usage

            # capture reasoning metadata if provided
            if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                reasoning_meta += chunk.additional_kwargs.get("reasoning") or chunk.additional_kwargs.get("reasoning_content") or ""

            piece = getattr(chunk, "content", None) or ""
            if not piece:
                continue

            full_text += piece

            for ch in piece:
                if in_tag:
                    tag_buffer += ch
                    buf_lower = tag_buffer.lower()
                    is_prefix = any(t.startswith(buf_lower) for t in TAG_SET)

                    if ch == ">" and buf_lower in TAG_SET:
                        # handle recognized tag
                        if buf_lower in ("<reasoning>", "<reasoning_summary>", "<summary>"):
                            inside_reasoning = True
                            reason_line_buffer = ""
                        elif buf_lower in ("</reasoning>", "</reasoning_summary>", "</summary>"):
                            inside_reasoning = False
                            if reason_line_buffer.strip():
                                line = reason_line_buffer.strip()
                                line = re.sub(r"^[-*]\s+", "", line)
                                if line:
                                    thoughts.append(line)
                                    yield {"type": "thoughts_delta", "thought": line}
                            reason_line_buffer = ""
                        # ignore <final> tags
                        tag_buffer = ""
                        in_tag = False
                        continue

                    if is_prefix:
                        continue

                    # Not a valid tag prefix, flush buffer as text
                    tail = tag_buffer[-1]
                    flush_text = tag_buffer[:-1]
                    if flush_text:
                        if inside_reasoning:
                            reason_line_buffer += flush_text
                            while "\n" in reason_line_buffer:
                                line, reason_line_buffer = reason_line_buffer.split("\n", 1)
                                line = line.strip()
                                if line:
                                    line = re.sub(r"^[-*]\s+", "", line)
                                    if line:
                                        thoughts.append(line)
                                        yield {"type": "thoughts_delta", "thought": line}
                        else:
                            content_buffer += flush_text
                            yield {"type": "delta", "content": flush_text}
                    tag_buffer = ""
                    in_tag = False
                    if tail == "<":
                        in_tag = True
                        tag_buffer = "<"
                    else:
                        if inside_reasoning:
                            reason_line_buffer += tail
                        else:
                            content_buffer += tail
                            yield {"type": "delta", "content": tail}
                    continue

                if ch == "<":
                    in_tag = True
                    tag_buffer = "<"
                    continue

                if inside_reasoning:
                    reason_line_buffer += ch
                    while "\n" in reason_line_buffer:
                        line, reason_line_buffer = reason_line_buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            line = re.sub(r"^[-*]\s+", "", line)
                            if line:
                                thoughts.append(line)
                                yield {"type": "thoughts_delta", "thought": line}
                else:
                    content_buffer += ch
                    yield {"type": "delta", "content": ch}

        # Flush any pending tag buffer as text
        if in_tag and tag_buffer:
            if inside_reasoning:
                reason_line_buffer += tag_buffer
            else:
                content_buffer += tag_buffer
                yield {"type": "delta", "content": tag_buffer}
            tag_buffer = ""
            in_tag = False

        if inside_reasoning and reason_line_buffer.strip():
            line = reason_line_buffer.strip()
            line = re.sub(r"^[-*]\s+", "", line)
            if line:
                thoughts.append(line)
                yield {"type": "thoughts_delta", "thought": line}

        # Extract reasoning from full text tags or metadata
        reasoning_block, cleaned = extract_tag_block(full_text, "reasoning")
        if not reasoning_block:
            reasoning_block, cleaned = extract_tag_block(cleaned, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, cleaned = extract_tag_block(cleaned, "summary")

        if not reasoning_block and reasoning_meta:
            reasoning_block = reasoning_meta

        # Remove <final> block if present
        _, cleaned = extract_tag_block(cleaned, "final")

        content = content_buffer.strip()

        if not thoughts:
            thoughts = parse_reasoning_lines(reasoning_block)
            if not thoughts:
                thoughts = self._fallback_thoughts_from_runtime(runtime_packet)
            if thoughts:
                for t in thoughts:
                    yield {"type": "thoughts_delta", "thought": t}

        if thoughts:
            yield {"type": "thoughts", "thoughts": thoughts}

        await self._maybe_store_memory_interaction(user_message=user_message, assistant_content=content)
        yield {"type": "done", "content": content, "usage": last_usage, "thoughts": thoughts}
