import asyncio

from langchain_core.messages import AIMessage

from backend.agent.Guardrails.risk_gate import RiskGate
from backend.agent.Orchestrator.planner import build_plan
from backend.agent.Orchestrator.runtime import AgenticTradingRuntime
from backend.agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator
from backend.agent.Orchestrator.tool_orchestrator import ToolOrchestrator
from backend.agent.Schema.agent_runtime import ToolCall, AgentPlan, PlanContext


def test_build_plan_detects_symbol_and_analysis_tools():
    plan = build_plan("analyze BTC 1h with RSI and whale flow")
    assert plan.context.symbol == "BTC-USD"
    names = [c.name for c in plan.tool_calls]
    assert "get_price" in names
    assert "get_technical_analysis" in names
    assert "get_whale_activity" in names


def test_build_plan_indicator_flow_add_then_get_when_write_enabled():
    plan = build_plan(
        "analyze BTC 1h",
        tool_states={"write": True, "indicators": ["RSI"]},
    )
    names = [c.name for c in plan.tool_calls]
    assert "add_indicator" in names
    assert "get_active_indicators" in names
    assert names.index("add_indicator") < names.index("get_active_indicators")


def test_build_plan_skips_tools_for_smalltalk():
    plan = build_plan("hello there")
    assert plan.tool_calls == []


def test_build_plan_uses_market_microstructure_tools_when_requested():
    plan = build_plan("show BTC orderbook and funding rate")
    names = [c.name for c in plan.tool_calls]
    assert "get_price" in names
    assert "get_orderbook" in names
    assert "get_funding_rate" in names


def test_build_plan_warns_when_chart_write_requested_but_write_disabled():
    plan = build_plan(
        "analyze BTC and apply RSI",
        tool_states={"write": False, "indicators": ["RSI"]},
    )
    names = [c.name for c in plan.tool_calls]
    assert "add_indicator" not in names
    assert "get_active_indicators" in names
    assert any("write mode is disabled" in item.lower() for item in plan.warnings)


def test_build_plan_uses_user_symbol_even_when_market_chip_is_different():
    plan = build_plan(
        "gw minta soll",
        tool_states={"market_symbol": "BTC-USD"},
    )
    assert plan.context.symbol == "SOL-USD"
    price_calls = [c for c in plan.tool_calls if c.name == "get_price"]
    assert len(price_calls) == 1
    assert price_calls[0].args.get("symbol") == "SOL"


def test_build_plan_auto_sets_symbol_before_price_when_symbol_changes_and_write_enabled():
    plan = build_plan(
        "check sol price",
        tool_states={"market_symbol": "BTC-USD", "write": True},
    )
    names = [c.name for c in plan.tool_calls]
    assert "set_symbol" in names
    assert "get_price" in names
    assert names.index("set_symbol") < names.index("get_price")
    set_symbol_calls = [c for c in plan.tool_calls if c.name == "set_symbol"]
    assert len(set_symbol_calls) == 1
    assert set_symbol_calls[0].args.get("symbol") == "BTC-USD"
    assert set_symbol_calls[0].args.get("target_symbol") == "SOL-USD"


def test_build_plan_indicator_flow_switches_symbol_then_adds_indicator():
    plan = build_plan(
        "analyze SOL 1h",
        tool_states={"market_symbol": "BTC-USD", "write": True, "indicators": ["RSI"]},
    )
    names = [c.name for c in plan.tool_calls]
    assert "set_symbol" in names
    assert "add_indicator" in names
    assert "get_active_indicators" in names
    assert names.index("set_symbol") < names.index("add_indicator")
    assert names.index("add_indicator") < names.index("get_active_indicators")


def test_build_plan_warns_symbol_mismatch_when_write_disabled():
    plan = build_plan(
        "check sol price",
        tool_states={"market_symbol": "BTC-USD", "write": False},
    )
    names = [c.name for c in plan.tool_calls]
    assert "set_symbol" not in names
    assert "get_price" in names
    assert any("allow write" in w.lower() and "differs from active chart" in w.lower() for w in plan.warnings)


def test_build_plan_skips_microstructure_tools_for_rwa_symbols():
    plan = build_plan("check usd/chf orderbook and funding", tool_states={"write": False})
    assert plan.context.symbol == "USD-CHF"
    names = [c.name for c in plan.tool_calls]
    assert "get_price" in names
    assert "get_orderbook" not in names
    assert "get_funding_rate" not in names
    assert any("orderbook" in w.lower() for w in plan.warnings)
    assert any("funding-rate" in w.lower() or "funding" in w.lower() for w in plan.warnings)


