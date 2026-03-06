"""
Orchestra State

Shared state container for the multi-agent orchestra system.
Each section (Research, Strategy, Execution) writes its findings here,
and the Maestro reads from it to coordinate the flow.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrchestraIntent(str, Enum):
    """What the user is asking for — determines which sections play."""

    ANALYSIS = "analysis"        # Full analysis: Research → Strategy
    EXECUTION = "execution"      # Trade action: Research → Strategy → Execution
    RESEARCH = "research"        # Info gathering: Research only (web gate open)
    QUICK = "quick"              # Simple question: direct LLM answer, no sections
    MONITOR = "monitor"          # Position check / portfolio review


class SectionRole(str, Enum):
    """Identifies which orchestra section produced a piece of output."""

    MAESTRO = "maestro"
    MEMORY = "memory"           # Librarian — retrieves past context
    RESEARCH = "research"       # Violin — data gathering
    STRATEGY = "strategy"       # Composer — strategy formulation
    RISK = "risk"               # Percussion — risk assessment
    SIMULATION = "simulation"   # Rehearsal Director — scenario testing
    EXECUTION = "execution"     # Brass — trade execution
    MONITORING = "monitoring"   # Sound Engineer — system health
    CRITIC = "critic"           # Music Critic — performance evaluation


class SectionStatus(str, Enum):
    """Status of a section's performance."""

    PENDING = "pending"
    PLAYING = "playing"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Section output records
# ---------------------------------------------------------------------------


@dataclass
class SectionOutput:
    """Structured output from one orchestra section."""

    role: SectionRole
    status: SectionStatus = SectionStatus.PENDING
    content: str = ""                                    # LLM text output
    data: Dict[str, Any] = field(default_factory=dict)   # Structured findings
    tool_calls_made: int = 0
    elapsed_ms: float = 0.0
    error: str = ""


@dataclass
class ResearchFindings:
    """Structured research data passed from Violin to Composer."""

    symbol: str = ""
    asset_type: str = "crypto"

    # Price context
    price: Optional[float] = None
    change_pct_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None

    # Technical analysis
    rsi: Optional[float] = None
    macd_signal: str = ""           # "bullish_cross", "bearish_cross", "neutral"
    ta_summary: str = ""
    patterns: List[str] = field(default_factory=list)

    # Key levels
    support: Optional[float] = None
    resistance: Optional[float] = None
    midpoint: Optional[float] = None

    # Canvas state
    canvas_indicators: List[str] = field(default_factory=list)
    canvas_timeframe: str = ""

    # External research (when web gate is open)
    news_summary: str = ""
    sentiment: str = ""             # "bullish", "bearish", "neutral", "mixed"

    # Orderbook / funding
    funding_rate: Optional[float] = None
    orderbook_bias: str = ""        # "buy_heavy", "sell_heavy", "balanced"

    def to_brief(self) -> str:
        """Compact text summary for passing to next section."""
        lines: List[str] = []
        if self.symbol:
            lines.append(f"Symbol: {self.symbol} ({self.asset_type})")
        if self.price is not None:
            change = f" ({self.change_pct_24h:+.2f}%)" if self.change_pct_24h else ""
            lines.append(f"Price: ${self.price:,.4f}{change}")
        if self.rsi is not None:
            lines.append(f"RSI(14): {self.rsi:.1f}")
        if self.macd_signal:
            lines.append(f"MACD: {self.macd_signal}")
        if self.ta_summary:
            lines.append(f"TA: {self.ta_summary[:200]}")
        if self.patterns:
            lines.append(f"Patterns: {', '.join(self.patterns[:5])}")
        if self.support is not None and self.resistance is not None:
            lines.append(f"Support: ${self.support:,.4f} | Resistance: ${self.resistance:,.4f}")
        if self.canvas_indicators:
            lines.append(f"Canvas: {', '.join(self.canvas_indicators[:6])} @ {self.canvas_timeframe}")
        if self.news_summary:
            lines.append(f"News: {self.news_summary[:200]}")
        if self.sentiment:
            lines.append(f"Sentiment: {self.sentiment}")
        if self.funding_rate is not None:
            lines.append(f"Funding: {self.funding_rate:.4f}%")
        if self.orderbook_bias:
            lines.append(f"Orderbook: {self.orderbook_bias}")
        return "\n".join(lines) if lines else "No research data available."


