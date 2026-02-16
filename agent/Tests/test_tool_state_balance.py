import asyncio

from backend.agent.Guardrails.risk_gate import RiskGate
from backend.agent.Orchestrator.human_ops_policy import inject_human_ops_guards
from backend.agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator
from backend.agent.Orchestrator.runtime import AgenticTradingRuntime
from backend.agent.Orchestrator.tool_orchestrator import ToolOrchestrator
from backend.agent.Schema.agent_runtime import AgentPlan, PlanContext, ToolCall
from backend.agent.Tools.trade_execution import place_order


def test_tool_orchestrator_parses_write_flag_string_false() -> None:
    async def fake_set_symbol(symbol: str, target_symbol: str):
        return {"status": "completed", "symbol": symbol, "target_symbol": target_symbol}

    async def _run():
        orchestrator = ToolOrchestrator(registry={"set_symbol": fake_set_symbol})
        result = await orchestrator.run_tool(
            ToolCall(name="set_symbol", args={"symbol": "BTC-USD", "target_symbol": "ETH-USD"}),
            tool_states={"write": "false"},
        )
        assert result.ok is False
        assert (result.data or {}).get("required_mode") == "write"

    asyncio.run(_run())


def test_tool_orchestrator_parses_write_flag_string_true() -> None:
    async def fake_set_symbol(symbol: str, target_symbol: str):
        return {"status": "completed", "symbol": symbol, "target_symbol": target_symbol}

    async def _run():
        orchestrator = ToolOrchestrator(registry={"set_symbol": fake_set_symbol})
        result = await orchestrator.run_tool(
            ToolCall(name="set_symbol", args={"symbol": "BTC-USD", "target_symbol": "ETH-USD"}),
            tool_states={"write": "true"},
        )
        assert result.ok is True

    asyncio.run(_run())


def test_risk_gate_parses_execution_flag_string_false() -> None:
    outcome = RiskGate.evaluate("execute buy BTC now", tool_states={"execution": "false"})
    assert any("Auto Execution is disabled" in item for item in outcome["blocks"])


def test_trade_execution_parses_execution_flag_string_false() -> None:
    async def _run():
        result = await place_order(
            symbol="BTC-USD",
            side="buy",
            amount_usd=100.0,
            tool_states={"execution": "false", "user_address": "0xabc"},
        )
        assert "Execution disabled" in str(result.get("error") or "")

    asyncio.run(_run())


def test_runtime_symbol_sync_parses_write_flag_string_false() -> None:
    runtime = AgenticTradingRuntime()
    plan = AgentPlan(
        intent="analysis",
        context=PlanContext(symbol="ETH-USD", timeframe="1H"),
        tool_calls=[ToolCall(name="get_price", args={"symbol": "ETH-USD"}, reason="read price")],
    )

    runtime._ensure_symbol_sync_tool(
        plan=plan,
        tool_states={"market_symbol": "BTC-USD", "write": "false"},
    )

    assert plan.tool_calls[0].name == "get_price"
    assert any("Enable 'Allow Write'" in item for item in plan.warnings)


def test_human_ops_guard_parses_write_flag_string_false() -> None:
    plan = AgentPlan(
        intent="analysis",
        context=PlanContext(symbol="BTC-USD", timeframe="1H"),
        tool_calls=[ToolCall(name="set_timeframe", args={"symbol": "BTC-USD", "timeframe": "1H"})],
    )
    inserted = inject_human_ops_guards(
        plan=plan,
        tool_states={"write": "false"},
        available_tools={"verify_tradingview_state"},
    )
    assert inserted == 0
    assert len(plan.tool_calls) == 1


def test_reasoning_orchestrator_cache_gate_parses_write_flag() -> None:
    orchestrator = ReasoningOrchestrator()
    assert orchestrator._should_cache_plan("set symbol BTC", {"write": "false"}) is True
    assert orchestrator._should_cache_plan("set symbol BTC", {"write": "true"}) is False


def test_runtime_strict_write_verification_is_balance_aware() -> None:
    runtime = AgenticTradingRuntime()
    assert runtime._is_strict_write_verification_enabled({"reliability_mode": "balanced"}) is False
    assert runtime._is_strict_write_verification_enabled({"reliability_mode": "strict"}) is True
    assert runtime._is_strict_write_verification_enabled(
        {"reliability_mode": "strict", "strict_write_verification": "false"}
    ) is False
    assert runtime._is_strict_write_verification_enabled(
        {"reliability_mode": "balanced", "strict_write_verification": "true"}
    ) is True
