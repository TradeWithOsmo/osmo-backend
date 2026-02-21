"""Bridge package so `agent.Orchestrator.*` resolves to top-level modules."""

from __future__ import annotations

from pathlib import Path

_root_orchestrator = Path(__file__).resolve().parents[2] / "Orchestrator"
if str(_root_orchestrator) not in __path__:
    __path__.append(str(_root_orchestrator))