@dataclass
class StrategyPlan:
    """Structured strategy output passed from Composer to Brass."""

    bias: str = ""                  # "long", "short", "neutral", "wait"
    confidence: float = 0.0         # 0.0 - 1.0
    timeframe: str = ""
    reasoning: str = ""

    # Entry plan
    entry_price: Optional[float] = None
    entry_condition: str = ""       # "break above 68500", "retest of 65000"

    # Exit plan
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_reward: Optional[float] = None

    # Validation / Invalidation
    validation_conditions: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)

    # Indicators to use
    indicators_needed: List[str] = field(default_factory=list)
    drawings_needed: List[str] = field(default_factory=list)

    # Next move scenarios
    if_valid: str = ""              # What to do if setup plays out
    if_invalid: str = ""            # What to do if setup fails

    def to_brief(self) -> str:
        """Compact text summary for passing to execution section."""
        lines: List[str] = []
        if self.bias:
            lines.append(f"Bias: {self.bias.upper()} (confidence: {self.confidence:.0%})")
        if self.reasoning:
            lines.append(f"Reasoning: {self.reasoning[:300]}")
        if self.entry_price is not None:
            lines.append(f"Entry: ${self.entry_price:,.4f}")
        if self.entry_condition:
            lines.append(f"Entry Condition: {self.entry_condition}")
        if self.take_profit is not None and self.stop_loss is not None:
            lines.append(f"TP: ${self.take_profit:,.4f} | SL: ${self.stop_loss:,.4f}")
        if self.risk_reward is not None:
            lines.append(f"R:R = {self.risk_reward:.2f}")
        if self.validation_conditions:
            lines.append("Validation: " + "; ".join(self.validation_conditions[:3]))
        if self.invalidation_conditions:
            lines.append("Invalidation: " + "; ".join(self.invalidation_conditions[:3]))
        if self.if_valid:
            lines.append(f"If valid: {self.if_valid}")
        if self.if_invalid:
            lines.append(f"If invalid: {self.if_invalid}")
        return "\n".join(lines) if lines else "No strategy available."


@dataclass
class MemoryContext:
    """Context retrieved by the Memory Agent (Librarian) from past sessions."""

    past_analyses: List[str] = field(default_factory=list)
    past_strategies: List[str] = field(default_factory=list)
    relevant_memories: List[str] = field(default_factory=list)
    knowledge_snippets: List[str] = field(default_factory=list)

    def to_brief(self) -> str:
        lines: List[str] = []
        if self.past_analyses:
            lines.append("Past Analyses:")
            for a in self.past_analyses[:3]:
                lines.append(f"  - {a[:150]}")
        if self.past_strategies:
            lines.append("Past Strategies:")
            for s in self.past_strategies[:3]:
                lines.append(f"  - {s[:150]}")
        if self.relevant_memories:
            lines.append("Relevant Memories:")
            for m in self.relevant_memories[:5]:
                lines.append(f"  - {m[:150]}")
        if self.knowledge_snippets:
            lines.append("Knowledge:")
            for k in self.knowledge_snippets[:3]:
                lines.append(f"  - {k[:150]}")
        return "\n".join(lines) if lines else ""


@dataclass
class RiskAssessment:
    """Risk evaluation produced by the Risk Agent (Percussion)."""

    risk_level: str = ""            # "low", "medium", "high", "extreme"
    risk_score: float = 0.0         # 0.0 - 1.0
    max_position_size_usd: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    approved: bool = True           # False = Risk Agent blocks execution
    reasoning: str = ""

    # Specific risk factors
    volatility_risk: str = ""       # "low", "medium", "high"
    correlation_risk: str = ""      # exposure to correlated assets
    funding_risk: str = ""          # funding rate concern
    liquidity_risk: str = ""        # orderbook depth concern

    def to_brief(self) -> str:
        lines: List[str] = []
        if self.risk_level:
            lines.append(f"Risk Level: {self.risk_level.upper()} (score: {self.risk_score:.0%})")
        if not self.approved:
            lines.append("BLOCKED: Risk Agent has blocked execution")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings[:5]:
                lines.append(f"  - {w}")
        if self.max_position_size_usd is not None:
            lines.append(f"Max Position Size: ${self.max_position_size_usd:,.2f}")
        if self.reasoning:
            lines.append(f"Reasoning: {self.reasoning[:200]}")
        return "\n".join(lines) if lines else "No risk assessment."


