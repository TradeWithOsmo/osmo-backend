from __future__ import annotations

import os
import sys


backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from agent.Orchestrator.tool_registry import get_tool_registry
from agent.Orchestrator.tool_modes import classify_tool_mode
from agent.Orchestrator.tool_modules import get_tool_module


def main() -> int:
    reg = get_tool_registry()
    rows = []
    for name, fn in sorted(reg.items()):
        mod = getattr(fn, "__module__", "")
        qual = getattr(fn, "__qualname__", getattr(fn, "__name__", ""))
        mode = classify_tool_mode(name)
        module = get_tool_module(name)
        rows.append((name, mode, module.category, f"{mod}.{qual}".strip(".")))

    print("| Tool | Mode | Prompt Category | Impl |")
    print("|---|---|---|---|")
    for n, mode, prompt_category, impl in rows:
        print(f"| {n} | {mode} | {prompt_category} | {impl} |")

    mode_counts = {"read": 0, "write": 0, "nav": 0}
    for _, mode, _, _ in rows:
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    print(f"\nTotal: {len(rows)}")
    print(
        "Mode Count: "
        f"read={mode_counts.get('read', 0)} "
        f"write={mode_counts.get('write', 0)} "
        f"nav={mode_counts.get('nav', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