def test_build_plan_adds_price_calls_for_multiple_requested_symbols():
    plan = build_plan("check price btc, bera", tool_states={"write": False})
    names = [c.name for c in plan.tool_calls]
    assert names.count("get_price") >= 2

    price_args = [c.args for c in plan.tool_calls if c.name == "get_price"]
    requested = {(item.get("symbol"), item.get("asset_type")) for item in price_args}
    assert ("BTC", "crypto") in requested
    assert ("BERA", "crypto") in requested


def test_build_plan_adds_single_position_tpsl_adjust_tool():
    plan = build_plan("adjust tp 71200 sl 68900 for BTC")
    names = [c.name for c in plan.tool_calls]
    assert "adjust_position_tpsl" in names
    adjust_call = next(c for c in plan.tool_calls if c.name == "adjust_position_tpsl")
    assert adjust_call.args.get("symbol") == "BTC-USD"
    assert adjust_call.args.get("tp") == "71200"
    assert adjust_call.args.get("sl") == "68900"


def test_build_plan_adds_bulk_tpsl_adjust_tool_without_symbol():
    plan = build_plan("adjust all positions tp 3% sl 1.5%")
    names = [c.name for c in plan.tool_calls]
    assert "adjust_all_positions_tpsl" in names
    adjust_call = next(c for c in plan.tool_calls if c.name == "adjust_all_positions_tpsl")
    assert adjust_call.args.get("tp_pct") == 3.0
    assert adjust_call.args.get("sl_pct") == 1.5


def test_reasoning_orchestrator_applies_guardrail_blocks():
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="execute long BTC 1000 usd 20x now",
        tool_states={"execution": False},
    )
    assert len(plan.blocks) > 0


def test_reasoning_orchestrator_supports_ai_planner_json(monkeypatch):
    class _FakePlannerLLM:
        def invoke(self, messages):
            _ = messages
            return AIMessage(
                content=(
                    '{"intent":"analysis","context":{"symbol":"BTC-USD","timeframe":"1H"},'
                    '"tool_calls":[{"name":"get_price","args":{"symbol":"BTC","asset_type":"crypto"},"reason":"Need latest price"}],'
                    '"warnings":[],"blocks":[]}'
                )
            )

    monkeypatch.setattr(
        "backend.agent.Orchestrator.reasoning_orchestrator.LLMFactory.get_llm",
        lambda *args, **kwargs: _FakePlannerLLM(),
    )
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="check btc price",
        tool_states={"planner_source": "ai", "planner_fallback": "none", "runtime_model_id": "groq/openai/gpt-oss-120b"},
    )
    assert plan.intent == "analysis"
    assert plan.context.symbol == "BTC-USD"
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].name == "get_price"


def test_reasoning_orchestrator_ai_planner_can_fallback_to_system(monkeypatch):
    class _FailingPlannerLLM:
        def invoke(self, messages):
            _ = messages
            raise RuntimeError("planner provider timeout")

    monkeypatch.setattr(
        "backend.agent.Orchestrator.reasoning_orchestrator.LLMFactory.get_llm",
        lambda *args, **kwargs: _FailingPlannerLLM(),
    )
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="check BTC RSI",
        tool_states={"planner_source": "ai", "planner_fallback": "system"},
    )
    names = [c.name for c in plan.tool_calls]
    assert "get_price" in names
    assert any("fallback to system planner" in w.lower() for w in plan.warnings)


def test_reasoning_orchestrator_ai_plan_repair_bootstraps_missing_tools(monkeypatch):
    class _EmptyToolPlannerLLM:
        def invoke(self, messages):
            _ = messages
            return AIMessage(
                content='{"intent":"analysis","context":{"symbol":"SOL-USD","timeframe":"1H"},"tool_calls":[]}'
            )

    monkeypatch.setattr(
        "backend.agent.Orchestrator.reasoning_orchestrator.LLMFactory.get_llm",
        lambda *args, **kwargs: _EmptyToolPlannerLLM(),
    )
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="analyze sol",
        tool_states={"planner_source": "ai", "planner_fallback": "none"},
    )
    names = [c.name for c in plan.tool_calls]
    assert "get_price" in names
    assert "get_technical_analysis" in names
    assert any("bootstrap analysis tools were added" in w.lower() for w in plan.warnings)