@dataclass
class SimulationResult:
    """Scenario testing output from the Simulation Agent (Rehearsal Director)."""

    scenarios_tested: int = 0
    best_case: str = ""
    worst_case: str = ""
    most_likely: str = ""
    expected_value: Optional[float] = None      # Expected PnL
    win_probability: Optional[float] = None     # 0.0 - 1.0
    recommendations: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    def to_brief(self) -> str:
        lines: List[str] = []
        if self.scenarios_tested > 0:
            lines.append(f"Scenarios Tested: {self.scenarios_tested}")
        if self.win_probability is not None:
            lines.append(f"Win Probability: {self.win_probability:.0%}")
        if self.best_case:
            lines.append(f"Best Case: {self.best_case[:150]}")
        if self.worst_case:
            lines.append(f"Worst Case: {self.worst_case[:150]}")
        if self.most_likely:
            lines.append(f"Most Likely: {self.most_likely[:150]}")
        if self.weaknesses:
            lines.append("Weaknesses: " + "; ".join(self.weaknesses[:3]))
        if self.recommendations:
            lines.append("Recommendations: " + "; ".join(self.recommendations[:3]))
        return "\n".join(lines) if lines else "No simulation data."


@dataclass
class CriticEvaluation:
    """Post-performance critique from the Critic Agent."""

    overall_grade: str = ""         # "A", "B", "C", "D", "F"
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    reasoning: str = ""

    def to_brief(self) -> str:
        lines: List[str] = []
        if self.overall_grade:
            lines.append(f"Grade: {self.overall_grade}")
        if self.strengths:
            lines.append("Strengths: " + "; ".join(self.strengths[:3]))
        if self.weaknesses:
            lines.append("Weaknesses: " + "; ".join(self.weaknesses[:3]))
        if self.improvements:
            lines.append("Improvements: " + "; ".join(self.improvements[:3]))
        return "\n".join(lines) if lines else ""


@dataclass
class SystemHealth:
    """System health snapshot from the Monitoring Agent (Sound Engineer)."""

    healthy: bool = True
    latency_warnings: List[str] = field(default_factory=list)
    tool_errors: List[str] = field(default_factory=list)
    consumer_online: bool = True    # TradingView frontend connected
    notes: List[str] = field(default_factory=list)

    def to_brief(self) -> str:
        status = "HEALTHY" if self.healthy else "DEGRADED"
        lines = [f"System: {status}"]
        if not self.consumer_online:
            lines.append("WARNING: TradingView consumer OFFLINE — chart writes will fail")
        if self.latency_warnings:
            for w in self.latency_warnings[:3]:
                lines.append(f"  Latency: {w}")
        if self.tool_errors:
            for e in self.tool_errors[:3]:
                lines.append(f"  Error: {e}")
        return "\n".join(lines) if lines else "System healthy."


# ---------------------------------------------------------------------------
# Main state container
# ---------------------------------------------------------------------------


