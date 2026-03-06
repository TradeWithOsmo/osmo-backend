"""
Orchestra Sections

Each section is a specialized mini-agent with its own system prompt,
tool set, and reflexion mini-loop. They share the _ToolExecutor and
evaluator infrastructure from the core ReflexionAgent.

Primary Sections:
  - ResearchSection (Violin) — data gathering
  - StrategySection (Composer) — strategy formulation
  - ExecutionSection (Brass) — trade execution

Supporting Sections:
  - MemorySection (Librarian) — past context retrieval
  - RiskSection (Percussion) — risk assessment
  - MonitoringSection (Sound Engineer) — system health
  - SimulationSection (Rehearsal Director) — scenario testing
  - CriticSection (Music Critic) — performance evaluation
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from .orchestra_state import (
    OrchestraState,
    ResearchFindings,
    RiskAssessment,
    SectionRole,
    SectionStatus,
    SimulationResult,
    StrategyPlan,
    SystemHealth,
)
from .orchestra_prompts import (
    RESEARCH_SYSTEM_PROMPT,
    STRATEGY_SYSTEM_PROMPT,
    EXECUTION_SYSTEM_PROMPT,
    MEMORY_SYSTEM_PROMPT,
    RISK_SYSTEM_PROMPT,
    MONITORING_SYSTEM_PROMPT,
    SIMULATION_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


# ---------------------------------------------------------------------------
# Tool sets per section — each section only sees its own instruments
# ---------------------------------------------------------------------------

RESEARCH_TOOLS = {
    # Data
    "get_price", "get_technical_analysis", "get_high_low_levels",
    "get_ticker_stats", "get_funding_rate",
    "get_indicators", "get_chainlink_price", "get_technical_summary",
    # Canvas read
    "get_active_indicators",
    # Web (conditionally enabled by web gate)
    "search_news", "search_sentiment", "search_web_hybrid",
}

STRATEGY_TOOLS = {
    # Canvas read/write
    "get_active_indicators", "add_indicator", "remove_indicator",
    "set_timeframe", "set_symbol", "setup_trade",
    # Drawing
    "draw", "update_drawing", "clear_drawings",
    # Data (for validation)
    "get_price", "get_high_low_levels", "get_technical_analysis",
}

EXECUTION_TOOLS = {
    # Trade execution
    "place_order", "get_positions", "close_position",
    "close_all_positions", "reverse_position", "cancel_order",
    "adjust_position_tpsl", "adjust_all_positions_tpsl",
    # Visualization
    "setup_trade",
    # Data (for validation)
    "get_price", "get_positions",
}

MEMORY_TOOLS = {
    "search_memory", "get_recent_history", "add_memory",
}

RISK_TOOLS = {
    "get_price", "get_positions", "get_funding_rate",
    "get_ticker_stats",
}

MONITORING_TOOLS: set = set()  # No tools — works from context only

SIMULATION_TOOLS = {
    "get_price", "get_technical_analysis", "get_high_low_levels",
    "get_ticker_stats",
}

CRITIC_TOOLS: set = set()  # No tools — evaluates from context only

# Web tools that require the gate to be open
WEB_GATE_TOOLS = {"search_news", "search_sentiment", "search_web_hybrid"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


def _trim_result(result: Any, max_chars: int = 2000) -> str:
    text = _safe_json_dumps(result)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"...[truncated, total {len(text)} chars]"


def _format_sig(name: str, args: Dict[str, Any]) -> str:
    if not args:
        return f"{name}()"
    parts = []
    for i, (k, v) in enumerate(args.items()):
        if i >= 4:
            parts.append("...")
            break
        raw = _safe_json_dumps(v)
        if len(raw) > 40:
            raw = raw[:37] + "..."
        parts.append(f"{k}={raw}")
    return f"{name}({', '.join(parts)})"


# ---------------------------------------------------------------------------
# Base Section
# ---------------------------------------------------------------------------


class BaseSection:
    """
    Base class for all orchestra sections.

    Each section runs a mini reflexion loop:
      Call LLM → Execute tool calls → Evaluate → Retry if needed → Loop

    Sections are stateless — they receive context, do their work,
    and return structured output.
    """

    ROLE: SectionRole = SectionRole.RESEARCH
    SYSTEM_PROMPT: str = ""
    ALLOWED_TOOLS: set = set()
    MAX_ITERATIONS: int = 6
    MAX_RETRIES: int = 2

    def __init__(
        self,
        *,
        executor: Any,          # _ToolExecutor from reflexion_agent
        evaluator: Any,         # ReflexionEvaluator
        registry: Dict[str, Any],
        model_id: str,
        api_key: str,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self._executor = executor
        self._evaluator = evaluator
        self._registry = registry
        self.model_id = model_id
        self.api_key = api_key
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tradewithosmo.com",
            "X-Title": f"Osmo Orchestra {self.ROLE.value}",
        }

    def _build_tools_payload(
        self, state: OrchestraState
    ) -> List[Dict[str, Any]]:
        """Build OpenAI-style tools list filtered to this section's instruments."""
        payload: List[Dict[str, Any]] = []
        allowed = set(self.ALLOWED_TOOLS)

        # Close web gate if maestro says so
        if not state.web_gate_open:
            allowed -= WEB_GATE_TOOLS

        for name in sorted(allowed):
            spec = self._registry.get(name)
            if not isinstance(spec, dict):
                continue
            parameters = spec.get("parameters") or {
                "type": "object",
                "additionalProperties": True,
            }
            payload.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec.get("description", name),
                    "parameters": parameters,
                },
            })
        return payload

    async def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools_payload: List[Dict[str, Any]],
        client: httpx.AsyncClient,
    ) -> Dict[str, Any]:
        """Single LLM call via OpenRouter."""
        body: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.reasoning_effort:
            body["include_reasoning"] = True
            body["reasoning"] = {"effort": self.reasoning_effort}
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

    @staticmethod
    def _extract_tool_calls(completion: Dict[str, Any]) -> List[Dict[str, Any]]:
        choices = completion.get("choices") or []
        if not choices:
            return []
        message = choices[0].get("message") or {}
        return message.get("tool_calls") or []

    @staticmethod
    def _extract_text(completion: Dict[str, Any]) -> str:
        choices = completion.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or item) if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content)

    @staticmethod
    def _parse_args(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        Run this section's mini reflexion loop.

        Parameters
        ----------
        state : OrchestraState
            Shared orchestra state (read/write).
        context_message : str
            The user message or upstream section's output.
        client : httpx.AsyncClient
            Shared HTTP client.
        emit : callable, optional
            Stream callback for events.

        Returns
        -------
        str : The section's text output.
        """
        def _emit(event_type: str, data: str) -> None:
            if emit:
                try:
                    emit(event_type, data)
                except Exception:
                    pass

        section_name = self.ROLE.value.capitalize()
        _emit("thinking", f"[{section_name}] section begins...")

        tools_payload = self._build_tools_payload(state)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": context_message},
        ]

        final_content = ""
        tool_call_count = 0
        t_start = time.monotonic()

        for iteration in range(self.MAX_ITERATIONS):
            try:
                completion = await self._call_llm(messages, tools_payload, client)
                state.total_llm_calls += 1
            except Exception as exc:
                logger.error("[%s] LLM call failed: %s", section_name, exc)
                _emit("tool_result", f"[{section_name}] LLM error: {exc}")
                break

            tool_calls = self._extract_tool_calls(completion)
            text_content = self._extract_text(completion)

            if text_content:
                _emit("content", text_content)
                final_content = text_content

            if not tool_calls:
                break

            # Add assistant message with tool calls
            assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if text_content:
                assistant_msg["content"] = text_content
            messages.append(assistant_msg)

            # Execute each tool call
            tool_results_msgs: List[Dict[str, Any]] = []
            for tc in tool_calls:
                tc_id = tc.get("id") or f"call_{iteration}_{tool_call_count}"
                fn = tc.get("function") or {}
                raw_name = str(fn.get("name") or "")
                raw_args = self._parse_args(fn.get("arguments") or {})

                # Verify tool is in this section's allowed set
                if raw_name not in self.ALLOWED_TOOLS:
                    tool_results_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps({
                            "error": f"Tool '{raw_name}' is not available in the {section_name} section."
                        }),
                    })
                    continue

                # Web gate check
                if raw_name in WEB_GATE_TOOLS and not state.web_gate_open:
                    tool_results_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps({
                            "error": f"Web search gate is closed. '{raw_name}' is not available."
                        }),
                    })
                    continue

                _emit("tool_call", f"[{section_name}] {_format_sig(raw_name, raw_args)}")

                # Execute
                exec_result = await self._executor.execute(raw_name, raw_args)
                tool_call_count += 1
                state.total_tool_calls += 1

                actual = exec_result.get("result") if exec_result.get("ok") else exec_result

                # Evaluate
                status, note, fix_hint = self._evaluator.evaluate(
                    raw_name, raw_args, actual
                )
                _emit("tool_result", f"[{section_name}] {status.value.upper()}: {note}")

                # Retry if needed
                retry_count = 0
                while (
                    self._evaluator.should_retry(status, raw_name, retry_count, self.MAX_RETRIES)
                ):
                    fixed_args = self._evaluator.apply_fix_to_args(
                        raw_name, raw_args, fix_hint or ""
                    )
                    _emit("tool_call", f"[{section_name}] retry #{retry_count+1}: {_format_sig(raw_name, fixed_args)}")

                    exec_result = await self._executor.execute(raw_name, fixed_args)
                    tool_call_count += 1
                    state.total_tool_calls += 1
                    actual = exec_result.get("result") if exec_result.get("ok") else exec_result
                    status, note, fix_hint = self._evaluator.evaluate(
                        raw_name, fixed_args, actual
                    )
                    retry_count += 1
                    if status.value == "good":
                        break

                # Ingest canvas state if applicable
                if raw_name == "get_active_indicators" and isinstance(actual, dict):
                    payload_data = actual.get("data", {}) if isinstance(actual, dict) else {}
                    if isinstance(payload_data, dict):
                        indicators = [str(i) for i in payload_data.get("active_indicators", [])]
                        tf = str(payload_data.get("timeframe") or "").strip()
                        symbol = str(raw_args.get("symbol") or state.primary_symbol or "").upper()
                        state.update_canvas(symbol=symbol, timeframe=tf, indicators=indicators)

                tool_results_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": _trim_result(actual),
                })

            messages.extend(tool_results_msgs)

        elapsed = (time.monotonic() - t_start) * 1000
        _emit("thinking", f"[{section_name}] done — {tool_call_count} tool calls, {elapsed:.0f}ms")

        return final_content

    def _build_context_for_next(self, state: OrchestraState) -> str:
        """Override in subclasses to build context for the next section."""
        return ""


# ---------------------------------------------------------------------------
# Research Section (Violin)
# ---------------------------------------------------------------------------


class ResearchSection(BaseSection):
    """
    The Violin Section — gathers market data, news, and sentiment.
    Produces ResearchFindings that feed into the Strategy section.
    """

    ROLE = SectionRole.RESEARCH
    SYSTEM_PROMPT = RESEARCH_SYSTEM_PROMPT
    ALLOWED_TOOLS = RESEARCH_TOOLS
    MAX_ITERATIONS = 5

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Enrich context with canvas state if available
        enriched = context_message
        if state.canvas_read and state.canvas_indicators:
            canvas_info = (
                f"\n\n[Current Canvas] {state.canvas_symbol} @ {state.canvas_timeframe}"
                f" — active indicators: {', '.join(state.canvas_indicators[:8])}"
            )
            enriched += canvas_info

        if state.web_gate_open:
            enriched += "\n\n[Web Search Gate: OPEN — you may use search_news, search_sentiment, search_web_hybrid]"
        else:
            enriched += "\n\n[Web Search Gate: CLOSED — internal data only]"

        content = await super().perform(state, enriched, client, emit)

        # Parse findings from the LLM output and tool results
        self._extract_findings(state, content)

        return content

    def _extract_findings(self, state: OrchestraState, content: str) -> None:
        """
        Best-effort extraction of structured findings from tool execution
        and LLM text output. The data was already ingested by tool execution,
        so we read from state.
        """
        findings = state.research
        findings.symbol = state.primary_symbol
        findings.canvas_indicators = list(state.canvas_indicators)
        findings.canvas_timeframe = state.canvas_timeframe


# ---------------------------------------------------------------------------
# Strategy Section (Composer)
# ---------------------------------------------------------------------------


class StrategySection(BaseSection):
    """
    The Composer — takes research findings and writes the strategic score.
    Produces a StrategyPlan that feeds into the Execution section.
    """

    ROLE = SectionRole.STRATEGY
    SYSTEM_PROMPT = STRATEGY_SYSTEM_PROMPT
    ALLOWED_TOOLS = STRATEGY_TOOLS
    MAX_ITERATIONS = 6

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build context from research findings
        research_brief = state.research.to_brief()
        enriched = (
            f"# Research Findings\n{research_brief}\n\n"
            f"# User Request\n{context_message}"
        )

        if state.canvas_read:
            canvas_note = f"\n\n[Canvas] {state.canvas_symbol} @ {state.canvas_timeframe}"
            if state.canvas_indicators:
                canvas_note += f" — active: {', '.join(state.canvas_indicators[:8])}"
            else:
                canvas_note += " — clean (no indicators)"
            enriched += canvas_note

        content = await super().perform(state, enriched, client, emit)

        # Extract strategy from LLM output
        self._extract_strategy(state, content)

        return content

    def _extract_strategy(self, state: OrchestraState, content: str) -> None:
        """Best-effort extraction of strategy plan from LLM output."""
        plan = state.strategy
        text = content.lower()

        # Try to extract bias
        if "long" in text and "short" not in text:
            plan.bias = "long"
        elif "short" in text and "long" not in text:
            plan.bias = "short"
        elif "neutral" in text or "wait" in text:
            plan.bias = "neutral"

        plan.reasoning = content[:500] if content else ""


# ---------------------------------------------------------------------------
# Execution Section (Brass)
# ---------------------------------------------------------------------------


class ExecutionSection(BaseSection):
    """
    The Brass Section — executes trades with precision and discipline.
    Only plays when the Maestro calls for execution.
    """

    ROLE = SectionRole.EXECUTION
    SYSTEM_PROMPT = EXECUTION_SYSTEM_PROMPT
    ALLOWED_TOOLS = EXECUTION_TOOLS
    MAX_ITERATIONS = 4

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build context from research + strategy
        research_brief = state.research.to_brief()
        strategy_brief = state.strategy.to_brief()

        enriched = (
            f"# Research Data\n{research_brief}\n\n"
            f"# Strategy Plan\n{strategy_brief}\n\n"
            f"# User Request\n{context_message}"
        )

        # Add risk assessment context if available
        if state.risk.risk_level:
            enriched += f"\n\n# Risk Assessment\n{state.risk.to_brief()}"
            if not state.risk.approved:
                enriched += (
                    "\n\nWARNING: Risk Agent has BLOCKED execution. "
                    "Use setup_trade() to visualize instead of placing orders."
                )

        # Add simulation context if available
        if state.simulation.scenarios_tested > 0:
            enriched += f"\n\n# Simulation Results\n{state.simulation.to_brief()}"

        content = await super().perform(state, enriched, client, emit)
        return content


# ---------------------------------------------------------------------------
# Memory Section (Librarian)
# ---------------------------------------------------------------------------


class MemorySection(BaseSection):
    """
    The Orchestra Librarian — retrieves relevant past context.
    Plays before Research to provide historical context.
    Can also store results after the performance.
    """

    ROLE = SectionRole.MEMORY
    SYSTEM_PROMPT = MEMORY_SYSTEM_PROMPT
    ALLOWED_TOOLS = MEMORY_TOOLS
    MAX_ITERATIONS = 3

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build query from user message and symbol
        enriched = context_message
        if state.primary_symbol:
            enriched += f"\n\n[Context] Primary symbol: {state.primary_symbol}"
        if state.target_symbols:
            enriched += f"\n[Target symbols: {', '.join(state.target_symbols)}]"

        content = await super().perform(state, enriched, client, emit)

        # Store any retrieved memories in state
        if content:
            mem = state.memory_context
            mem.relevant_memories.append(content[:500])

        return content

    async def store_performance(
        self,
        state: OrchestraState,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Store the results of this performance for future reference."""
        from .orchestra_prompts import MEMORY_STORE_PROMPT

        summary_parts: List[str] = []
        if state.research.symbol:
            summary_parts.append(f"Symbol: {state.research.symbol}")
            summary_parts.append(state.research.to_brief())
        if state.strategy.bias:
            summary_parts.append(state.strategy.to_brief())
        if state.risk.risk_level:
            summary_parts.append(state.risk.to_brief())
        if state.critic.overall_grade:
            summary_parts.append(state.critic.to_brief())

        if not summary_parts:
            return

        summary_text = "\n".join(summary_parts)

        # Use LLM to create a concise memory entry
        try:
            messages = [
                {"role": "system", "content": MEMORY_STORE_PROMPT},
                {"role": "user", "content": summary_text},
            ]
            body: Dict[str, Any] = {
                "model": self.model_id,
                "messages": messages,
                "temperature": 0.3,
            }
            resp = await client.post(
                OPENROUTER_CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            completion = resp.json()
            state.total_llm_calls += 1

            memory_text = self._extract_text(completion)
            if memory_text:
                # Store via add_memory tool
                await self._executor.execute("add_memory", {
                    "content": memory_text,
                    "metadata": {
                        "symbol": state.primary_symbol,
                        "intent": state.intent.value,
                        "type": "orchestra_performance",
                    },
                })
                state.total_tool_calls += 1

                def _emit(t: str, d: str) -> None:
                    if emit:
                        try:
                            emit(t, d)
                        except Exception:
                            pass
                _emit("thinking", f"[Memory] stored performance note for {state.primary_symbol}")

        except Exception as exc:
            logger.debug("[Memory] Failed to store performance: %s", exc)


# ---------------------------------------------------------------------------
# Risk Section (Percussion)
# ---------------------------------------------------------------------------


class RiskSection(BaseSection):
    """
    The Percussion Section — assesses risk and maintains stability.
    Plays after Strategy, before Execution.
    Can BLOCK execution if risk is too high.
    """

    ROLE = SectionRole.RISK
    SYSTEM_PROMPT = RISK_SYSTEM_PROMPT
    ALLOWED_TOOLS = RISK_TOOLS
    MAX_ITERATIONS = 4

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build context from research + strategy
        research_brief = state.research.to_brief()
        strategy_brief = state.strategy.to_brief()

        enriched = (
            f"# Research Data\n{research_brief}\n\n"
            f"# Strategy Plan\n{strategy_brief}\n\n"
            f"# User Request\n{context_message}"
        )

        content = await super().perform(state, enriched, client, emit)

        # Extract risk assessment from LLM output
        self._extract_risk(state, content)

        return content

    def _extract_risk(self, state: OrchestraState, content: str) -> None:
        """Best-effort extraction of risk assessment from LLM output."""
        risk = state.risk
        text = content.lower()

        # Extract risk level
        if "extreme" in text:
            risk.risk_level = "extreme"
            risk.approved = False
        elif "high" in text and "risk" in text:
            risk.risk_level = "high"
            risk.risk_score = 0.75
        elif "medium" in text and "risk" in text:
            risk.risk_level = "medium"
            risk.risk_score = 0.5
        elif "low" in text and "risk" in text:
            risk.risk_level = "low"
            risk.risk_score = 0.25

        # Check for explicit block
        if "block" in text and ("execution" in text or "trade" in text):
            risk.approved = False
        if "approved: no" in text or "approved: false" in text:
            risk.approved = False

        risk.reasoning = content[:300] if content else ""


# ---------------------------------------------------------------------------
# Monitoring Section (Sound Engineer)
# ---------------------------------------------------------------------------


class MonitoringSection(BaseSection):
    """
    The Sound Engineer — checks system health before the performance.
    No tools needed — works from context and state inspection.
    """

    ROLE = SectionRole.MONITORING
    SYSTEM_PROMPT = MONITORING_SYSTEM_PROMPT
    ALLOWED_TOOLS = MONITORING_TOOLS
    MAX_ITERATIONS = 1  # Just one check

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build health context from available information
        health_context = self._build_health_context(state)
        enriched = f"# System Health Check\n{health_context}\n\n# User Request\n{context_message}"

        content = await super().perform(state, enriched, client, emit)

        # Parse health assessment
        self._extract_health(state, content)

        return content

    def _build_health_context(self, state: OrchestraState) -> str:
        """Build system context for the monitoring agent."""
        lines: List[str] = []

        # Check canvas read status
        if state.canvas_read:
            lines.append(f"Canvas: READABLE ({state.canvas_symbol} @ {state.canvas_timeframe})")
        else:
            lines.append("Canvas: NOT YET READ")

        # Check tool registry
        lines.append(f"Tool Registry: {len(self._registry)} tools registered")

        # Check for any section errors so far
        for name, section in state.sections.items():
            if section.status == SectionStatus.ERROR:
                lines.append(f"Section Error: {name} — {section.error}")

        lines.append(f"Total tool calls so far: {state.total_tool_calls}")
        lines.append(f"Total LLM calls so far: {state.total_llm_calls}")

        return "\n".join(lines) if lines else "No health data available."

    def _extract_health(self, state: OrchestraState, content: str) -> None:
        """Parse health assessment from LLM output."""
        health = state.system_health
        text = content.lower()

        # Try JSON parse first
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end + 1])
                if isinstance(parsed, dict):
                    health.healthy = parsed.get("healthy", True)
                    health.consumer_online = parsed.get("consumer_online", True)
                    health.latency_warnings = parsed.get("latency_warnings", [])
                    health.tool_errors = parsed.get("tool_errors", [])
                    health.notes = parsed.get("notes", [])
                    return
        except (json.JSONDecodeError, Exception):
            pass

        # Fallback to text analysis
        if "unhealthy" in text or "degraded" in text or "abort" in text:
            health.healthy = False
        if "consumer" in text and ("offline" in text or "not" in text):
            health.consumer_online = False