def test_reasoning_orchestrator_ai_plan_repair_drops_write_tools_when_write_disabled(monkeypatch):
    class _WriteToolPlannerLLM:
        def invoke(self, messages):
            _ = messages
            return AIMessage(
                content=(
                    '{"intent":"analysis","context":{"symbol":"BTC-USD","timeframe":"1H"},'
                    '"tool_calls":[{"name":"set_symbol","args":{"target_symbol":"BTC-USD"},"reason":"sync chart"}]}'
                )
            )

    monkeypatch.setattr(
        "backend.agent.Orchestrator.reasoning_orchestrator.LLMFactory.get_llm",
        lambda *args, **kwargs: _WriteToolPlannerLLM(),
    )
    orchestrator = ReasoningOrchestrator()
    plan = orchestrator.build_plan(
        user_message="analyze btc",
        tool_states={"planner_source": "ai", "planner_fallback": "none", "write": False},
    )
    names = [c.name for c in plan.tool_calls]
    assert "set_symbol" not in names
    assert "get_price" in names
    assert any("dropped" in w.lower() and "write tool" in w.lower() for w in plan.warnings)


def test_tool_orchestrator_resolves_namespace_alias():
    async def _run():
        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 123.45, "asset_type": asset_type}}

        orchestrator = ToolOrchestrator(registry={"get_price": fake_get_price}, tool_timeout_sec=2.0)
        result = await orchestrator.run_tool(
            ToolCall(
                name="trading.get_price",
                args={"symbol": "BTC", "asset_type": "crypto"},
                reason="test",
            )
        )
        assert result.ok is True
        assert result.name == "get_price"

    asyncio.run(_run())


def test_tool_orchestrator_blocks_write_tools_when_write_disabled():
    async def _run():
        async def fake_set_symbol(symbol: str, target_symbol: str):
            return {"status": "success"}

        orchestrator = ToolOrchestrator(registry={"set_symbol": fake_set_symbol}, tool_timeout_sec=2.0)
        result = await orchestrator.run_tool(
            ToolCall(
                name="set_symbol",
                args={"symbol": "SOL-USD", "target_symbol": "SOL-USD"},
                reason="test",
            ),
            tool_states={"write": False},
        )
        assert result.ok is False
        assert "allow write" in (result.error or "").lower()

    asyncio.run(_run())


def test_tool_orchestrator_allows_nav_tools_without_write():
    async def _run():
        async def fake_get_photo_chart(symbol: str, target: str = "canvas"):
            return {"status": "success", "symbol": symbol, "target": target}

        orchestrator = ToolOrchestrator(registry={"get_photo_chart": fake_get_photo_chart}, tool_timeout_sec=2.0)
        result = await orchestrator.run_tool(
            ToolCall(
                name="get_photo_chart",
                args={"symbol": "BTC-USD", "target": "canvas"},
                reason="test",
            ),
            tool_states={"write": False},
        )
        assert result.ok is True
        assert result.name == "get_photo_chart"

    asyncio.run(_run())


def test_risk_gate_blocks_execution_if_auto_execution_is_disabled():
    result = RiskGate.evaluate("buy BTC now with 20x leverage", {"execution": False})
    assert len(result["blocks"]) > 0


def test_runtime_executes_registered_tools():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 123.45, "asset_type": asset_type}}

        runtime._registry = {"get_price": fake_get_price}

        packet = await runtime.prepare("show me price for BTC", tool_states={"plan_mode": True})
        assert packet["plan"] is not None
        assert len(packet["tool_results"]) == 1
        assert packet["tool_results"][0].ok is True
        assert "AGENTIC_TRADING_RUNTIME_CONTEXT" in packet["runtime_context"]
        assert isinstance(packet.get("phases"), list)
        assert len(packet.get("phases") or []) > 0

    asyncio.run(_run())


def test_runtime_skips_tools_when_plan_mode_disabled():
    async def _run():
        runtime = AgenticTradingRuntime()
        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 999.0, "asset_type": asset_type}}

        runtime._registry = {"get_price": fake_get_price}
        packet = await runtime.prepare(
            "show me price for BTC",
            tool_states={"plan_mode": False},
        )
        assert packet["plan"] is not None
        assert len(packet["tool_results"]) == 0

    asyncio.run(_run())


