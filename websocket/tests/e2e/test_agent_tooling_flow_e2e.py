import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agent.Core.agent_brain import AgentBrain
from agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator
from agent.Orchestrator.trace_store import runtime_trace_store


@pytest.mark.asyncio
async def test_agent_brain_chat_uses_reflexion_runtime(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    brain = AgentBrain(
        model_id="openrouter/anthropic/claude-3.5-sonnet",
        tool_states={"strict_react": True, "max_tool_actions": 2},
    )

    reflexion_result = {
        "response": "reflexion answer",
        "state_summary": {
            "total_steps": 3,
            "actions": {"good": 2, "errors": 1, "retried": 1},
            "reflections": 1,
        },
        "tool_calls": 3,
    }

    reflexion_mock = AsyncMock(return_value=reflexion_result)
    monkeypatch.setattr(brain._reflexion_agent, "chat", reflexion_mock)

    result = await brain.chat("check btc", history=[])

    assert result["content"] == "reflexion answer"
    assert result["runtime"]["engine"] == "reflexion_agent"
    assert result["runtime"]["tool_calls_count"] == 3
    reflexion_mock.assert_awaited_once()


def test_reasoning_orchestrator_build_plan_has_context_and_steps():
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="Analyze BTC-USD on 1H and give setup",
        history=None,
        tool_states={
            "plan_mode": True,
            "market_symbol": "BTC-USD",
            "market_timeframe": "1H",
            "max_tool_actions": 2,
            "execution": False,
        },
    )

    assert plan.context.symbol == "BTC-USD"
    assert plan.context.timeframe == "1H"
    assert len(plan.tool_calls) == 2
    assert plan.intent in {"analysis", "execution"}


def test_runtime_trace_store_add_and_list_roundtrip():
    user = "0x1234567890abcdef1234567890abcdef12345678"
    session = "s-e2e-trace"

    runtime_trace_store.add(
        user_address=user,
        session_id=session,
        trace={"model_id": "test-model", "runtime": {"engine": "test"}},
    )

    traces = runtime_trace_store.list(
        user_address=user,
        session_id=session,
        limit=5,
    )

    assert len(traces) >= 1
    assert traces[-1]["model_id"] == "test-model"
    assert "timestamp" in traces[-1]
