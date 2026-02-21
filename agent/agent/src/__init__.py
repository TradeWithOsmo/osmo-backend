"""Bridge package so `agent.src.*` resolves to top-level `src/*`."""

from __future__ import annotations

from pathlib import Path

_root_src = Path(__file__).resolve().parents[2] / "src"
if str(_root_src) not in __path__:
    __path__.append(str(_root_src))