def test_runtime_prefetches_memory_when_enabled():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_search_memory(user_id: str, query: str, limit: int = 5):
            return {"results": [{"memory": "user likes pullback entries"}], "user_id": user_id, "query": query}

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 100.0, "asset_type": asset_type}}

        runtime._registry = {
            "search_memory": fake_search_memory,
            "get_price": fake_get_price,
        }
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="BTC-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "BTC", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "check btc trend",
            tool_states={"plan_mode": True, "memory_enabled": True, "strict_react": True},
            user_context={"user_address": "0xabc"},
        )

        names = [item.name for item in packet["tool_results"]]
        assert "search_memory" in names
        assert "get_price" in names
        memory_result = next(item for item in packet["tool_results"] if item.name == "search_memory")
        assert memory_result.args.get("user_id") == "0xabc"
        assert memory_result.ok is True

    asyncio.run(_run())


def test_runtime_prefetches_knowledge_when_enabled_even_if_plan_mode_disabled():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_search_knowledge_base(query: str, category: str = None, top_k: int = 3):
            return {
                "status": "success",
                "query": query,
                "category_filter": category,
                "results_count": 1,
                "results": [{"content": "risk-first trading guidance"}],
                "top_k": top_k,
            }

        runtime._registry = {"search_knowledge_base": fake_search_knowledge_base}

        packet = await runtime.prepare(
            "how to manage BTC risk today",
            tool_states={"plan_mode": False, "knowledge_enabled": True, "knowledge_top_k": 3},
        )

        names = [item.name for item in packet["tool_results"]]
        assert names == ["search_knowledge_base"]
        knowledge_result = packet["tool_results"][0]
        assert knowledge_result.args.get("top_k") == 3
        assert knowledge_result.ok is True
        phase_names = [item.get("name") for item in (packet.get("phases") or [])]
        assert "knowledge_think" in phase_names
        assert "knowledge_act" in phase_names
        assert "knowledge_observe" in phase_names

    asyncio.run(_run())


def test_runtime_context_marks_strong_knowledge_signal():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_search_knowledge_base(query: str, category: str = None, top_k: int = 3):
            return {
                "status": "success",
                "query": query,
                "category_filter": category,
                "results_count": 1,
                "results": [
                    {
                        "score": 0.71,
                        "title": "Risk Management Playbook",
                        "category": "03_trade_management",
                        "subcategory": "risk",
                        "content": "Use invalidation-first risk checks.",
                    }
                ],
            }

        runtime._registry = {"search_knowledge_base": fake_search_knowledge_base}

        packet = await runtime.prepare(
            "how to manage risk on btc setup",
            tool_states={"plan_mode": False, "knowledge_enabled": True},
        )

        context = packet.get("runtime_context") or ""
        assert "knowledge_evidence:" in context
        assert "- signal=strong" in context
        assert "Risk Management Playbook" in context

    asyncio.run(_run())


def test_runtime_context_marks_weak_knowledge_signal_on_zero_similarity():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_search_knowledge_base(query: str, category: str = None, top_k: int = 3):
            return {
                "status": "success",
                "query": query,
                "category_filter": category,
                "results_count": 2,
                "warning_code": "zero_similarity",
                "results": [
                    {"score": 0.0, "title": "Doc A", "category": "general", "subcategory": "", "content": "a"},
                    {"score": 0.0, "title": "Doc B", "category": "general", "subcategory": "", "content": "b"},
                ],
            }

        runtime._registry = {"search_knowledge_base": fake_search_knowledge_base}

        packet = await runtime.prepare(
            "what is best setup now",
            tool_states={"plan_mode": False, "knowledge_enabled": True},
        )

        context = packet.get("runtime_context") or ""
        assert "knowledge_evidence:" in context
        assert "- signal=weak" in context
        assert "- warning_code=zero_similarity" in context

    asyncio.run(_run())


