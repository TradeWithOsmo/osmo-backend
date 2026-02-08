from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from backend.agent.Core.agent_brain import AgentBrain


DEFAULT_HARD_PROMPT = (
    "You are trading perps only. Build a 24h and 7d probability tree for BTC-USD, SOL-USD, and USD/CHF. "
    "Use live evidence (price + technicals 1H/4H/1D), plus funding+orderbook for crypto, plus recent news/sentiment. "
    "Then produce a conditional hedge plan with strict risk caps, explicit data gaps, and confidence per symbol. "
    "If evidence conflicts, state invalidation logic without forcing precise levels."
)


def _quality_score(content: str) -> int:
    text = (content or "").lower()
    score = 0
    if any(sym in text for sym in ("btc", "sol", "usd/chf", "usd-chf")):
        score += 2
    if "confidence" in text:
        score += 2
    if "data gap" in text or "data gaps" in text:
        score += 2
    if "risk" in text:
        score += 2
    if "24h" in text and "7d" in text:
        score += 2
    return max(0, min(score, 10))


def _build_report(
    *,
    round_name: str,
    model_id: str,
    question: str,
    content: str,
    thoughts: List[str],
    phases: List[Dict[str, Any]],
    tool_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    tool_total = len(tool_results)
    tool_ok = 0
    for item in tool_results:
        ok = bool(item.get("ok"))
        has_data_error = isinstance(item.get("data"), dict) and bool(item["data"].get("error"))
        if ok and not has_data_error:
            tool_ok += 1
    tool_fail = max(0, tool_total - tool_ok)

    phase_total = len(phases)
    tool_call_phases = sum(1 for p in phases if str(p.get("name")) == "tool_call")
    tool_observe_phases = sum(1 for p in phases if str(p.get("name")) == "tool_observe")
    strict_pattern_ok = tool_call_phases == tool_observe_phases

    content_preview = (content or "").strip()
    thoughts_preview = [str(t) for t in (thoughts or [])[:6]]
    phase_preview = phases[:16]
    tool_names = [str(t.get("name")) for t in tool_results if t.get("name")]
    failed_tools = [str(t.get("name")) for t in tool_results if not bool(t.get("ok"))]

    return {
        "quality_score": _quality_score(content_preview),
        "tool_total": tool_total,
        "tool_ok": tool_ok,
        "tool_fail": tool_fail,
        "phase_total": phase_total,
        "tool_call_phases": tool_call_phases,
        "tool_observe_phases": tool_observe_phases,
        "strict_pattern_ok": strict_pattern_ok,
        "has_symbols": any(k in content_preview.lower() for k in ("btc", "sol", "usd/chf", "usd-chf")),
        "has_confidence": "confidence" in content_preview.lower(),
        "has_data_gap": ("data gap" in content_preview.lower()) or ("data gaps" in content_preview.lower()),
        "has_risk": "risk" in content_preview.lower(),
        "round": round_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_id,
        "question": question,
        "content_preview": content_preview,
        "thoughts_preview": thoughts_preview,
        "phase_preview": phase_preview,
        "failed_tools": failed_tools,
        "tool_names": tool_names,
        "status": "ok",
    }


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    tool_states: Dict[str, Any] = {
        "agent_engine": "deepagents",
        "agent_engine_strict": True,
        "plan_mode": True,
        "strict_react": True,
        "write": False,
        "retry_failed_tools": True,
        "model_timeout_sec": float(args.model_timeout_sec),
    }
    if args.max_tool_actions <= 0:
        tool_states["max_tool_actions"] = "none"
    else:
        tool_states["max_tool_actions"] = int(args.max_tool_actions)

    brain = AgentBrain(
        model_id=args.model_id,
        reasoning_effort=args.reasoning_effort,
        tool_states=tool_states,
        user_context={"user_id": args.user_id},
    )

    result = await brain.chat(user_message=args.prompt, history=[])
    runtime = result.get("runtime") if isinstance(result, dict) else {}
    phases = runtime.get("phases") if isinstance(runtime, dict) else []
    tool_results = runtime.get("tool_results") if isinstance(runtime, dict) else []

    report = _build_report(
        round_name=args.round_name,
        model_id=args.model_id,
        question=args.prompt,
        content=str(result.get("content") or ""),
        thoughts=[str(x) for x in (result.get("thoughts") or [])],
        phases=phases if isinstance(phases, list) else [],
        tool_results=tool_results if isinstance(tool_results, list) else [],
    )
    report["usage"] = result.get("usage", {})
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one E2E hard question against current agent runtime.")
    parser.add_argument("--model-id", default="groq/openai/gpt-oss-120b")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--prompt", default=DEFAULT_HARD_PROMPT)
    parser.add_argument("--round-name", default="manual_e2e")
    parser.add_argument(
        "--output",
        default="backend/agent/Evaluators/reasoning_tuning/reports_live_patch_r3_high_only/manual_e2e.json",
    )
    parser.add_argument("--model-timeout-sec", type=float, default=260.0)
    parser.add_argument("--max-tool-actions", type=int, default=0, help="<=0 means unlimited")
    parser.add_argument("--user-id", default="e2e_runner")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = asyncio.run(_run(args))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output_path), "quality_score": report.get("quality_score")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
