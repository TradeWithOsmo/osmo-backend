import asyncio

from backend.agent.Orchestrator.tool_orchestrator import ToolOrchestrator
from backend.agent.Schema.agent_runtime import ToolCall


def test_tool_orchestrator_reports_explicit_timeout():
    async def slow_tool(symbol: str):
        _ = symbol
        await asyncio.sleep(0.05)
        return {"ok": True}

    async def _run():
        orchestrator = ToolOrchestrator(registry={"get_price": slow_tool}, tool_timeout_sec=0.01)
        result = await orchestrator.run_tool(
            ToolCall(name="get_price", args={"symbol": "BTC-USD"}, reason="timeout-test")
        )
        assert result.ok is False
        assert "tool timeout" in str(result.error or "").lower()
        assert (result.data or {}).get("code") == "tool_timeout"

    asyncio.run(_run())
