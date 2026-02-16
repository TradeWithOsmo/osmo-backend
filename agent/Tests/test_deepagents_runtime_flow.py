import asyncio

from backend.agent.Core import deepagents_runtime as deep_runtime
from backend.agent.Tools.data import analysis as analysis_tool


class _FakeAIMessage:
    type = "ai"

    def __init__(self, content: str) -> None:
        self.content = content
        self.usage_metadata = {}
        self.response_metadata = {}


class _FakeDeepAgent:
    async def ainvoke(self, payload):
        _ = payload
        return {
            "messages": [
                _FakeAIMessage("<final>ok</final>\n<reasoning>\n- done\n</reasoning>")
            ]
        }


class _SlowDeepAgent:
    async def ainvoke(self, payload):
        _ = payload
        await asyncio.sleep(0.05)
        return {"messages": [_FakeAIMessage("late")]}


def test_deepagents_runtime_skips_bootstrap_prefetch_by_default(monkeypatch):
    monkeypatch.setattr(deep_runtime, "create_deep_agent", lambda **kwargs: _FakeDeepAgent())
    monkeypatch.setattr(
        deep_runtime.DeepAgentsRuntime,
        "_build_wrapped_tools",
        lambda self, user_message: [],
    )

    runtime = deep_runtime.DeepAgentsRuntime(
        llm=object(),
        system_prompt="system",
        tool_states={"strict_react": True},
    )
    result = asyncio.run(runtime.run_chat(user_message="analyze BTC-USD now"))

    phases = ((result or {}).get("runtime") or {}).get("phases") or []
    phase_names = [item.get("name") for item in phases if isinstance(item, dict)]
    assert "bootstrap_prefetch_skipped" in phase_names
    assert "tool_call" not in phase_names
    graph = ((result or {}).get("runtime") or {}).get("execution_graph") or {}
    assert isinstance(graph, dict)
    assert len(graph.get("nodes") or []) > 0


def test_bootstrap_calls_skip_rwa_technical_prefetch():
    runtime = deep_runtime.DeepAgentsRuntime(
        llm=object(),
        system_prompt="system",
        tool_states={},
    )
    calls = runtime._build_bootstrap_calls("analyze BTC-USD and USD/CHF")
    names_and_symbols = [(call.name, (call.args or {}).get("symbol")) for call in calls]

    assert ("get_technical_analysis", "BTC-USD") in names_and_symbols
    assert ("get_technical_analysis", "USD-CHF") not in names_and_symbols


def test_analysis_tool_short_circuits_fiat_rwa_without_http(monkeypatch):
    class _ShouldNotCallHTTP:
        def __init__(self, *args, **kwargs):
            raise AssertionError("httpx.AsyncClient should not be called for fiat-RWA technical.")

    monkeypatch.setattr(analysis_tool.httpx, "AsyncClient", _ShouldNotCallHTTP)
    result = asyncio.run(
        analysis_tool.get_technical_analysis("USD-CHF", timeframe="1D", asset_type="rwa")
    )

    assert isinstance(result, dict)
    assert "error" in result
    assert "unsupported" in str(result.get("error", "")).lower()


def test_timeout_fallback_contains_symbol_confidence_block(monkeypatch):
    monkeypatch.setattr(deep_runtime, "create_deep_agent", lambda **kwargs: _SlowDeepAgent())
    monkeypatch.setattr(
        deep_runtime.DeepAgentsRuntime,
        "_build_wrapped_tools",
        lambda self, user_message: [],
    )

    runtime = deep_runtime.DeepAgentsRuntime(
        llm=object(),
        system_prompt="system",
        tool_states={"strict_react": True},
    )
    runtime._model_timeout_sec = 0.01
    result = asyncio.run(
        runtime.run_chat(user_message="analyze BTC-USD and USD/CHF probability tree")
    )

    content = str((result or {}).get("content") or "").lower()
    assert "per-symbol fallback" in content
    assert "confidence=" in content
    assert "btc-usd" in content


def test_compact_profile_skips_write_tools_without_write_intent():
    runtime = deep_runtime.DeepAgentsRuntime(
        llm=object(),
        system_prompt="system",
        tool_states={"tool_profile": "compact", "write": True, "execution": False},
    )
    wrapped = runtime._build_wrapped_tools(user_message="hai osmo")
    names = {tool.__name__ for tool in wrapped}

    assert not names.intersection(set(deep_runtime.DeepAgentsRuntime._WRITE_TOOL_NAMES))
    assert "get_price" in names


def test_compact_profile_enables_write_tools_when_write_intent_present():
    runtime = deep_runtime.DeepAgentsRuntime(
        llm=object(),
        system_prompt="system",
        tool_states={"tool_profile": "compact", "write": True, "execution": False},
    )
    wrapped = runtime._build_wrapped_tools(user_message="please set symbol to ETH-USD and set timeframe to 1m")
    names = {tool.__name__ for tool in wrapped}

    assert "set_symbol" in names
    assert "set_timeframe" in names