# ---------------------------------------------------------------------------
# Simulation Section (Rehearsal Director)
# ---------------------------------------------------------------------------


class SimulationSection(BaseSection):
    """
    The Rehearsal Director — tests strategy through scenario simulation.
    Plays after Strategy, before Execution (for execution intents).
    """

    ROLE = SectionRole.SIMULATION
    SYSTEM_PROMPT = SIMULATION_SYSTEM_PROMPT
    ALLOWED_TOOLS = SIMULATION_TOOLS
    MAX_ITERATIONS = 4

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build context from research + strategy
        research_brief = state.research.to_brief()
        strategy_brief = state.strategy.to_brief()

        enriched = (
            f"# Research Data\n{research_brief}\n\n"
            f"# Strategy Plan\n{strategy_brief}\n\n"
            f"# User Request\n{context_message}\n\n"
            f"Simulate scenarios for this strategy and report findings."
        )

        content = await super().perform(state, enriched, client, emit)

        # Extract simulation results
        self._extract_simulation(state, content)

        return content

    def _extract_simulation(self, state: OrchestraState, content: str) -> None:
        """Best-effort extraction of simulation results."""
        sim = state.simulation
        text = content.lower()

        # Mark that simulation was run
        sim.scenarios_tested = 3  # Default assumption

        # Try to extract win probability
        import re
        prob_match = re.search(r"win probability[:\s]*(\d+)%", text)
        if prob_match:
            sim.win_probability = int(prob_match.group(1)) / 100.0

        # Extract scenario count
        count_match = re.search(r"(\d+)\s*scenarios?\s*tested", text)
        if count_match:
            sim.scenarios_tested = int(count_match.group(1))

        # Store full content as reasoning
        if content:
            # Try to find best/worst/most likely sections
            for line in content.split("\n"):
                lower = line.lower().strip()
                if lower.startswith("best case"):
                    sim.best_case = line.strip()[:200]
                elif lower.startswith("worst case"):
                    sim.worst_case = line.strip()[:200]
                elif lower.startswith("most likely"):
                    sim.most_likely = line.strip()[:200]


