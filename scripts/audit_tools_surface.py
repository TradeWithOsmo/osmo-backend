from __future__ import annotations

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from agent.Orchestrator.tool_registry import get_tool_registry
from agent.Orchestrator.tool_modes import classify_tool_mode


def _discover_public_async_functions(tools_root: Path) -> Dict[str, List[str]]:
    discovered: Dict[str, List[str]] = defaultdict(list)
    for path in tools_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        rel = str(path.relative_to(Path(backend_root))).replace("\\", "/")
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_"):
                discovered[node.name].append(rel)
    return dict(discovered)


def _discover_public_async_by_file(tools_root: Path) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = defaultdict(list)
    for path in tools_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        rel = str(path.relative_to(Path(backend_root))).replace("\\", "/")
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_"):
                mapping[rel].append(node.name)
    return dict(mapping)


def _render_registry_rows(registry: Dict[str, object]) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    for name, fn in sorted(registry.items()):
        mode = classify_tool_mode(name)
        impl = f"{getattr(fn, '__module__', '')}.{getattr(fn, '__qualname__', getattr(fn, '__name__', ''))}".strip(".")
        rows.append((name, mode, impl))
    return rows


def main() -> int:
    tools_root = Path(backend_root) / "agent" / "Tools"
    registry = get_tool_registry()
    discovered = _discover_public_async_functions(tools_root)
    discovered_by_file = _discover_public_async_by_file(tools_root)

    registry_names: Set[str] = set(registry.keys())
    discovered_names: Set[str] = set(discovered.keys())

    missing_in_registry = sorted(discovered_names - registry_names)
    missing_in_tools = sorted(registry_names - discovered_names)

    print("| Tool | Mode | Impl |")
    print("|---|---|---|")
    for name, mode, impl in _render_registry_rows(registry):
        print(f"| {name} | {mode} | {impl} |")

    print(f"\nRegistry Total: {len(registry_names)}")
    print(f"Tools Public Async Total: {len(discovered_names)}")

    print("\nMissing In Registry (public async exists in Tools but not exposed):")
    if missing_in_registry:
        for name in missing_in_registry:
            print(f"- {name} -> {', '.join(discovered[name])}")
    else:
        print("- none")

    print("\nMissing In Tools (registered tool not found as public async in Tools):")
    if missing_in_tools:
        for name in missing_in_tools:
            print(f"- {name}")
    else:
        print("- none")

    print("\nTools Files With Public Async Not Exposed In Registry (possible untouched in runtime path):")
    file_rows: List[Tuple[str, int, int, List[str]]] = []
    for rel_file, fn_names in sorted(discovered_by_file.items()):
        exposed = sorted(name for name in fn_names if name in registry_names)
        hidden = sorted(name for name in fn_names if name not in registry_names)
        if hidden:
            file_rows.append((rel_file, len(exposed), len(hidden), hidden))
    if not file_rows:
        print("- none")
    else:
        for rel_file, exposed_count, hidden_count, hidden in file_rows:
            print(
                f"- {rel_file}: exposed={exposed_count}, hidden={hidden_count}, hidden_names={', '.join(hidden)}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
