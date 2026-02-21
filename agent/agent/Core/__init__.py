"""Bridge package so `agent.Core.*` resolves to top-level `Core/*`."""

from __future__ import annotations

from pathlib import Path

_root_core = Path(__file__).resolve().parents[2] / "Core"
if str(_root_core) not in __path__:
    __path__.append(str(_root_core))

