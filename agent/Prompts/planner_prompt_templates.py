from __future__ import annotations

import json
from typing import Any, Dict, List


PLANNER_IDENTITY_SNIPPET = (
    "You are the planning layer for a trading agent. "
    "Return one JSON object only. No markdown, no prose."
)

PLANNER_SCHEMA_SNIPPET = (
    '{'
    '"intent":"analysis|execution|education|smalltalk|other",'
    '"context":{'
    '"symbol":"optional BTC-USD style",'
    '"timeframe":"optional timeframe (1m,5m,15m,30m,1H,4H,1D,1W)",'
    '"requested_execution":false,'
    '"requested_news":false,'
    '"requested_sentiment":false,'
    '"requested_whales":false,'
    '"side":"optional long|short|buy|sell",'
    '"order_type":"optional market|limit|stop_limit",'
    '"amount_usd":null,'
    '"leverage":1,'
    '"limit_price":null,'
    '"stop_price":null,'
    '"tp":null,'
    '"sl":null'
    '},'
    '"tool_calls":[{"name":"tool_name","args":{},"reason":"short reason"}],'
    '"warnings":["optional"],'
    '"blocks":["optional"]'
    '}'
)

PLANNER_RULES_SNIPPET = (
    "Rules:\n"
    "- Keep tool_calls minimal and <= 6.\n"
    "- Analysis requests should prefer read tools.\n"
    "- Use write tools only on explicit mutation intent.\n"
    "- Do not invent tools outside allowed names."
)


def _compact_history(history: List[Dict[str, Any]] | None) -> List[Dict[str, str]]:
    output: List[Dict[str, str]] = []
    for item in (history or [])[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = str(item.get("content") or "")[:500]
        output.append({"role": role, "content": content})
    return output


def build_planner_system_prompt(
    allowed_tools: List[str],
    *,
    tool_modules_text: str = "",
    flow_templates_text: str = "",
) -> str:
    tool_names = ", ".join(sorted(str(name) for name in allowed_tools if str(name).strip()))
    prompt = (
        f"{PLANNER_IDENTITY_SNIPPET}\n\n"
        "Output schema:\n"
        f"{PLANNER_SCHEMA_SNIPPET}\n\n"
        f"Allowed tool names: {tool_names}\n"
        f"{PLANNER_RULES_SNIPPET}"
    )
    if tool_modules_text:
        prompt += f"\n\nTool modules (name/desc/input/output/example):\n{tool_modules_text}"
    if flow_templates_text:
        prompt += f"\n\nTool operation flow templates:\n{flow_templates_text}"
    return prompt


def build_planner_user_prompt(
    *,
    user_message: str,
    compact_tool_states: Dict[str, Any],
    history: List[Dict[str, Any]] | None,
) -> str:
    compact_history = _compact_history(history)
    return (
        f"user_message: {user_message}\n"
        f"tool_states: {json.dumps(compact_tool_states, ensure_ascii=False, default=str)}\n"
        f"history: {json.dumps(compact_history, ensure_ascii=False)}\n"
        "Return JSON now."
    )