# ---------------------------------------------------------------------------
# Critic Section (Music Critic)
# ---------------------------------------------------------------------------


class CriticSection(BaseSection):
    """
    The Music Critic — evaluates the quality of the orchestra's performance.
    Plays last, after all other sections have completed.
    """

    ROLE = SectionRole.CRITIC
    SYSTEM_PROMPT = CRITIC_SYSTEM_PROMPT
    ALLOWED_TOOLS = CRITIC_TOOLS
    MAX_ITERATIONS = 1  # Single evaluation pass

    async def perform(
        self,
        state: OrchestraState,
        context_message: str,
        client: httpx.AsyncClient,
        emit: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        # Build comprehensive context from all sections
        parts: List[str] = []

        # What was the user's request
        parts.append(f"# User Request\n{context_message}")

        # What each section produced
        for name, section in state.sections.items():
            if section.status == SectionStatus.DONE and section.content:
                parts.append(f"# {name.capitalize()} Section Output\n{section.content[:400]}")
            elif section.status == SectionStatus.ERROR:
                parts.append(f"# {name.capitalize()} Section — ERROR: {section.error}")
            elif section.status == SectionStatus.SKIPPED:
                parts.append(f"# {name.capitalize()} Section — SKIPPED")

        # Structured data summaries
        if state.research.symbol:
            parts.append(f"# Research Brief\n{state.research.to_brief()}")
        if state.strategy.bias:
            parts.append(f"# Strategy Brief\n{state.strategy.to_brief()}")
        if state.risk.risk_level:
            parts.append(f"# Risk Brief\n{state.risk.to_brief()}")

        # Performance stats
        parts.append(
            f"# Performance Stats\n"
            f"Total tool calls: {state.total_tool_calls}\n"
            f"Total LLM calls: {state.total_llm_calls}\n"
            f"Sections played: {sum(1 for s in state.sections.values() if s.status == SectionStatus.DONE)}"
        )

        enriched = "\n\n".join(parts)
        enriched += "\n\nEvaluate this performance. Return grade, strengths, weaknesses, improvements."

        content = await super().perform(state, enriched, client, emit)

        # Extract critic evaluation
        self._extract_evaluation(state, content)

        return content

    def _extract_evaluation(self, state: OrchestraState, content: str) -> None:
        """Best-effort extraction of critic evaluation."""
        critic = state.critic
        text = content.upper()

        # Extract grade
        import re
        grade_match = re.search(r"GRADE[:\s]*([ABCDF][+-]?)", text)
        if grade_match:
            critic.overall_grade = grade_match.group(1)
        elif any(f"GRADE: {g}" in text for g in "ABCDF"):
            for g in "ABCDF":
                if f"GRADE: {g}" in text:
                    critic.overall_grade = g
                    break

        critic.reasoning = content[:400] if content else ""


__all__ = [
    "BaseSection",
    "ResearchSection",
    "StrategySection",
    "ExecutionSection",
    "MemorySection",
    "RiskSection",
    "MonitoringSection",
    "SimulationSection",
    "CriticSection",
    "RESEARCH_TOOLS",
    "STRATEGY_TOOLS",
    "EXECUTION_TOOLS",
    "MEMORY_TOOLS",
    "RISK_TOOLS",
    "SIMULATION_TOOLS",
]
