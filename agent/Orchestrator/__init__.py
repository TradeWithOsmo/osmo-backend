"""
Orchestrator module

The full trading orchestra:
  - MaestroOrchestrator: Multi-agent conductor
  - ResearchSection (Violin): Data gathering
  - StrategySection (Composer): Strategy formulation
  - ExecutionSection (Brass): Trade execution
  - MemorySection (Librarian): Past context retrieval
  - RiskSection (Percussion): Risk assessment
  - MonitoringSection (Sound Engineer): System health
  - SimulationSection (Rehearsal Director): Scenario testing
  - CriticSection (Music Critic): Performance evaluation

Also includes:
  - ReasoningOrchestrator: Lightweight plan preview
  - ExecutionAdapter: Bridge to order/trade services
  - runtime_trace_store: Session diagnostics
"""

from .execution_adapter import ExecutionAdapter
from .maestro import MaestroOrchestrator
from .orchestra_state import (
    CriticEvaluation,
    MemoryContext,
    OrchestraIntent,
    OrchestraState,
    RiskAssessment,
    SectionRole,
    SectionStatus,
    SimulationResult,
    SystemHealth,
)
from .reasoning_orchestrator import ReasoningOrchestrator
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
from .trace_store import runtime_trace_store

__all__ = [
    "runtime_trace_store",
    "ReasoningOrchestrator",
    "ExecutionAdapter",
    "MaestroOrchestrator",
    "OrchestraIntent",
    "OrchestraState",
    "SectionRole",
    "SectionStatus",
    "MemoryContext",
    "RiskAssessment",
    "SimulationResult",
    "CriticEvaluation",
    "SystemHealth",
    "ResearchSection",
    "StrategySection",
    "ExecutionSection",
    "MemorySection",
    "RiskSection",
    "MonitoringSection",
    "SimulationSection",
    "CriticSection",
]
