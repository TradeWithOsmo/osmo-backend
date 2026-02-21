"""Bridge package so `agent.Tools.*` resolves to top-level `Tools/*`."""

from __future__ import annotations

from pathlib import Path

_root_tools = Path(__file__).resolve().parents[2] / "Tools"
if str(_root_tools) not in __path__:
    __path__.append(str(_root_tools))

_source_init = _root_tools / "__init__.py"
if _source_init.exists():
    code = _source_init.read_text(encoding="utf-8")
    exec(compile(code, str(_source_init), "exec"), globals())