@dataclass
class OrchestraState:
    """
    Full state for one orchestra performance (one user message turn).

    The Maestro creates this, sections read/write to it,
    and the Maestro reads the final result.
    """

    # Intent & context
    intent: OrchestraIntent = OrchestraIntent.ANALYSIS
    user_message: str = ""
    primary_symbol: str = ""
    target_symbols: List[str] = field(default_factory=list)
    timeframe: str = ""

    # Web search gate — controlled by Maestro
    web_gate_open: bool = False

    # Section outputs
    sections: Dict[str, SectionOutput] = field(default_factory=dict)

    # Structured findings passed between sections
    memory_context: MemoryContext = field(default_factory=MemoryContext)
    research: ResearchFindings = field(default_factory=ResearchFindings)
    strategy: StrategyPlan = field(default_factory=StrategyPlan)
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    simulation: SimulationResult = field(default_factory=SimulationResult)
    critic: CriticEvaluation = field(default_factory=CriticEvaluation)
    system_health: SystemHealth = field(default_factory=SystemHealth)

    # Canvas state (shared across sections)
    canvas_read: bool = False
    canvas_indicators: List[str] = field(default_factory=list)
    canvas_symbol: str = ""
    canvas_timeframe: str = ""

    # Session metadata
    session_id: str = ""
    user_address: str = ""
    created_at: float = field(default_factory=time.time)

    # Performance tracking
    total_tool_calls: int = 0
    total_llm_calls: int = 0

    # -------------------------------------------------------------------------
    # Section management
    # -------------------------------------------------------------------------

    def init_section(self, role: SectionRole) -> SectionOutput:
        """Initialize a section output tracker."""
        output = SectionOutput(role=role, status=SectionStatus.PLAYING)
        self.sections[role.value] = output
        return output

    def get_section(self, role: SectionRole) -> Optional[SectionOutput]:
        return self.sections.get(role.value)

    def complete_section(
        self, role: SectionRole, content: str = "", data: Optional[Dict[str, Any]] = None,
        tool_calls: int = 0, elapsed_ms: float = 0.0
    ) -> None:
        output = self.sections.get(role.value)
        if output:
            output.status = SectionStatus.DONE
            output.content = content
            output.data = data or {}
            output.tool_calls_made = tool_calls
            output.elapsed_ms = elapsed_ms

    def fail_section(self, role: SectionRole, error: str) -> None:
        output = self.sections.get(role.value)
        if output:
            output.status = SectionStatus.ERROR
            output.error = error

    def skip_section(self, role: SectionRole) -> None:
        output = self.sections.get(role.value, SectionOutput(role=role))
        output.status = SectionStatus.SKIPPED
        self.sections[role.value] = output

    # -------------------------------------------------------------------------
    # Canvas state (shared)
    # -------------------------------------------------------------------------

    def update_canvas(
        self, symbol: str, timeframe: str, indicators: List[str]
    ) -> None:
        self.canvas_read = True
        self.canvas_symbol = symbol.upper().strip()
        self.canvas_timeframe = timeframe.strip()
        self.canvas_indicators = list(indicators)

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        sections_summary = {}
        for name, output in self.sections.items():
            sections_summary[name] = {
                "status": output.status.value,
                "tool_calls": output.tool_calls_made,
                "elapsed_ms": round(output.elapsed_ms, 1),
                "error": output.error or None,
            }

        return {
            "intent": self.intent.value,
            "primary_symbol": self.primary_symbol,
            "target_symbols": self.target_symbols,
            "web_gate": self.web_gate_open,
            "sections": sections_summary,
            "canvas": {
                "read": self.canvas_read,
                "symbol": self.canvas_symbol,
                "timeframe": self.canvas_timeframe,
                "indicators": self.canvas_indicators,
            },
            "total_tool_calls": self.total_tool_calls,
            "total_llm_calls": self.total_llm_calls,
            "research_brief": self.research.to_brief() if self.research.symbol else None,
            "strategy_brief": self.strategy.to_brief() if self.strategy.bias else None,
            "risk_brief": self.risk.to_brief() if self.risk.risk_level else None,
            "simulation_brief": self.simulation.to_brief() if self.simulation.scenarios_tested else None,
            "critic_brief": self.critic.to_brief() if self.critic.overall_grade else None,
            "system_health": self.system_health.to_brief(),
        }


__all__ = [
    "OrchestraIntent",
    "SectionRole",
    "SectionStatus",
    "SectionOutput",
    "ResearchFindings",
    "StrategyPlan",
    "MemoryContext",
    "RiskAssessment",
    "SimulationResult",
    "CriticEvaluation",
    "SystemHealth",
    "OrchestraState",
]
