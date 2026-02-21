"""Bridge package so `agent.Config.*` resolves to top-level `Config/*`."""

from __future__ import annotations

from pathlib import Path

_root_config = Path(__file__).resolve().parents[2] / "Config"
if str(_root_config) not in __path__:
    __path__.append(str(_root_config))

