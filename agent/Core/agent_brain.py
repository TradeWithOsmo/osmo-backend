"""
Agent Brain
Core logic for the Osmo AI Agent.
Handles model routing, prompt preparation, and execution.
"""

from dataclasses import asdict
from typing import Callable, List, Dict, Any, Optional, Tuple
import json
import re
import asyncio
import difflib
from langchain_core.messages import AIMessage
from .llm_factory import LLMFactory
from .response_cache import TTLCache
try:
    from .deepagents_runtime import DeepAgentsRuntime
except Exception:  # pragma: no cover - optional dependency at runtime
    DeepAgentsRuntime = None
from ..Orchestrator.runtime import AgenticTradingRuntime
from ..Orchestrator.human_ops_policy import (
    default_max_tool_actions_for_mode,
    default_tool_retry_attempts_for_mode,
    normalize_recovery_mode,
    normalize_reliability_mode,
)
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
        self._groq_key_index: int = 0
        provider, base_model_id = self._split_runtime_model_id(model_id)
        self._base_model_id: str = base_model_id
        self._effective_model_id: str = model_id
        self._effective_runtime_provider: str = provider

        self.llm = LLMFactory.get_llm(
            self._effective_model_id,
            reasoning_effort=reasoning_effort,
            groq_key_index=self._groq_key_index,
        )
        self.system_prompt = LLMFactory.get_system_prompt(
            self._base_model_id,
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

    def _strip_runtime_context_block(self, user_message: str) -> str:
        text = str(user_message or "")
        if not text:
            return ""
        cleaned = re.sub(
            r"\[RUNTIME_CONTEXT\].*?\[/RUNTIME_CONTEXT\]",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        return cleaned or text.strip()

    def _extract_runtime_context_block(self, user_message: str) -> Tuple[str, str]:
        text = str(user_message or "")
        if not text:
            return "", ""
        pattern = re.compile(r"\[RUNTIME_CONTEXT\].*?\[/RUNTIME_CONTEXT\]", re.IGNORECASE | re.DOTALL)
        match = pattern.search(text)
        if not match:
            return "", text.strip()
        block = match.group(0).strip()
        body = (text[:match.start()] + text[match.end():]).strip()
        return block, body

    def _detect_user_language(self, user_message: str) -> str:
        text = str(user_message or "").strip().lower()
        if not text:
            return "en"

        # Script-level detection first (fast and robust for non-Latin languages).
        if re.search(r"[\u0600-\u06FF]", text):
            return "ar"
        if re.search(r"[\u0900-\u097F]", text):
            return "hi"
        if re.search(r"[\u0400-\u04FF]", text):
            return "ru"
        if re.search(r"[\u3040-\u30FF]", text):
            return "ja"
        if re.search(r"[\uAC00-\uD7AF]", text):
            return "ko"
        if re.search(r"[\u4E00-\u9FFF]", text):
            return "zh"

        # Latin-family heuristic by stopword density.
        language_tokens: Dict[str, Tuple[str, ...]] = {
            "id": ("yang", "dan", "untuk", "tolong", "cek", "ubah", "ganti", "simbol", "indikator", "sekarang", "lalu"),
            "en": ("the", "and", "please", "check", "change", "symbol", "indicator", "current", "then", "what", "why"),
            "es": ("el", "la", "y", "por", "favor", "cambiar", "simbolo", "símbolo", "indicador", "ahora", "luego"),
            "pt": ("o", "a", "e", "por", "favor", "mudar", "simbolo", "símbolo", "indicador", "agora", "depois"),
            "fr": ("le", "la", "et", "s'il", "svp", "changer", "symbole", "indicateur", "maintenant", "ensuite"),
            "de": ("der", "die", "und", "bitte", "ändern", "wechseln", "symbol", "indikator", "jetzt", "dann"),
            "tr": ("ve", "lütfen", "değiştir", "sembol", "gösterge", "şimdi", "sonra"),
        }
        scores: Dict[str, int] = {}
        for lang, tokens in language_tokens.items():
            score = sum(1 for token in tokens if re.search(rf"\b{re.escape(token)}\b", text))
            if score > 0:
                scores[lang] = score
        if not scores:
            return "en"
        return max(scores.items(), key=lambda item: item[1])[0]

    def _fuzzy_correct_command_tokens(self, user_message: str) -> str:
        text = str(user_message or "")
        if not text.strip():
            return ""

        # Pre-map common misspellings observed in user prompts.
        typo_map = {
            "cheked": "check",
            "sekaang": "sekarang",
            "simbo": "symbol",
            "symbo": "symbol",
            "chnage": "change",
            "timefrmae": "timeframe",
            "indikatr": "indicator",
            "indicat0r": "indicator",
            "donde": "done",
            "cencel": "cancel",
            "ordell": "order",
            "stochs": "stoch",
        }

        def _replace_token(match: re.Match[str]) -> str:
            token = match.group(0)
            lower = token.lower()
            if lower in typo_map:
                repl = typo_map[lower]
                return repl.upper() if token.isupper() else repl
            if len(lower) < 4 or not lower.isascii():
                return token
            close = difflib.get_close_matches(lower, self._COMMAND_VOCAB, n=1, cutoff=0.82)
            if not close:
                return token
            repl = close[0]
            if token[0].isupper():
                repl = repl.capitalize()
            return repl

        return re.sub(r"[A-Za-z][A-Za-z0-9_-]{2,}", _replace_token, text)

    def _normalize_command_phrases(self, user_message: str) -> str:
        text = self._fuzzy_correct_command_tokens(user_message)
        if not text.strip():
            return ""

        replacements: List[Tuple[str, str]] = [
            (r"\b(chequear|revisar|comprobar)\b", "check"),
            (r"\bcek(?:kan)?\b", "check"),
            (r"\b(verificar|verifica|vérifier|prüfen)\b", "verify"),
            (r"\b(cambiar|cambia|mudar|changer|wechseln)\b", "change"),
            (r"\bsimbol\b", "symbol"),
            (r"\b(símbolo|simbolo|symbole)\b", "symbol"),
            (r"\bsekarang\b", "current"),
            (r"\b(ahora|agora|maintenant|jetzt)\b", "current"),
            (r"\bubah\b", "change"),
            (r"\bganti\b", "change"),
            (r"\b(agregar|añadir|adicionar|ajouter|hinzufügen)\b", "add"),
            (r"\btambahkan?\b", "add"),
            (r"\bindikator\b", "indicator"),
            (r"\b(indicador|indicateur|indikator)\b", "indicator"),
            (r"\blalu\b", "then"),
            (r"\b(luego|después|depois|ensuite|dann)\b", "then"),
            (r"\bdan\b", "and"),
            (r"\b(y|e|et|und)\b", "and"),
            (r"\b(obtener|obtenir|buscar|pegar|capturar)\b", "get"),
            (r"\b(eliminar|retirer|löschen)\b", "remove"),
            (r"\bwaktu\b", "time"),
            (r"\b(marco temporal|intervalo|periodo|période)\b", "time frame"),
            (r"\bkerangka waktu\b", "time frame"),
            (r"\btf\b", "time frame"),
        ]
        out = text
        for pattern, replacement in replacements:
            out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def _normalize_runtime_input(self, user_message: str) -> Dict[str, Any]:
        context_block, body = self._extract_runtime_context_block(user_message)
        original_message = str(body or "").strip()
        user_language = self._detect_user_language(original_message)
        normalized_body = self._normalize_command_phrases(original_message)
        normalization_applied = normalized_body != original_message

        normalized_message = normalized_body
        if context_block:
            normalized_message = f"{context_block}\n\n{normalized_body}".strip()

        return {
            "original_message": original_message,
            "normalized_body": normalized_body,
            "normalized_message": normalized_message,
            "normalization_applied": normalization_applied,
            "user_language": user_language,
        }

    def _build_response_language_instruction(self, user_language: str) -> str:
        language = str(user_language or "en").strip().lower()
        if language == "en":
            return "Response language policy: answer in English."
        return (
            "Response language policy: answer in the same language as the user's latest message "
            f"(detected={language})."
        )

    def _resolve_model_timeout_sec(self, tool_states: Optional[Dict[str, Any]], default: float = 40.0) -> float:
        raw: Any = None
        if isinstance(tool_states, dict):
            raw = tool_states.get("model_timeout_sec")
        try:
            value = float(raw) if raw is not None else float(default)
        except Exception:
            value = float(default)
        return max(8.0, min(value, 300.0))

    def _summarize_tool_outcomes(self, tool_results: List[ToolResult], limit: int = 3) -> str:
        if not tool_results:
            return "- no tool result"
        lines: List[str] = []
        for item in tool_results[: max(1, int(limit or 1))]:
            name = str(getattr(item, "name", "") or "tool")
            ok = bool(getattr(item, "ok", False))
            if ok:
                lines.append(f"- {name}: ok")
                continue
            error = str(getattr(item, "error", "") or "")
            if not error and isinstance(getattr(item, "data", None), dict):
                error = str((item.data or {}).get("error") or "")
            if error:
                lines.append(f"- {name}: fail ({error[:120]})")
            else:
                lines.append(f"- {name}: fail")
        return "\n".join(lines)

    def _is_predictable_query(self, user_message: str) -> bool:
        text = self._strip_runtime_context_block(user_message).strip().lower()
        if text in {"hi", "hello", "hey", "gm", "hai", "halo", "help"}:
            return True
        # Keep greetings with direct assistant mention on the low-latency path.
        return bool(re.fullmatch(r"(hi+|hello+|hey+|gm+|hai+|halo+)(?:\s+(osmo|assistant|bot|ai|agent))?[!.,\s]*", text))

    def _build_predictable_fast_response(self, user_message: str) -> Dict[str, Any]:
        text = self._strip_runtime_context_block(user_message).strip().lower()
        if text == "help":
            content = (
                "Ready. I can help with market analysis, trade setups, and position management. "
                "Send the pair and timeframe you want to check."
            )
            thought = "Detected quick help intent; answered directly without tool runtime."
        else:
            content = "Hi! I'm online. Which market do you want to check now?"
            thought = "Detected lightweight greeting; skipped tool runtime for lower latency."
        return {
            "content": content,
            "usage": {},
            "thoughts": [thought],
            "runtime": {
                "plan": None,
                "tool_results": [],
                "phases": [
                    {
                        "name": "quick_reply",
                        "status": "done",
                        "detail": "Fast-path response for lightweight greeting/help query.",
                        "meta": {"stage": "plan", "fast_path": True},
                    }
                ],
            },
        }

    def _cache_response_get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._response_cache.get(key)

    def _cache_response_set(self, key: str, payload: Dict[str, Any]) -> None:
        self._response_cache.set(key, payload)

    def _predictable_response_cache_key(self, user_message: str, tool_states: Dict[str, Any]) -> str:
        normalized_message = self._strip_runtime_context_block(user_message).strip().lower()
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
            normalized_message,
            market,
            timeframe,
        )

    def _runtime_model_provider(self) -> str:
        provider = str(getattr(self, "_effective_runtime_provider", "") or "").strip().lower()
        return provider or "openrouter"

    def _split_runtime_model_id(self, model_id: str) -> Tuple[str, str]:
        """
        Supports provider-prefixed IDs like:
        - groq/{model}
        - openrouter/{model}
        - nvidia/{model} (legacy prefix; normalized to openrouter/{model})

        Returns: (runtime_provider, base_model_id)
        """
        raw = str(model_id or "").strip()
        if not raw:
            return "openrouter", raw
        base_id, suffix = (raw.split(":", 1) + [None])[:2]
        if "/" not in base_id:
            return "openrouter", raw
        prefix, remainder = base_id.split("/", 1)
        if prefix in {"groq", "openrouter"} and remainder:
            resolved = remainder + (f":{suffix}" if suffix else "")
            return prefix, resolved
        if prefix == "nvidia" and remainder:
            resolved = remainder + (f":{suffix}" if suffix else "")
            return "openrouter", resolved
        return "openrouter", raw

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

    def _is_smalltalk_query(self, user_message: str) -> bool:
        text = self._strip_runtime_context_block(user_message).strip().lower()
        if not text:
            return False
        if text in {"hi", "hello", "hey", "gm", "hai", "halo", "help"}:
            return True
        if re.fullmatch(r"(hi+|hello+|hey+|gm+|hai+|halo+)(?:\s+(osmo|assistant|bot|ai|agent))?[!.,\s]*", text):
            return True
        return False

    def _analysis_intent(self, user_message: str) -> bool:
        text = self._strip_runtime_context_block(user_message).strip().lower()
        if not text or self._is_smalltalk_query(text):
            return False
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

    def _extract_plan_warning(self, runtime_packet: Dict[str, Any]) -> Optional[str]:
        plan_obj = runtime_packet.get("plan")
        warnings: List[str] = []
        if isinstance(plan_obj, dict):
            raw = plan_obj.get("warnings")
            if isinstance(raw, list):
                warnings = [str(item).strip() for item in raw if str(item).strip()]
        elif hasattr(plan_obj, "warnings"):
            raw = getattr(plan_obj, "warnings", None)
            if isinstance(raw, list):
                warnings = [str(item).strip() for item in raw if str(item).strip()]
        if warnings:
            return warnings[0]

        phases = runtime_packet.get("phases")
        if isinstance(phases, list):
            for item in phases:
                if not isinstance(item, dict):
                    continue
                detail = str(item.get("detail") or "").strip()
                status = str(item.get("status") or "").strip().lower()
                if detail and status in {"error", "warn"}:
                    return detail
        return None

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

    def _extract_usage(self, response: Any) -> Dict[str, Any]:
        usage: Dict[str, Any] = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
        elif hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {}) or response.response_metadata.get("usage", {})
        return usage if isinstance(usage, dict) else {}

    def _parse_tagged_response(self, raw_content: str, runtime_packet: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
        text = str(raw_content or "")

        def extract_tag_block(src: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(src)
            if not match:
                return None, src
            inner = match.group(1).strip()
            cleaned = (src[:match.start()] + src[match.end():]).strip()
            return inner, cleaned

        def strip_tags(src: str) -> str:
            tags = ["<final>", "</final>", "<reasoning>", "</reasoning>", "<reasoning_summary>", "</reasoning_summary>", "<summary>", "</summary>"]
            for t in tags:
                src = src.replace(t, "")
            return src.strip()

        def parse_reasoning_lines(src: Optional[str]) -> List[str]:
            if not src:
                return []
            lines = []
            for raw in src.splitlines():
                line = raw.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                lines.append(line)
            return lines

        final_block, after_final = extract_tag_block(text, "final")
        reasoning_block, after_reasoning = extract_tag_block(after_final, "reasoning")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "summary")

        content = final_block if final_block is not None else (after_reasoning or text)
        content = strip_tags(content)
        thoughts = parse_reasoning_lines(reasoning_block)
        if not thoughts and isinstance(runtime_packet, dict):
            thoughts = self._fallback_thoughts_from_runtime(runtime_packet)
        return content, thoughts

    def _is_tool_execution_request(self, user_message: str) -> bool:
        text = self._strip_runtime_context_block(user_message).strip().lower()
        if not text:
            return False
        markers = (
            "tool",
            "set symbol",
            "change symbol",
            "switch symbol",
            "check symbol",
            "current symbol",
            "symbol now",
            "set timeframe",
            "change timeframe",
            "set time frame",
            "change time frame",
            "add indicator",
            "remove indicator",
            "get indicator",
            "get indicators",
            "active indicators",
            "verify state",
            "verify",
            "focus chart",
            "draw",
            "place order",
            "close position",
            "close all",
            "cancel order",
            "reverse position",
        )
        if any(marker in text for marker in markers):
            return True

        # Command-sequence pattern:
        # e.g. "check current symbol > change time frame to 1m > add indicator rsi > get indicators"
        action_verbs = ("check", "get", "set", "change", "switch", "add", "remove", "verify", "list", "show", "fetch")
        chart_targets = ("symbol", "timeframe", "time frame", "indicator", "chart", "position", "order")
        if any(v in text for v in action_verbs) and any(t in text for t in chart_targets):
            return True
        if ">" in text and sum(1 for v in action_verbs if v in text) >= 2:
            return True
        return False

    async def _chat_via_runtime_prepare_primary(
        self,
        *,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        attachments: Optional[List[Dict[str, Any]]],
        runtime_tool_states: Dict[str, Any],
        original_user_message: Optional[str] = None,
        input_normalization: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        runtime_states: Dict[str, Any] = dict(runtime_tool_states or {})
        reliability_mode = normalize_reliability_mode(runtime_states.get("reliability_mode"))
        write_enabled = self._parse_bool(runtime_states.get("write"), default=False)
        runtime_states["plan_mode"] = True
        runtime_states["strict_react"] = True
        runtime_states["planner_source"] = "system"
        runtime_states["planner_fallback"] = "none"
        runtime_states.setdefault("retry_failed_tools", True)

        default_retry_attempts = default_tool_retry_attempts_for_mode(reliability_mode)
        raw_retry_attempts = (
            runtime_states.get("tool_retry_max_attempts")
            or runtime_states.get("tool_retry_max")
            or default_retry_attempts
        )
        try:
            configured_retry_attempts = int(raw_retry_attempts)
        except Exception:
            configured_retry_attempts = default_retry_attempts
        if write_enabled:
            configured_retry_attempts = max(configured_retry_attempts, default_retry_attempts)
        configured_retry_attempts = max(1, min(configured_retry_attempts, 4))
        runtime_states["tool_retry_max_attempts"] = configured_retry_attempts

        default_budget = default_max_tool_actions_for_mode(reliability_mode)
        raw_budget = (
            runtime_states.get("max_tool_actions")
            or runtime_states.get("max_tool_calls")
            or default_budget
        )
        try:
            configured_budget = int(raw_budget)
        except Exception:
            configured_budget = default_budget
        if write_enabled:
            configured_budget = max(configured_budget, default_budget)
        configured_budget = max(1, min(configured_budget, 16))
        runtime_states["max_tool_actions"] = configured_budget
        runtime_states["max_tool_calls"] = configured_budget
        runtime_states.setdefault("max_react_iterations", int(runtime_states.get("max_tool_calls") or 4))

        runtime_packet = await self.runtime.prepare(
            user_message=user_message,
            history=history,
            tool_states=runtime_states,
            user_context=self.user_context,
        )
        if not isinstance(runtime_packet, dict):
            return None

        runtime_tool_results = self._runtime_tool_results(runtime_packet)
        runtime_packet["tool_results"] = runtime_tool_results
        runtime_context = str(runtime_packet.get("runtime_context") or "")
        normalization = dict(input_normalization or {})
        user_language = str(normalization.get("user_language") or "en").strip().lower()

        if self._is_tool_execution_request(user_message) and not runtime_tool_results:
            plan_hint = self._extract_plan_warning(runtime_packet)
            if user_language == "id":
                content = (
                    "Tidak ada tool yang berhasil dieksekusi pada request ini, jadi saya tidak akan mengklaim hasil aksi chart/order. "
                    "Coba ulang dengan langkah lebih kecil (contoh: set symbol dulu, lalu set timeframe)."
                )
                if plan_hint:
                    content = f"{content}\nPetunjuk planner: {plan_hint}"
            else:
                content = (
                    "No tools were executed for this request, so I will not claim chart/order actions. "
                    "Retry with smaller steps (for example: set symbol first, then set timeframe)."
                )
                if plan_hint:
                    content = f"{content}\nPlanner hint: {plan_hint}"
            runtime_packet.setdefault("phases", [])
            if isinstance(runtime_packet.get("phases"), list):
                runtime_packet["phases"].append(
                    {
                        "name": "runtime_primary",
                        "status": "error",
                        "detail": "Tool execution request produced no tool results.",
                    }
                )
            plan_obj = runtime_packet.get("plan")
            if hasattr(plan_obj, "__dataclass_fields__"):
                runtime_packet["plan"] = asdict(plan_obj)
            runtime_packet["tool_results"] = [asdict(item) for item in runtime_tool_results]
            runtime_packet["input_normalization"] = normalization
            return {
                "content": content,
                "usage": {},
                "thoughts": ["Tool execution requested but no tool result was produced; returned safe non-claim response."],
                "runtime": runtime_packet,
            }

        cached_prompt = self._get_cached_prompt()
        if cached_prompt is None:
            cached_prompt = self.system_prompt
            self._set_cached_prompt(cached_prompt)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": cached_prompt}]
        if runtime_context:
            messages.append({"role": "system", "content": runtime_context})
        messages.append({"role": "system", "content": self._build_response_language_instruction(user_language)})
        if normalization.get("normalization_applied"):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Internal command normalization has been applied before tool planning/execution. "
                        "Use runtime evidence as source-of-truth and do not fabricate tool outputs."
                    ),
                }
            )
        safe_history = self._sanitize_history(history)
        if safe_history:
            messages.extend(safe_history)
        user_content = str(original_user_message or self._strip_runtime_context_block(user_message) or user_message)
        if attachments:
            user_content = f"{user_content}\n\n[Attachments present; interpret with caution.]"
        messages.append({"role": "user", "content": user_content})

        synthesis_timeout_sec = max(
            12.0,
            min(
                self._resolve_model_timeout_sec(runtime_states, default=40.0),
                45.0,
            ),
        )
        try:
            response = await self._invoke_with_tool_choice_guard(
                messages,
                timeout_sec=synthesis_timeout_sec,
            )
        except asyncio.TimeoutError:
            summary_block = self._summarize_tool_outcomes(runtime_tool_results)
            if user_language == "id":
                content = (
                    "Eksekusi tool selesai, tapi tahap penyusunan jawaban timeout. "
                    "Ringkasan hasil tool:\n"
                    f"{summary_block}\n"
                    "Coba ulang dengan prompt lebih singkat atau ulang langkah per langkah."
                )
            else:
                content = (
                    "Tool execution completed, but response synthesis timed out. "
                    "Tool result summary:\n"
                    f"{summary_block}\n"
                    "Retry with a shorter prompt or execute commands step-by-step."
                )
            runtime_packet.setdefault("phases", [])
            if isinstance(runtime_packet.get("phases"), list):
                runtime_packet["phases"].append(
                    {
                        "name": "runtime_primary",
                        "status": "error",
                        "detail": f"Synthesis timeout after {int(synthesis_timeout_sec)}s.",
                    }
                )
            plan_obj = runtime_packet.get("plan")
            if hasattr(plan_obj, "__dataclass_fields__"):
                runtime_packet["plan"] = asdict(plan_obj)
            runtime_packet["tool_results"] = [asdict(item) for item in runtime_tool_results]
            runtime_packet["input_normalization"] = normalization
            return {
                "content": content,
                "usage": {},
                "thoughts": [
                    "Tool execution completed but final synthesis timed out; returned safe summary."
                ],
                "runtime": runtime_packet,
            }
        usage = self._extract_usage(response)
        raw_content = str(getattr(response, "content", "") or "")
        raw_content = await self._maybe_rewrite_for_data_gaps(
            raw_content,
            runtime_packet,
            timeout_sec=min(12.0, max(6.0, synthesis_timeout_sec * 0.35)),
        )
        content, thoughts = self._parse_tagged_response(raw_content, runtime_packet=runtime_packet)
        runtime_packet.setdefault("phases", [])
        if isinstance(runtime_packet.get("phases"), list):
            runtime_packet["phases"].append(
                {
                    "name": "runtime_primary",
                    "status": "done",
                    "detail": "Request routed to deterministic runtime primary path.",
                }
            )

        plan_obj = runtime_packet.get("plan")
        if hasattr(plan_obj, "__dataclass_fields__"):
            runtime_packet["plan"] = asdict(plan_obj)
        runtime_packet["tool_results"] = [asdict(item) for item in runtime_tool_results]
        runtime_packet["input_normalization"] = normalization

        return {
            "content": content,
            "usage": usage or {},
            "thoughts": thoughts,
            "runtime": runtime_packet,
        }

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
        if self._is_smalltalk_query(user_message):
            return False
        if not self._analysis_intent(user_message):
            return False

        tool_results = self._runtime_tool_results(runtime_packet)
        confidence = self._extract_confidence_score(content)
        low_confidence = confidence is not None and confidence < 60.0
        low_confidence_markers = self._content_low_confidence(content)

        if tool_results and all(not bool(getattr(item, "ok", False)) for item in tool_results):
            return True
        if not tool_results:
            # No automatic RAG on empty tool result. Only fallback if answer itself
            # explicitly indicates low-confidence/data-gap.
            return low_confidence or low_confidence_markers

        if low_confidence:
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

        if low_confidence_markers:
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

        synthesis_timeout_sec = max(
            12.0,
            min(self._resolve_model_timeout_sec(self.tool_states, default=40.0), 45.0),
        )
        response = await self._invoke_with_tool_choice_guard(
            messages,
            timeout_sec=synthesis_timeout_sec,
        )
        usage = self._extract_usage(response)
        raw_content = response.content or ""
        raw_content = await self._maybe_rewrite_for_data_gaps(
            raw_content,
            {"tool_results": [rag_result]},
            timeout_sec=min(10.0, max(5.0, synthesis_timeout_sec * 0.3)),
        )
        content, thoughts = self._parse_tagged_response(raw_content, runtime_packet={"tool_results": [rag_result]})
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
        state.setdefault("runtime_model_id", getattr(self, "_base_model_id", self.model_id))
        state.setdefault("runtime_model_provider", provider)
        # Inject user_address for execution tools
        if self.user_context.get("user_address"):
            state["user_address"] = self.user_context.get("user_address")
        state["runtime_flow_mode"] = "sync"
        state["rag_mode"] = "secondary"
        state["agent_engine"] = "deepagents"
        state["agent_engine_strict"] = True
        state["reliability_mode"] = normalize_reliability_mode(state.get("reliability_mode"))
        state["recovery_mode"] = normalize_recovery_mode(state.get("recovery_mode"))
        write_enabled = self._parse_bool(state.get("write"), default=False)
        state.setdefault("planner_source", "ai")
        state.setdefault("planner_model_id", self.model_id)
        state.setdefault("planner_fallback", "none")
        # Performance-safe defaults; frontend can opt in for deeper runs.
        state.setdefault("tool_profile", "compact")
        try:
            default_budget = default_max_tool_actions_for_mode(str(state.get("reliability_mode") or "balanced"))
            default_max_actions = int(state.get("max_tool_actions", default_budget) or default_budget)
        except Exception:
            default_max_actions = default_max_tool_actions_for_mode(str(state.get("reliability_mode") or "balanced"))
        if write_enabled:
            default_max_actions = max(default_max_actions, default_budget)
        default_max_actions = max(1, min(default_max_actions, 16))
        state["max_tool_actions"] = default_max_actions

        existing_max_calls = state.get("max_tool_calls")
        try:
            resolved_max_calls = int(existing_max_calls) if existing_max_calls is not None else default_max_actions
        except Exception:
            resolved_max_calls = default_max_actions
        if write_enabled:
            resolved_max_calls = max(resolved_max_calls, default_max_actions)
        resolved_max_calls = max(1, min(resolved_max_calls, 16))
        state["max_tool_calls"] = resolved_max_calls

        try:
            default_retry_budget = default_tool_retry_attempts_for_mode(str(state.get("reliability_mode") or "balanced"))
            default_retry_max = int(state.get("tool_retry_max", default_retry_budget) or default_retry_budget)
        except Exception:
            default_retry_max = default_tool_retry_attempts_for_mode(str(state.get("reliability_mode") or "balanced"))
        if write_enabled:
            default_retry_max = max(default_retry_max, default_retry_budget)
        default_retry_max = max(1, min(default_retry_max, 4))
        state["tool_retry_max"] = default_retry_max
        raw_retry_attempts = state.get("tool_retry_max_attempts")
        try:
            resolved_retry_attempts = int(raw_retry_attempts) if raw_retry_attempts is not None else default_retry_max
        except Exception:
            resolved_retry_attempts = default_retry_max
        if write_enabled:
            resolved_retry_attempts = max(resolved_retry_attempts, default_retry_max)
        state["tool_retry_max_attempts"] = max(1, min(resolved_retry_attempts, 4))
        state.setdefault("model_timeout_sec", 40)
        state.setdefault("web_observation_enabled", False)
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
        phase_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.agent_engine != "deepagents":
            return None
        if not self._should_use_deepagents():
            raise RuntimeError("Deep Agents engine is required but unavailable.")
        runtime_tool_states = self._build_runtime_tool_states()
        runtime_tool_states["agent_engine"] = "deepagents"
        normalized_input = self._normalize_runtime_input(user_message)
        normalized_message = str(normalized_input.get("normalized_message") or user_message)
        normalized_body = str(
            normalized_input.get("normalized_body")
            or self._strip_runtime_context_block(normalized_message)
            or normalized_message
        ).strip()
        if self._is_predictable_query(user_message) and not attachments:
            predictable_cache_key = self._predictable_response_cache_key(user_message, runtime_tool_states)
            cached = self._cache_response_get(predictable_cache_key)
            if isinstance(cached, dict):
                return cached
            fast_response = self._build_predictable_fast_response(user_message)
            self._cache_response_set(predictable_cache_key, fast_response)
            return fast_response
        if self._is_tool_execution_request(normalized_body):
            return await self._chat_via_runtime_prepare_primary(
                user_message=normalized_body,
                history=history,
                attachments=attachments,
                runtime_tool_states=runtime_tool_states,
                original_user_message=str(normalized_input.get("original_message") or ""),
                input_normalization=normalized_input,
            )

        predictable_cache_key: Optional[str] = None

        async def _run_once() -> Dict[str, Any]:
            try:
                runner = DeepAgentsRuntime(
                    llm=self.llm,
                    system_prompt=self.system_prompt,
                    tool_states=runtime_tool_states,
                    phase_callback=phase_callback,
                )
            except TypeError:
                # Backward compat for patched tests/custom stubs that don't accept phase_callback.
                runner = DeepAgentsRuntime(
                    llm=self.llm,
                    system_prompt=self.system_prompt,
                    tool_states=runtime_tool_states,
                )
            return await runner.run_chat(
                user_message=user_message,
                history=history,
                attachments=attachments,
            )

        try:
            result = await _run_once()
        except Exception as error:
            provider = self._runtime_model_provider()
            # Groq: rotate API key index on rate-limit errors to keep deepagents runtime alive.
            if provider == "groq" and self._is_rate_limit_error(error):
                try:
                    keys = LLMFactory.groq_api_keys()
                except Exception:
                    keys = []

                max_index = len(keys) - 1
                retry_error: Exception = error
                while self._groq_key_index < max_index and self._is_rate_limit_error(retry_error):
                    self._groq_key_index += 1
                    self.llm = LLMFactory.get_llm(
                        self._effective_model_id,
                        reasoning_effort=self.reasoning_effort,
                        groq_key_index=self._groq_key_index,
                    )
                    runtime_tool_states = self._build_runtime_tool_states()
                    runtime_tool_states["agent_engine"] = "deepagents"
                    try:
                        result = await _run_once()
                        break
                    except Exception as err2:
                        retry_error = err2
                        continue
                else:
                    raise retry_error
            else:
                raise
        runtime_packet = result.get("runtime") if isinstance(result, dict) else {}
        if not isinstance(runtime_packet, dict):
            runtime_packet = {}
        runtime_tool_results = self._runtime_tool_results(runtime_packet)
        runtime_packet["tool_results"] = runtime_tool_results
        runtime_packet["input_normalization"] = normalized_input

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

    async def _maybe_rewrite_for_data_gaps(
        self,
        raw_content: str,
        runtime_packet: Dict[str, Any],
        timeout_sec: Optional[float] = None,
    ) -> str:
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
            revised = await self._invoke_with_tool_choice_guard(
                revision_messages,
                timeout_sec=timeout_sec,
            )
            revised_text = (getattr(revised, "content", None) or "").strip()
            if revised_text:
                return revised_text
        except Exception:
            return raw_content
        return raw_content

    async def _invoke_with_tool_choice_guard(
        self,
        messages: List[Dict[str, Any]],
        timeout_sec: Optional[float] = None,
    ):
        async def _ainvoke(payload: List[Dict[str, Any]]):
            if timeout_sec is None:
                return await self.llm.ainvoke(payload)
            try:
                bounded_timeout = float(timeout_sec)
            except Exception:
                bounded_timeout = 30.0
            bounded_timeout = max(5.0, min(bounded_timeout, 180.0))
            return await asyncio.wait_for(
                self.llm.ainvoke(payload),
                timeout=bounded_timeout,
            )

        try:
            return await _ainvoke(messages)
        except Exception as error:
            if not self._is_tool_choice_conflict_error(error):
                raise
            retry_messages = self._build_no_tool_retry_messages(messages)
            try:
                return await _ainvoke(retry_messages)
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
        phase_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        def enqueue_phase(phase: Dict[str, Any]) -> None:
            if not isinstance(phase, dict):
                return
            try:
                phase_queue.put_nowait(dict(phase))
            except Exception:
                return

        def normalize_stream_phase(
            raw_phase: Dict[str, Any],
            *,
            default_status: str,
        ) -> Optional[Dict[str, Any]]:
            if not isinstance(raw_phase, dict):
                return None
            payload = dict(raw_phase)
            name = str(payload.pop("name", "")).strip()
            if not name:
                return None
            status = str(payload.pop("status", default_status) or default_status).strip() or default_status
            detail = str(payload.pop("detail", "")).strip()
            raw_meta = payload.pop("meta", {})
            meta: Dict[str, Any] = dict(raw_meta) if isinstance(raw_meta, dict) else {}
            for key, value in payload.items():
                if value is None:
                    continue
                meta.setdefault(key, value)

            if not detail:
                stage = str(meta.get("stage") or "").strip().lower()
                tool = str(meta.get("tool") or "").strip()
                if stage and tool:
                    detail = f"{stage}: {tool}"
                elif stage:
                    detail = f"{stage}: {name.replace('_', ' ')}"
                elif tool:
                    detail = f"{name.replace('_', ' ')} ({tool})"
                else:
                    detail = name.replace("_", " ")

            return {"name": name, "status": status, "detail": detail, "meta": meta}

        def drain_phase_queue(default_status: str) -> List[Dict[str, Any]]:
            drained: List[Dict[str, Any]] = []
            while True:
                try:
                    raw = phase_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                normalized = normalize_stream_phase(raw, default_status=default_status)
                if normalized:
                    drained.append(normalized)
            return drained

        deep_task = asyncio.create_task(
            self._chat_via_deepagents(
                user_message=user_message,
                history=history,
                attachments=attachments,
                phase_callback=enqueue_phase,
            )
        )
        try:
            deep_result: Optional[Dict[str, Any]]
            try:
                # Give very fast paths (e.g. greeting/help cache) a chance to finish
                # before emitting synthetic loading phases.
                deep_result = await asyncio.wait_for(asyncio.shield(deep_task), timeout=0.05)
            except asyncio.TimeoutError:
                deep_result = None

            if deep_result is None:
                last_progress_emit = 0.0
                while not deep_task.done():
                    emitted_live_phase = False
                    for phase in drain_phase_queue(default_status="running"):
                        phase_meta = dict(phase.get("meta") or {})
                        phase_meta["stream_live"] = True
                        phase["meta"] = phase_meta
                        yield {"type": "runtime_phase", "phase": phase}
                        emitted_live_phase = True

                    now_ts = asyncio.get_running_loop().time()
                    if progress_idx < len(progress_phases):
                        should_emit_synthetic = (not emitted_live_phase) and (now_ts - last_progress_emit >= 0.35)
                        if should_emit_synthetic:
                            name, detail = progress_phases[progress_idx]
                            progress_idx += 1
                            last_progress_emit = now_ts
                            yield {
                                "type": "runtime_phase",
                                "phase": {
                                    "name": name,
                                    "status": "running",
                                    "detail": detail,
                                    "meta": {"stage": "think", "synthetic": True},
                                },
                            }
                    await asyncio.sleep(0.12)

                deep_result = await deep_task
            if deep_result is None:
                raise RuntimeError("Deep Agents runtime returned no result.")

            for phase in drain_phase_queue(default_status="done"):
                phase_meta = dict(phase.get("meta") or {})
                phase_meta["stream_live"] = True
                phase["meta"] = phase_meta
                yield {"type": "runtime_phase", "phase": phase}

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
                normalized_phase = normalize_stream_phase(phase, default_status="done")
                if normalized_phase is None:
                    continue
                phase_meta = dict(normalized_phase.get("meta") or {})
                phase_meta["stream_final"] = True
                normalized_phase["meta"] = phase_meta
                yield {"type": "runtime_phase", "phase": normalized_phase}

            content = str(deep_result.get("content", "") or "")
            if content:
                content_len = len(content)
                # Smaller chunks + tiny pacing to feel like natural chatbot streaming.
                if content_len > 2400:
                    chunk_size = 64
                elif content_len > 1200:
                    chunk_size = 48
                elif content_len > 600:
                    chunk_size = 32
                else:
                    chunk_size = 20
                for i in range(0, content_len, chunk_size):
                    yield {"type": "delta", "content": content[i : i + chunk_size]}
                    if i + chunk_size < content_len:
                        await asyncio.sleep(0.012)

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
    _COMMAND_VOCAB: Tuple[str, ...] = (
        "check",
        "current",
        "symbol",
        "change",
        "switch",
        "time",
        "frame",
        "timeframe",
        "add",
        "remove",
        "get",
        "indicator",
        "indicators",
        "verify",
        "focus",
        "chart",
        "place",
        "order",
        "close",
        "position",
        "cancel",
        "reverse",
        "set",
        "list",
        "show",
        "fetch",
        "then",
        "and",
        "done",
    )
