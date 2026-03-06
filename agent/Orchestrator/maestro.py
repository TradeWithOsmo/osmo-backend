"""
Maestro Orchestrator

The Conductor of the trading orchestra.

Responsibilities:
  1. Understand user intent
  2. Open/close the web search gate
  3. Read the canvas (first move, always)
  4. Route to the right sections in the right order
  5. Synthesize all section outputs into one harmonious response

Full Orchestra Flow:
  Intent → Monitoring (pre-flight) → Memory (past context) → Canvas Read
  → Research (Violin) → Strategy (Composer) → Risk (Percussion)
  → Simulation (Rehearsal) → [Execution (Brass)]
  → Critic (evaluation) → Memory (store) → Synthesis

Not all sections play every time.
The Maestro decides who performs based on the user's intent.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

import httpx

from .orchestra_state import (
    OrchestraIntent,
    OrchestraState,
    SectionRole,
    SectionStatus,
)
from .orchestra_prompts import MAESTRO_INTENT_PROMPT, MAESTRO_SYNTHESIS_PROMPT
from .sections import (
    CriticSection,
    ExecutionSection,
    MemorySection,
    MonitoringSection,
    ResearchSection,
    RiskSection,
    SimulationSection,
    StrategySection,
)

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


# ---------------------------------------------------------------------------
# Symbol / timeframe extraction (reuse from reasoning_orchestrator)
# ---------------------------------------------------------------------------

_TIMEFRAME_RE = re.compile(
    r"\b(1m|3m|5m|15m|30m|1h|4h|1d|1w|daily|weekly|hourly)\b", re.I
)
_SYMBOL_RE = re.compile(
    r"\b([A-Z]{2,8})(?:[-/](?:USD|USDT|EUR|GBP|JPY|CHF|AUD|NZD|USDC))?\b"
)

_ENGLISH_SKIP = {
    "A", "AN", "THE", "AND", "OR", "BUT", "NOR", "SO", "YET", "AT", "BY",
    "FOR", "FROM", "IN", "INTO", "OF", "OFF", "ON", "OUT", "OVER", "PER",
    "TO", "UP", "VIA", "WITH", "I", "ME", "MY", "WE", "US", "OUR", "IT",
    "ITS", "DO", "DID", "IS", "AM", "ARE", "WAS", "WERE", "BE", "BEEN",
    "HAS", "HAD", "GET", "GOT", "SET", "LET", "USE", "RUN", "ANALYZE",
    "ANALYSIS", "COMPARE", "CHECK", "SHOW", "GIVE", "FIND", "LOOK", "SCAN",
    "PLOT", "DRAW", "ADD", "LIST", "MARKET", "MARKETS", "TRADE", "TRADES",
    "CHART", "CHARTS", "PRICE", "PRICES", "SIGNAL", "SIGNALS", "BOTH",
    "ALL", "HIGH", "LOW", "OPEN", "CLOSE", "VOLUME", "DATA", "NOW", "THEN",
    "WHEN", "WHAT", "HOW", "WHY", "WHICH", "USD", "EUR", "GBP", "JPY",
    "CHF", "CAD", "AUD", "NZD", "USDT", "USDC", "BUSD",
}


def _extract_symbols(message: str) -> List[str]:
    found: List[str] = []
    for m in re.finditer(
        r"\b([A-Z]{2,8})(?:[-/](?:USD|USDT|EUR|GBP|JPY|CHF|AUD|NZD|USDC))?\b",
        message.upper(),
    ):
        candidate = m.group(1)
        full = m.group(0).upper().replace("/", "-").replace("_", "-")
        is_pair = "-" in full
        if candidate not in _ENGLISH_SKIP or is_pair:
            if full not in found:
                found.append(full)
    return found[:5]


def _extract_timeframe(message: str) -> str:
    m = _TIMEFRAME_RE.search(message)
    if not m:
        return ""
    raw = m.group(1).upper()
    mapping = {"DAILY": "1D", "WEEKLY": "1W", "HOURLY": "1H"}
    return mapping.get(raw, raw)


# ---------------------------------------------------------------------------
# Maestro
# ---------------------------------------------------------------------------


class MaestroOrchestrator:
    """
    The Maestro — conducts the trading analysis orchestra.

    Usage:
        maestro = MaestroOrchestrator(
            executor=tool_executor,
            evaluator=evaluator,
            registry=tool_registry,
            model_id="anthropic/claude-3.5-sonnet",
            api_key=api_key,
            tool_states=tool_states,
        )
        result = await maestro.conduct(user_message, history)
    """

    def __init__(
        self,
        *,
        executor: Any,
        evaluator: Any,
        registry: Dict[str, Any],
        model_id: str,
        api_key: str,
        tool_states: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self._executor = executor
        self._evaluator = evaluator
        self._registry = registry
        self.model_id = model_id
        self.api_key = api_key
        self.tool_states = dict(tool_states or {})
        self.user_context = dict(user_context or {})
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort

        # Initialize sections — each gets the same executor and evaluator
        section_kwargs = dict(
            executor=executor,
            evaluator=evaluator,
            registry=registry,
            model_id=model_id,
            api_key=api_key,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        # Primary sections
        self._research = ResearchSection(**section_kwargs)
        self._strategy = StrategySection(**section_kwargs)
        self._execution = ExecutionSection(**section_kwargs)
        # Supporting sections
        self._memory = MemorySection(**section_kwargs)
        self._risk = RiskSection(**section_kwargs)
        self._monitoring = MonitoringSection(**section_kwargs)
        self._simulation = SimulationSection(**section_kwargs)
        self._critic = CriticSection(**section_kwargs)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": "Osmo Maestro",
        }

    # ------------------------------------------------------------------
    # Intent Classification
    # ------------------------------------------------------------------

    async def _classify_intent(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        client: httpx.AsyncClient,
    ) -> Tuple[OrchestraIntent, List[str], str, bool]:
        """
        Classify user intent using lightweight LLM call.
        Falls back to heuristic if LLM fails.

        Returns: (intent, symbols, timeframe, web_search_needed)
        """
        # First try heuristic (fast path for obvious intents)
        heuristic = self._heuristic_intent(user_message)

        # For quick intents, skip LLM call
        if heuristic == OrchestraIntent.QUICK:
            symbols = _extract_symbols(user_message)
            tf = _extract_timeframe(user_message)
            return heuristic, symbols, tf, False

        # Use LLM for nuanced classification
        try:
            body: Dict[str, Any] = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": MAESTRO_INTENT_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.0,
            }
            resp = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            completion = resp.json()

            text = ""
            choices = completion.get("choices") or []
            if choices:
                text = str((choices[0].get("message") or {}).get("content") or "")

            # Parse JSON from response
            parsed = self._parse_intent_json(text)
            if parsed:
                intent_str = str(parsed.get("intent") or "analysis").lower()
                intent_map = {
                    "analysis": OrchestraIntent.ANALYSIS,
                    "execution": OrchestraIntent.EXECUTION,
                    "research": OrchestraIntent.RESEARCH,
                    "quick": OrchestraIntent.QUICK,
                    "monitor": OrchestraIntent.MONITOR,
                }
                intent = intent_map.get(intent_str, OrchestraIntent.ANALYSIS)
                symbols = parsed.get("symbols") or _extract_symbols(user_message)
                tf = parsed.get("timeframe") or _extract_timeframe(user_message)
                web = bool(parsed.get("web_search_needed", False))
                return intent, symbols, str(tf), web

        except Exception as exc:
            logger.debug("[Maestro] Intent LLM call failed, using heuristic: %s", exc)

        # Fallback to heuristic
        symbols = _extract_symbols(user_message)
        tf = _extract_timeframe(user_message)
        web = heuristic == OrchestraIntent.RESEARCH
        return heuristic, symbols, tf, web

    @staticmethod
    def _heuristic_intent(message: str) -> OrchestraIntent:
        """Fast keyword-based intent classification."""
        text = message.lower()

        # Execution keywords
        exec_kw = ("place order", "buy", "sell", "long", "short", "entry",
                    "execute", "open position", "close position", "tp", "sl",
                    "take profit", "stop loss", "beli", "jual")
        if any(kw in text for kw in exec_kw):
            return OrchestraIntent.EXECUTION

        # Monitor keywords
        monitor_kw = ("position", "portfolio", "balance", "check", "status",
                      "my trade", "my order", "pnl")
        if any(kw in text for kw in monitor_kw):
            return OrchestraIntent.MONITOR

        # Research keywords
        research_kw = ("news", "sentiment", "research", "why", "what happened",
                       "fundamental", "berita", "kenapa")
        if any(kw in text for kw in research_kw):
            return OrchestraIntent.RESEARCH

        # Quick keywords (greetings, simple questions)
        quick_kw = ("hello", "hi", "hey", "thanks", "thank you", "help",
                    "halo", "terima kasih", "tolong")
        if any(kw in text for kw in quick_kw) and len(text.split()) < 8:
            return OrchestraIntent.QUICK

        # Default: analysis
        return OrchestraIntent.ANALYSIS

    @staticmethod
    def _parse_intent_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response."""
        text = text.strip()
        # Try direct parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Try extracting JSON block
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return None

    # ------------------------------------------------------------------
    # Canvas Reader (Conductor's First Move)
    # ------------------------------------------------------------------

    async def _read_canvas(
        self,
        state: OrchestraState,
        symbol: str,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Read the chart canvas — always the Maestro's first move."""
        def _emit(t: str, d: str) -> None:
            if emit:
                try:
                    emit(t, d)
                except Exception:
                    pass

        _emit("tool_call", f"[Maestro] reading canvas for {symbol}...")

        exec_result = await self._executor.execute(
            "get_active_indicators", {"symbol": symbol}
        )
        actual = exec_result.get("result") if exec_result.get("ok") else {}

        indicators: List[str] = []
        timeframe = ""
        if isinstance(actual, dict):
            payload_data = actual.get("data", {}) if isinstance(actual, dict) else {}
            if isinstance(payload_data, dict):
                active = payload_data.get("active_indicators", [])
                if isinstance(active, list):
                    indicators = [str(i) for i in active]
                timeframe = str(payload_data.get("timeframe") or "").strip()

        state.update_canvas(symbol=symbol, timeframe=timeframe, indicators=indicators)
        state.total_tool_calls += 1

        canvas_desc = (
            f"{len(indicators)} indicators [{', '.join(indicators[:6])}]"
            if indicators else "clean canvas"
        )
        _emit("tool_result", f"[Maestro] canvas: {symbol} @ {timeframe or '?'} — {canvas_desc}")

        logger.info(
            "[Maestro] Canvas read: %s @ %s — %d indicators",
            symbol, timeframe or "?", len(indicators),
        )

    # ------------------------------------------------------------------
    # Synthesis (Final Composition)
    # ------------------------------------------------------------------

    async def _synthesize(
        self,
        state: OrchestraState,
        user_message: str,
        section_outputs: Dict[str, str],
        client: httpx.AsyncClient,
    ) -> str:
        """
        Combine all section outputs into one harmonious response.
        Uses the Maestro's synthesis prompt.
        """
        parts: List[str] = []

        if "research" in section_outputs:
            parts.append(f"## Research Findings\n{section_outputs['research']}")

        if "strategy" in section_outputs:
            parts.append(f"## Strategy Analysis\n{section_outputs['strategy']}")

        if "risk" in section_outputs:
            parts.append(f"## Risk Assessment\n{section_outputs['risk']}")

        if "simulation" in section_outputs:
            parts.append(f"## Simulation Results\n{section_outputs['simulation']}")

        if "execution" in section_outputs:
            parts.append(f"## Execution Report\n{section_outputs['execution']}")

        # If only one section played and its output is clean, return it directly
        if len(parts) == 1:
            return list(section_outputs.values())[0]

        if not parts:
            return ""

        combined = "\n\n".join(parts)

        # Apply conversation style if configured
        style_context = ""
        conversation_style = str(self.tool_states.get("conversation_style") or "").strip()
        trading_style = str(
            self.tool_states.get("trading_style")
            or self.tool_states.get("trading_style_profile")
            or ""
        ).strip()
        if conversation_style:
            style_context += f"\nConversation style: {conversation_style}"
        if trading_style and trading_style.lower() not in {"off", "none", "default"}:
            style_context += f"\nTrading style: {trading_style}"

        synthesis_prompt = MAESTRO_SYNTHESIS_PROMPT
        if style_context:
            synthesis_prompt += f"\n\n<style>{style_context}</style>"

        messages = [
            {"role": "system", "content": synthesis_prompt},
            {"role": "user", "content": (
                f"User asked: {user_message}\n\n"
                f"Section outputs:\n{combined}\n\n"
                f"Synthesize into one clear, cohesive response."
            )},
        ]

        try:
            body: Dict[str, Any] = {
                "model": self.model_id,
                "messages": messages,
                "temperature": self.temperature,
            }
            resp = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=60.0,
            )
            resp.raise_for_status()
            completion = resp.json()
            state.total_llm_calls += 1

            choices = completion.get("choices") or []
            if choices:
                return str((choices[0].get("message") or {}).get("content") or "")
        except Exception as exc:
            logger.error("[Maestro] Synthesis failed: %s", exc)

        # Fallback: just concatenate section outputs
        return combined

    # ------------------------------------------------------------------
    # Quick Response (no sections needed)
    # ------------------------------------------------------------------

    async def _quick_response(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        client: httpx.AsyncClient,
    ) -> str:
        """Handle quick intents (greetings, simple questions) directly."""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": (
                "You are Osmo, a friendly and knowledgeable trading assistant. "
                "Respond naturally and concisely. If the user is greeting you, "
                "greet them back warmly. If they have a simple question, answer it."
            )},
        ]
        for item in (history or []):
            if isinstance(item, dict) and item.get("content"):
                role = str(item.get("role") or "user").strip().lower()
                if role not in {"system", "assistant", "user"}:
                    role = "user"
                messages.append({"role": role, "content": str(item["content"])})
        messages.append({"role": "user", "content": user_message})

        try:
            body: Dict[str, Any] = {
                "model": self.model_id,
                "messages": messages,
                "temperature": self.temperature,
            }
            resp = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            completion = resp.json()
            choices = completion.get("choices") or []
            if choices:
                return str((choices[0].get("message") or {}).get("content") or "")
        except Exception as exc:
            logger.error("[Maestro] Quick response failed: %s", exc)
        return "Hey! How can I help you with your trading today?"

    # ------------------------------------------------------------------
    # Main Conduct Method
    # ------------------------------------------------------------------

    async def conduct(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "",
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Tuple[str, OrchestraState]:
        """
        Conduct the full orchestra performance.

        This is the main entry point. The Maestro:
        1. Classifies intent
        2. Reads the canvas
        3. Routes to the right sections
        4. Synthesizes the final response

        Parameters
        ----------
        user_message : str
            The user's message.
        history : list, optional
            Conversation history.
        session_id : str
            Session identifier.
        stream_callback : callable, optional
            Stream events to the caller.

        Returns
        -------
        tuple of (response_text, OrchestraState)
        """
        def _emit(event_type: str, data: str) -> None:
            if stream_callback:
                try:
                    stream_callback(event_type, data)
                except Exception:
                    pass

        state = OrchestraState(
            user_message=user_message,
            session_id=session_id,
            user_address=str(self.user_context.get("user_address") or ""),
        )

        t_start = time.monotonic()

        async with httpx.AsyncClient(timeout=120.0) as client:
            # ---- Step 1: Classify Intent ----
            _emit("thinking", "[Maestro] understanding your intent...")
            intent, symbols, timeframe, web_needed = await self._classify_intent(
                user_message, history, client
            )

            state.intent = intent
            state.target_symbols = symbols
            state.primary_symbol = symbols[0] if symbols else ""
            state.timeframe = timeframe
            state.web_gate_open = web_needed
            state.total_llm_calls += 1

            _emit("thinking", (
                f"[Maestro] intent={intent.value}, "
                f"symbols={symbols}, timeframe={timeframe or 'auto'}, "
                f"web_gate={'OPEN' if web_needed else 'CLOSED'}"
            ))

            # Also check tool_states for symbol fallback
            if not state.primary_symbol:
                fallback_sym = str(
                    self.tool_states.get("market_symbol")
                    or self.tool_states.get("market")
                    or ""
                ).strip().upper()
                if fallback_sym:
                    state.primary_symbol = fallback_sym
                    state.target_symbols = [fallback_sym]

            logger.info(
                "[Maestro] Intent=%s, Symbols=%s, TF=%s, WebGate=%s",
                intent.value, symbols, timeframe, web_needed,
            )

            # ---- Step 2: Quick path (no sections needed) ----
            if intent == OrchestraIntent.QUICK:
                _emit("thinking", "[Maestro] quick response — no sections needed")
                for role in SectionRole:
                    if role != SectionRole.MAESTRO:
                        state.skip_section(role)
                response = await self._quick_response(user_message, history, client)
                state.total_llm_calls += 1
                _emit("content", response)
                return response, state

            # ---- Step 3: Monitoring (Sound Engineer — pre-flight check) ----
            await self._run_section(
                section=self._monitoring,
                role=SectionRole.MONITORING,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Monitoring (Sound Engineer)",
                should_play=True,  # Always plays
            )

            # If monitoring says system is unhealthy, log warning but continue
            if not state.system_health.healthy:
                _emit("tool_result", "[Maestro] WARNING: System health degraded — proceeding with caution")

            # ---- Step 4: Memory (Librarian — retrieve past context) ----
            memory_enabled = self._is_flag_true(self.tool_states.get("memory_enabled"))
            await self._run_section(
                section=self._memory,
                role=SectionRole.MEMORY,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Memory (Librarian)",
                should_play=memory_enabled and intent != OrchestraIntent.MONITOR,
            )

            # ---- Step 5: Read the Canvas (Maestro's first move) ----
            if state.primary_symbol:
                await self._read_canvas(state, state.primary_symbol, emit=stream_callback)

            # ---- Step 6: Research (Violin) ----
            section_outputs: Dict[str, str] = {}
            research_plays = intent in (
                OrchestraIntent.ANALYSIS,
                OrchestraIntent.EXECUTION,
                OrchestraIntent.RESEARCH,
                OrchestraIntent.MONITOR,
            )
            output = await self._run_section(
                section=self._research,
                role=SectionRole.RESEARCH,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Research (Violin)",
                should_play=research_plays,
            )
            if output:
                section_outputs["research"] = output

            # ---- Step 7: Strategy (Composer) ----
            strategy_plays = intent in (OrchestraIntent.ANALYSIS, OrchestraIntent.EXECUTION)
            output = await self._run_section(
                section=self._strategy,
                role=SectionRole.STRATEGY,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Strategy (Composer)",
                should_play=strategy_plays,
            )
            if output:
                section_outputs["strategy"] = output

            # ---- Step 8: Risk (Percussion — guards before execution) ----
            risk_plays = intent == OrchestraIntent.EXECUTION and state.strategy.bias != ""
            output = await self._run_section(
                section=self._risk,
                role=SectionRole.RISK,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Risk (Percussion)",
                should_play=risk_plays,
            )
            if output:
                section_outputs["risk"] = output

            # ---- Step 9: Simulation (Rehearsal Director — test before execution) ----
            sim_plays = (
                intent == OrchestraIntent.EXECUTION
                and state.strategy.bias != ""
                and state.risk.approved  # Only simulate if risk hasn't blocked
            )
            output = await self._run_section(
                section=self._simulation,
                role=SectionRole.SIMULATION,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Simulation (Rehearsal Director)",
                should_play=sim_plays,
            )
            if output:
                section_outputs["simulation"] = output

            # ---- Step 10: Execution (Brass) ----
            execution_enabled = self._is_flag_true(self.tool_states.get("execution"))
            exec_plays = (
                intent == OrchestraIntent.EXECUTION
                and execution_enabled
                and state.risk.approved  # Risk Agent can block execution
            )
            if intent == OrchestraIntent.EXECUTION and not state.risk.approved:
                state.skip_section(SectionRole.EXECUTION)
                _emit("thinking", "[Maestro] Risk Agent BLOCKED execution — Brass section silent.")
            elif intent == OrchestraIntent.EXECUTION and not execution_enabled:
                state.skip_section(SectionRole.EXECUTION)
                _emit("thinking", "[Maestro] Execution disabled — Brass section silent. Strategy will use setup_trade() instead.")
            else:
                output = await self._run_section(
                    section=self._execution,
                    role=SectionRole.EXECUTION,
                    state=state,
                    context_message=user_message,
                    client=client,
                    emit=stream_callback,
                    label="Execution (Brass)",
                    should_play=exec_plays,
                )
                if output:
                    section_outputs["execution"] = output

            # ---- Step 11: Critic (Music Critic — evaluate performance) ----
            # Plays after all primary sections, for analysis and execution intents
            critic_plays = (
                intent in (OrchestraIntent.ANALYSIS, OrchestraIntent.EXECUTION)
                and len(section_outputs) >= 2  # At least research + strategy
            )
            output = await self._run_section(
                section=self._critic,
                role=SectionRole.CRITIC,
                state=state,
                context_message=user_message,
                client=client,
                emit=stream_callback,
                label="Critic (Music Critic)",
                should_play=critic_plays,
            )
            # Critic output is stored in state but not added to section_outputs
            # (it's internal feedback, not user-facing)

            # ---- Step 12: Memory Store (Librarian — save results) ----
            if memory_enabled and state.research.symbol:
                try:
                    await self._memory.store_performance(
                        state=state, client=client, emit=stream_callback
                    )
                except Exception as exc:
                    logger.debug("[Maestro] Memory store failed: %s", exc)

            # ---- Step 13: Synthesis ----
            if len(section_outputs) > 1:
                _emit("thinking", "[Maestro] synthesizing all section outputs...")
                response = await self._synthesize(
                    state, user_message, section_outputs, client
                )
            elif section_outputs:
                response = list(section_outputs.values())[0]
            else:
                response = "I couldn't complete the analysis. Please try again."

            _emit("content", response)

        total_elapsed = (time.monotonic() - t_start) * 1000
        logger.info(
            "[Maestro] Performance complete — intent=%s, sections=%d, tools=%d, llm=%d, time=%.0fms",
            intent.value,
            len([s for s in state.sections.values() if s.status == SectionStatus.DONE]),
            state.total_tool_calls,
            state.total_llm_calls,
            total_elapsed,
        )

        return response, state

    # ------------------------------------------------------------------
    # Section runner helper
    # ------------------------------------------------------------------

    async def _run_section(
        self,
        *,
        section: Any,
        role: SectionRole,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]],
        label: str,
        should_play: bool,
    ) -> Optional[str]:
        """
        Run a single section with proper state tracking and error handling.
        Returns the section's text output, or None if skipped/failed.
        """
        def _emit_safe(t: str, d: str) -> None:
            if emit:
                try:
                    emit(t, d)
                except Exception:
                    pass

        if not should_play:
            state.skip_section(role)
            return None

        state.init_section(role)
        _emit_safe("thinking", f"[Maestro] cue: {label}...")
        t_section = time.monotonic()

        try:
            output = await section.perform(
                state=state,
                context_message=context_message,
                client=client,
                emit=emit,
            )
            elapsed = (time.monotonic() - t_section) * 1000
            state.complete_section(
                role, content=output, elapsed_ms=elapsed,
            )
            return output
        except Exception as exc:
            logger.error("[Maestro] %s failed: %s", label, exc)
            state.fail_section(role, str(exc))
            _emit_safe("tool_result", f"[{label}] error: {exc}")
            return None

    @staticmethod
    def _is_flag_true(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value) if value is not None else False


__all__ = ["MaestroOrchestrator"]