def test_runtime_adds_followup_indicator_tools_for_rsi_request():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 101.0, "asset_type": asset_type}}

        async def fake_get_technical_analysis(symbol: str, timeframe: str = "1H"):
            return {"data": {"symbol": symbol, "timeframe": timeframe, "trend": "neutral"}}

        async def fake_get_active_indicators(symbol: str, timeframe: str = "1H"):
            return {"data": {"symbol": symbol, "timeframe": timeframe, "indicators": ["RSI"]}}

        async def fake_get_indicators(symbol: str, timeframe: str = "1H"):
            return {"data": {"RSI": 57.2, "timeframe": timeframe}}

        runtime._registry = {
            "get_price": fake_get_price,
            "get_technical_analysis": fake_get_technical_analysis,
            "get_active_indicators": fake_get_active_indicators,
            "get_indicators": fake_get_indicators,
        }

        packet = await runtime.prepare(
            "check RSI for BTC now",
            tool_states={"plan_mode": True, "market_symbol": "BTC-USD", "timeframe": ["1H"]},
        )
        names = [item.name for item in packet["tool_results"]]
        assert "get_price" in names
        assert "get_technical_analysis" in names
        assert "get_active_indicators" in names
        assert "get_indicators" in names

    asyncio.run(_run())


def test_runtime_adds_knowledge_followup_when_prefetch_not_successful():
    async def _run():
        runtime = AgenticTradingRuntime()
        attempts = {"search_knowledge_base": 0}

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 100.0, "asset_type": asset_type}}

        async def flaky_search_knowledge_base(query: str, category: str = None, top_k: int = 4):
            attempts["search_knowledge_base"] += 1
            if attempts["search_knowledge_base"] == 1:
                raise RuntimeError("temporary rag backend timeout")
            return {
                "status": "success",
                "query": query,
                "category_filter": category,
                "results_count": 1,
                "results": [{"content": "confluence and risk checks"}],
                "top_k": top_k,
            }

        runtime._registry = {
            "get_price": fake_get_price,
            "search_knowledge_base": flaky_search_knowledge_base,
        }
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="BTC-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "BTC", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "analyze btc setup with risk context",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "knowledge_enabled": True,
                "max_tool_calls": 5,
            },
        )

        knowledge_results = [item for item in packet["tool_results"] if item.name == "search_knowledge_base"]
        assert len(knowledge_results) >= 2
        assert any(item.ok is False for item in knowledge_results)
        assert any(item.ok is True for item in knowledge_results)

    asyncio.run(_run())


def test_runtime_always_emits_core_phase_markers():
    async def _run():
        runtime = AgenticTradingRuntime()
        packet = await runtime.prepare("hello there", tool_states={})
        phase_names = [item.get("name") for item in (packet.get("phases") or [])]
        required = {
            "tool_round_start",
            "tool_execution",
            "tool_check",
            "tool_followup",
            "tool_round_complete",
            "execution_adapter",
            "runtime_ready",
        }
        assert required.issubset(set(phase_names))

    asyncio.run(_run())


def test_runtime_injects_set_symbol_for_symbol_scoped_tools():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_set_symbol(symbol: str, target_symbol: str):
            return {"status": "success", "symbol": symbol, "target_symbol": target_symbol}

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 123.0, "asset_type": asset_type}}

        runtime._registry = {"set_symbol": fake_set_symbol, "get_price": fake_get_price}

        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="SOL-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "SOL", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "check sol price",
            tool_states={"plan_mode": True, "market_symbol": "BTC-USD", "write": True},
        )
        names = [item.name for item in packet["tool_results"]]
        assert names[0] == "set_symbol"
        assert packet["tool_results"][0].args.get("symbol") == "BTC-USD"
        assert packet["tool_results"][0].args.get("target_symbol") == "SOL-USD"
        assert "get_price" in names

    asyncio.run(_run())


def test_runtime_adds_warning_if_symbol_mismatch_but_write_disabled():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "price": 123.0, "asset_type": asset_type}}

        runtime._registry = {"get_price": fake_get_price}

        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="SOL-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "SOL", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "check sol price",
            tool_states={"plan_mode": True, "market_symbol": "BTC-USD", "write": False},
        )
        names = [item.name for item in packet["tool_results"]]
        assert names[0] == "get_price"
        assert any("allow write" in item.lower() for item in (packet["plan"].warnings or []))

    asyncio.run(_run())


