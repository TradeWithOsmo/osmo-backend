from __future__ import annotations

import ast
from pathlib import Path
from typing import Set


AGENT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = AGENT_DIR / "Tools" / "tradingview"
ORCH_DIR = AGENT_DIR / "Orchestrator"


def _public_async_defs(file_path: Path) -> Set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    out: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_"):
            out.add(node.name)
    return out


def _registry_keys() -> Set[str]:
    tree = ast.parse((ORCH_DIR / "tool_registry.py").read_text(encoding="utf-8"))
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key_node in node.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    out.add(key_node.value)
    return out


def _tool_module_keys() -> Set[str]:
    tree = ast.parse((ORCH_DIR / "tool_modules.py").read_text(encoding="utf-8"))
    out: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target_names = [node.target.id] if isinstance(node.target, ast.Name) else []
            value = node.value
        else:
            continue
        if "_TOOL_MODULES" not in target_names or not isinstance(value, ast.Dict):
            continue
        for key_node in value.keys:
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                out.add(key_node.value)
    return out


def test_tradingview_public_async_tools_are_registered_and_documented() -> None:
    tool_files = [
        TOOLS_DIR / "actions.py",
        TOOLS_DIR / "drawing" / "actions.py",
        TOOLS_DIR / "nav" / "actions.py",
    ]
    tradingview_tools: Set[str] = set()
    for file_path in tool_files:
        tradingview_tools |= _public_async_defs(file_path)

    registry = _registry_keys()
    modules = _tool_module_keys()

    missing_registry = sorted(tradingview_tools - registry)
    missing_modules = sorted(tradingview_tools - modules)

    assert not missing_registry, (
        "TradingView public async tools missing in registry: " + ", ".join(missing_registry)
    )
    assert not missing_modules, (
        "TradingView public async tools missing in tool_modules metadata: " + ", ".join(missing_modules)
    )

