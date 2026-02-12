from __future__ import annotations

import ast
from pathlib import Path
from typing import Set


ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1] / "Orchestrator"


def _parse_string_set(file_path: Path, var_name: str) -> Set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    result: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target_names = [node.target.id] if isinstance(node.target, ast.Name) else []
            value = node.value
        else:
            continue
        if var_name not in target_names:
            continue
        if isinstance(value, ast.Set):
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    result.add(element.value)
    return result


def _parse_returned_registry_keys(file_path: Path) -> Set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    keys: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key_node in node.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.add(key_node.value)
    return keys


def _parse_module_keys(file_path: Path) -> Set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    keys: Set[str] = set()
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
                keys.add(key_node.value)
    return keys


def test_write_tools_have_registry_and_module_coverage() -> None:
    write_tools = _parse_string_set(ORCHESTRATOR_DIR / "tool_modes.py", "WRITE_TOOL_NAMES")
    registry_tools = _parse_returned_registry_keys(ORCHESTRATOR_DIR / "tool_registry.py")
    module_tools = _parse_module_keys(ORCHESTRATOR_DIR / "tool_modules.py")

    missing_in_registry = sorted(write_tools - registry_tools)
    missing_in_modules = sorted(write_tools - module_tools)

    assert not missing_in_registry, (
        "WRITE_TOOL_NAMES contains tools not present in registry: "
        + ", ".join(missing_in_registry)
    )
    assert not missing_in_modules, (
        "WRITE_TOOL_NAMES contains tools missing in tool_modules metadata: "
        + ", ".join(missing_in_modules)
    )


def test_registry_tools_have_module_metadata() -> None:
    registry_tools = _parse_returned_registry_keys(ORCHESTRATOR_DIR / "tool_registry.py")
    module_tools = _parse_module_keys(ORCHESTRATOR_DIR / "tool_modules.py")

    missing_modules = sorted(registry_tools - module_tools)
    assert not missing_modules, (
        "Registry tools missing in tool_modules metadata: " + ", ".join(missing_modules)
    )