def test_runtime_rwa_fallback_price_uses_rwa_asset_type():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_technical_analysis(symbol: str, timeframe: str = "1H", asset_type: str = "crypto"):
            return {"error": "analysis unavailable", "symbol": symbol, "asset_type": asset_type}

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "asset_type": asset_type, "price": 1.23}}

        runtime._registry = {
            "get_technical_analysis": fake_get_technical_analysis,
            "get_price": fake_get_price,
        }
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="USD-CHF", timeframe="1H"),
            tool_calls=[
                ToolCall(
                    name="get_technical_analysis",
                    args={"symbol": "USD-CHF", "timeframe": "1H", "asset_type": "rwa"},
                    reason="test",
                )
            ],
        )

        packet = await runtime.prepare(
            "check usd/chf technical and orderbook",
            tool_states={"plan_mode": True, "write": False, "strict_react": True},
        )

        price_results = [item for item in packet["tool_results"] if item.name == "get_price"]
        assert len(price_results) == 1
        assert price_results[0].args.get("asset_type") == "rwa"
        assert price_results[0].args.get("symbol") == "USD-CHF"
        assert "get_orderbook" not in [item.name for item in packet["tool_results"]]
        assert any("orderbook" in w.lower() for w in (packet["plan"].warnings or []))

    asyncio.run(_run())


def test_runtime_retries_failed_tool_once_then_succeeds():
    async def _run():
        runtime = AgenticTradingRuntime()
        attempts = {"get_price": 0}

        async def flaky_get_price(symbol: str, asset_type: str = "crypto"):
            attempts["get_price"] += 1
            if attempts["get_price"] == 1:
                raise RuntimeError("temporary connector timeout")
            return {"data": {"symbol": symbol, "asset_type": asset_type, "price": 123.45}}

        runtime._registry = {"get_price": flaky_get_price}
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="BTC-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "BTC", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "check btc price",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "max_tool_calls": 4,
                "tool_retry_max_attempts": 2,
                "retry_failed_tools": True,
            },
        )

        assert len(packet["tool_results"]) == 2
        assert packet["tool_results"][0].ok is False
        assert packet["tool_results"][1].ok is True
        retry_running = any(
            item.get("name") == "tool_retry_scheduled" and item.get("status") == "running"
            for item in (packet.get("phases") or [])
        )
        assert retry_running

    asyncio.run(_run())


def test_runtime_injects_user_address_for_tpsl_adjust_tools():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_adjust_position_tpsl(
            user_address: str,
            symbol: str,
            tp: str = None,
            sl: str = None,
            exchange: str = None,
        ):
            return {
                "status": "ok",
                "user_address": user_address,
                "symbol": symbol,
                "tp": tp,
                "sl": sl,
                "exchange": exchange,
            }

        runtime._registry = {"adjust_position_tpsl": fake_adjust_position_tpsl}
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="execution",
            context=PlanContext(symbol="BTC-USD", timeframe="1H", requested_execution=True),
            tool_calls=[
                ToolCall(
                    name="adjust_position_tpsl",
                    args={"symbol": "BTC-USD", "tp": "71200", "sl": "68900"},
                    reason="test",
                )
            ],
        )

        packet = await runtime.prepare(
            "adjust tp 71200 sl 68900 for btc",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "execution": True,
                "max_tool_calls": 3,
            },
            user_context={"user_address": "0xabc"},
        )

        results = [item for item in packet["tool_results"] if item.name == "adjust_position_tpsl"]
        assert len(results) == 1
        assert results[0].ok is True
        assert results[0].args.get("user_address") == "0xabc"

    asyncio.run(_run())


def test_runtime_does_not_retry_non_retryable_tool_errors():
    async def _run():
        runtime = AgenticTradingRuntime()
        runtime._registry = {}
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol=None, timeframe="1H"),
            tool_calls=[ToolCall(name="unknown_tool_abc", args={"symbol": "BTC"}, reason="test")],
        )

        packet = await runtime.prepare(
            "check btc",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "max_tool_calls": 4,
                "tool_retry_max_attempts": 3,
                "retry_failed_tools": True,
            },
        )

        assert len(packet["tool_results"]) == 1
        assert packet["tool_results"][0].ok is False
        assert "Unknown tool" in (packet["tool_results"][0].error or "")
        retry_running = any(
            item.get("name") == "tool_retry_scheduled" and item.get("status") == "running"
            for item in (packet.get("phases") or [])
        )
        assert not retry_running

    asyncio.run(_run())


