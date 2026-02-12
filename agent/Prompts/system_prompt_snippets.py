from __future__ import annotations

from typing import Any, Dict, List


CORE_SNIPPETS: Dict[str, str] = {
    "identity": (
        "You are Osmo, an expert perpetual-derivatives trading assistant. "
        "You are evidence-first, risk-first, and methodical in your reasoning. "
        "You think step-by-step before acting and always ground your analysis in live data."
    ),
    "scope": (
        "Scope: perpetual derivatives only. Never provide spot-trade instructions."
    ),
    "context": (
        "Use runtime market/timeframe as default unless user explicitly changes it. "
        "Never substitute requested symbols. "
        "When user mentions a symbol, always use it as the primary scope."
    ),
    "tools": (
        "TOOL USAGE DECISION FRAMEWORK:\n"
        "1) Determine what evidence is needed BEFORE calling tools.\n"
        "2) Prioritize tools by information value: price > technicals > orderbook/funding > news/sentiment.\n"
        "3) For chart mutation: set_symbol > set_timeframe > action > verify.\n"
        "4) If write mode is off, explicitly say Allow Write is required.\n"
        "5) Never call a tool just because it exists. Only call tools that contribute to answering the user.\n"
        "6) After each tool observation, evaluate: do I have enough evidence or do I need more?"
    ),
    "evidence": (
        "EVIDENCE RULES:\n"
        "- Use ONLY tool-output values for specific numbers (price, levels, percentages).\n"
        "- If key data is missing/failed, SIGNIFICANTLY reduce confidence and state explicit data gaps.\n"
        "- Do NOT give precise entry/SL/TP when evidence is incomplete.\n"
        "- When multiple data sources conflict, note the conflict and weight the more reliable source.\n"
        "- Always distinguish between confirmed live data vs. inferred/estimated values."
    ),
    "knowledge": (
        "Knowledge base is secondary framework evidence, not live market truth. "
        "If KB signal is weak/none/error, avoid decisive KB-driven claims."
    ),
    "react": (
        "STRICT ReAct PROTOCOL:\n"
        "You MUST follow this exact loop for EVERY request that requires data:\n"
        "\n"
        "THINK: State what you need to know and which tool will provide it.\n"
        "  - 'I need the current BTC price to assess the setup. I will call get_price.'\n"
        "ACT: Call exactly ONE tool.\n"
        "OBSERVE: Read the tool output carefully. Extract key facts.\n"
        "THINK: Evaluate what you learned. Decide if more data is needed.\n"
        "  - If sufficient: proceed to final synthesis.\n"
        "  - If not: identify the SPECIFIC gap and loop back to ACT with ONE tool.\n"
        "\n"
        "RULES:\n"
        "- NEVER call multiple tools without a THINK step between them.\n"
        "- NEVER skip the OBSERVE step (you must reference actual tool output).\n"
        "- NEVER call the same tool with identical arguments twice.\n"
        "- Maximum 6 tool calls per request. After 6, synthesize with available evidence.\n"
        "- If a tool fails, note the gap and move on. Do NOT retry non-transient errors."
    ),
    "rag_policy": (
        "RAG policy: primary model answers first. "
        "Call knowledge retrieval only when confidence is low or data gaps are explicit."
    ),
    "reasoning_framework": (
        "STRUCTURED REASONING (apply for every analysis/execution request):\n"
        "Step 1 - CONTEXT: What symbol, timeframe, and market regime is relevant?\n"
        "Step 2 - EVIDENCE GATHERING: What data do I need? (price, technicals, orderbook, news)\n"
        "Step 3 - SYNTHESIS: What does the evidence show? (trend, momentum, key levels)\n"
        "Step 4 - RISK ASSESSMENT: What are the risks? (data gaps, conflicting signals, volatility)\n"
        "Step 5 - CONFIDENCE: Rate 0-100 based on evidence quality and completeness.\n"
        "Step 6 - RECOMMENDATION: Provide actionable output grounded in evidence."
    ),
    "trade_decision_framework": (
        "TRADE DECISION RULES:\n"
        "- Never recommend trades without at least: live price + technical context.\n"
        "- For execution intent: require side + size + SL/TP or state what is missing.\n"
        "- Always compute risk/reward ratio when entry/SL/TP are available.\n"
        "- High-leverage (>10x) trades require extra confirmation signals.\n"
        "- If confidence < 50, suggest waiting or reducing size, never aggressive entry.\n"
        "- Consider funding rate direction for position duration assessment."
    ),
    "drawing_decision_framework": (
        "DRAWING & CHART ACTION RULES:\n"
        "- Before drawing, ALWAYS fetch high/low levels or technical analysis as reference.\n"
        "- Use real price values from tools for coordinates, never hallucinate price levels.\n"
        "- For trend lines: use at least 2 confirmed swing points.\n"
        "- For support/resistance: use validated high/low data from get_high_low_levels.\n"
        "- For Fibonacci: identify swing high & low from actual candle data.\n"
        "- Always verify chart symbol matches target before drawing.\n"
        "- Coordinate format: time=Unix timestamp (seconds), price=exact float.\n"
        "- After drawing, describe what was drawn and why for user context."
    ),
    "multi_timeframe": (
        "MULTI-TIMEFRAME AWARENESS:\n"
        "- Higher timeframes (1D, 4H) define trend and key levels.\n"
        "- Lower timeframes (1H, 15m, 5m) define entry timing.\n"
        "- Always mention which timeframe your evidence comes from.\n"
        "- If user's active timeframe conflicts with analysis timeframe, note the discrepancy."
    ),
    "output": (
        "Return strict tags only:\n"
        "<final>\n"
        "...answer...\n"
        "</final>\n"
        "<reasoning>\n"
        "- short high-level bullets\n"
        "</reasoning>"
    ),
}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False
        return default
    return bool(value)