def test_runtime_write_tools_default_to_no_retry():
    async def _run():
        runtime = AgenticTradingRuntime()
        attempts = {"set_symbol": 0}

        async def flaky_set_symbol(symbol: str, target_symbol: str):
            attempts["set_symbol"] += 1
            raise RuntimeError("temporary write transport error")

        runtime._registry = {"set_symbol": flaky_set_symbol}
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol=None, timeframe="1H"),
            tool_calls=[
                ToolCall(
                    name="set_symbol",
                    args={"symbol": "BTC-USD", "target_symbol": "SOL-USD"},
                    reason="test",
                )
            ],
        )

        packet = await runtime.prepare(
            "sync symbol",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "write": True,
                "retry_failed_tools": True,
                "tool_retry_max_attempts": 3,
                "max_tool_calls": 5,
            },
        )

        assert len(packet["tool_results"]) == 1
        assert packet["tool_results"][0].ok is False
        assert attempts["set_symbol"] == 1
        retry_running = any(
            item.get("name") == "tool_retry_scheduled" and item.get("status") == "running"
            for item in (packet.get("phases") or [])
        )
        assert not retry_running

    asyncio.run(_run())


def test_runtime_write_tool_retry_can_be_enabled_with_mode_override():
    async def _run():
        runtime = AgenticTradingRuntime()
        attempts = {"set_symbol": 0}

        async def flaky_set_symbol(symbol: str, target_symbol: str):
            attempts["set_symbol"] += 1
            if attempts["set_symbol"] == 1:
                raise RuntimeError("temporary write transport error")
            return {"status": "success", "symbol": symbol, "target_symbol": target_symbol}

        runtime._registry = {"set_symbol": flaky_set_symbol}
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol=None, timeframe="1H"),
            tool_calls=[
                ToolCall(
                    name="set_symbol",
                    args={"symbol": "BTC-USD", "target_symbol": "SOL-USD"},
                    reason="test",
                )
            ],
        )

        packet = await runtime.prepare(
            "sync symbol",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "write": True,
                "retry_failed_tools": True,
                "write_tool_retry_max_attempts": 2,
                "max_tool_calls": 5,
            },
        )

        assert len(packet["tool_results"]) == 2
        assert packet["tool_results"][0].ok is False
        assert packet["tool_results"][1].ok is True
        assert attempts["set_symbol"] == 2
        retry_running = any(
            item.get("name") == "tool_retry_scheduled" and item.get("status") == "running"
            for item in (packet.get("phases") or [])
        )
        assert retry_running

    asyncio.run(_run())


def test_runtime_auto_adds_web_news_observation_for_openrouter_analysis():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "asset_type": asset_type, "price": 100.0}}

        async def fake_search_news(query: str, mode: str = "quality", source: str = "news"):
            return {"data": {"query": query, "mode": mode, "source": source, "items": []}}

        runtime._registry = {
            "get_price": fake_get_price,
            "search_news": fake_search_news,
        }
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="BTC-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "BTC", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "analyze btc trend",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "runtime_model_provider": "openrouter",
                "web_observation_enabled": True,
                "web_observation_mode": "quality",
                "max_tool_calls": 5,
            },
        )

        names = [item.name for item in packet["tool_results"]]
        assert "get_price" in names
        assert "search_news" in names
        news_results = [item for item in packet["tool_results"] if item.name == "search_news"]
        assert len(news_results) == 1
        assert news_results[0].args.get("mode") == "quality"

    asyncio.run(_run())


def test_runtime_auto_web_observation_uses_speed_mode_for_groq():
    async def _run():
        runtime = AgenticTradingRuntime()

        async def fake_get_price(symbol: str, asset_type: str = "crypto"):
            return {"data": {"symbol": symbol, "asset_type": asset_type, "price": 100.0}}

        async def fake_search_news(query: str, mode: str = "quality", source: str = "news"):
            return {"data": {"query": query, "mode": mode, "source": source, "items": []}}

        runtime._registry = {
            "get_price": fake_get_price,
            "search_news": fake_search_news,
        }
        runtime._build_plan_phase = lambda **_: AgentPlan(
            intent="analysis",
            context=PlanContext(symbol="SOL-USD", timeframe="1H"),
            tool_calls=[ToolCall(name="get_price", args={"symbol": "SOL", "asset_type": "crypto"}, reason="test")],
        )

        packet = await runtime.prepare(
            "analyze sol intraday",
            tool_states={
                "plan_mode": True,
                "strict_react": True,
                "runtime_model_provider": "groq",
                "web_observation_enabled": True,
                "max_tool_calls": 5,
            },
        )

        news_results = [item for item in packet["tool_results"] if item.name == "search_news"]
        assert len(news_results) == 1
        assert news_results[0].args.get("mode") == "speed"

    asyncio.run(_run())