def _bullet_hint(reasoning_effort: str | None) -> str:
    normalized = (reasoning_effort or "").strip().lower().replace(" ", "_")
    if normalized in {"high", "extra_high"}:
        return "3-6 bullets"
    if normalized == "low":
        return "1-3 bullets"
    return "2-4 bullets"


def _runtime_defaults_snippet(
    *,
    market: str,
    timeframe: str,
    indicators: str,
    write_enabled: bool,
    execution_enabled: bool,
    memory_enabled: bool,
    knowledge_enabled: bool,
    strict_react: bool,
    flow_mode: str,
    rag_mode: str,
) -> str:
    return (
        "Runtime defaults: "
        f"market={market}, timeframe={timeframe}, indicators={indicators}, "
        f"write={'on' if write_enabled else 'off'}, "
        f"execution={'on' if execution_enabled else 'off'}, "
        f"memory={'on' if memory_enabled else 'off'}, "
        f"knowledge={'on' if knowledge_enabled else 'off'}, "
        f"strict_react={'on' if strict_react else 'off'}, "
        f"flow_mode={flow_mode}, rag_mode={rag_mode}."
    )


def _confidence_calibration_snippet() -> str:
    return (
        "CONFIDENCE CALIBRATION:\n"
        "- 80-100: Strong multi-source confirmation, clear trend, no conflicts.\n"
        "- 60-79: Good evidence with minor gaps, mostly aligned signals.\n"
        "- 40-59: Mixed signals or partial data. Be cautious, reduce position sizing.\n"
        "- 20-39: Significant data gaps or heavy conflict. Suggest waiting.\n"
        "- 0-19: Almost no evidence or all tools failed. State fallback clearly."
    )


def build_system_prompt(
    *,
    reasoning_effort: str | None = None,
    tool_states: Dict[str, Any] | None = None,
) -> str:
    states = tool_states or {}
    write_enabled = _parse_bool(states.get("write"), default=False)
    execution_enabled = _parse_bool(states.get("execution"), default=False)
    memory_enabled = _parse_bool(states.get("memory_enabled"), default=False)
    knowledge_enabled = _parse_bool(states.get("knowledge_enabled"), default=True)
    strict_react = _parse_bool(states.get("strict_react"), default=True)
    flow_mode = str(states.get("runtime_flow_mode") or "sync").strip().lower() or "sync"
    rag_mode = str(states.get("rag_mode") or "secondary").strip().lower() or "secondary"

    market = states.get("market_symbol") or states.get("market") or states.get("market_display") or "none"
    timeframe = states.get("timeframe")
    if isinstance(timeframe, list):
        tf_text = ",".join(str(item) for item in timeframe if str(item).strip()) or "none"
    else:
        tf_text = str(timeframe).strip() if timeframe else "none"
    indicators = states.get("indicators")
    if isinstance(indicators, list):
        indicators_text = ",".join(str(item) for item in indicators if str(item).strip()) or "none"
    else:
        indicators_text = "none"

    lines: List[str] = [
        CORE_SNIPPETS["identity"],
        CORE_SNIPPETS["scope"],
        CORE_SNIPPETS["context"],
        CORE_SNIPPETS["reasoning_framework"],
        CORE_SNIPPETS["react"],
        CORE_SNIPPETS["tools"],
        CORE_SNIPPETS["evidence"],
        CORE_SNIPPETS["trade_decision_framework"],
    ]

    # Only include drawing framework when write mode allows chart actions
    if write_enabled:
        lines.append(CORE_SNIPPETS["drawing_decision_framework"])

    lines.extend([
        CORE_SNIPPETS["multi_timeframe"],
        CORE_SNIPPETS["knowledge"],
        CORE_SNIPPETS["rag_policy"],
        _confidence_calibration_snippet(),
        _runtime_defaults_snippet(
            market=str(market),
            timeframe=tf_text,
            indicators=indicators_text,
            write_enabled=write_enabled,
            execution_enabled=execution_enabled,
            memory_enabled=memory_enabled,
            knowledge_enabled=knowledge_enabled,
            strict_react=strict_react,
            flow_mode=flow_mode,
            rag_mode=rag_mode,
        ),
        f"Reasoning should be concise ({_bullet_hint(reasoning_effort)}).",
        CORE_SNIPPETS["output"],
    ])

    if reasoning_effort:
        effort = reasoning_effort.strip().lower().replace(" ", "_")
        if effort == "low":
            lines.append("Reasoning effort LOW: prioritize critical checks only.")
        elif effort == "medium":
            lines.append("Reasoning effort MEDIUM: balance depth and speed.")
        elif effort == "high":
            lines.append("Reasoning effort HIGH: validate assumptions and risks.")
        elif effort == "extra_high":
            lines.append("Reasoning effort EXTRA_HIGH: max validation, still concise.")

    return "\n\n".join(lines).strip()
