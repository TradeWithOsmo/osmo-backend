import asyncio

from backend.agent.Core.agent_brain import AgentBrain
from backend.agent.Schema.agent_runtime import ToolResult


class _FakeRuntime:
    async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
        return {"plan": None, "tool_results": [], "runtime_context": "", "phases": []}


class _DummyLLM:
    async def ainvoke(self, messages):
        return None

    async def astream(self, messages):
        if False:
            yield messages


def _build_brain(
    monkeypatch,
    llm,
    tool_states=None,
    user_context=None,
    deep_runtime_cls=None,
    model_id="test/model",
    runtime_cls=None,
):
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", runtime_cls or _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", lambda *args, **kwargs: llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    if deep_runtime_cls is not None:
        monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", deep_runtime_cls)
    return AgentBrain(model_id=model_id, tool_states=tool_states, user_context=user_context)


def test_agent_engine_is_forced_to_deepagents(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    assert brain.agent_engine == "deepagents"
    assert brain.agent_engine_strict is True


def test_chat_raises_when_deepagents_unavailable(monkeypatch):
    class _UnavailableDeepRuntime:
        @staticmethod
        def is_available():
            return False

    brain = _build_brain(monkeypatch, _DummyLLM(), deep_runtime_cls=_UnavailableDeepRuntime)

    try:
        asyncio.run(brain.chat(user_message="check btc"))
        assert False, "Expected RuntimeError when Deep Agents runtime is unavailable"
    except RuntimeError as exc:
        assert "Deep Agents engine is required but unavailable" in str(exc)


def test_chat_and_stream_use_deepagents_result(monkeypatch):
    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm
            self.system_prompt = system_prompt
            self.tool_states = tool_states

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            return {
                "content": "deepagents-ok",
                "usage": {"total_tokens": 10},
                "thoughts": ["step-1", "step-2"],
                "runtime": {
                    "plan": None,
                    "tool_results": [],
                    "phases": [{"name": "plan"}, {"name": "act"}],
                },
            }

    brain = _build_brain(monkeypatch, _DummyLLM(), deep_runtime_cls=_DeepRuntime)

    result = asyncio.run(brain.chat(user_message="check btc"))
    assert result["content"] == "deepagents-ok"
    assert result["thoughts"] == ["step-1", "step-2"]

    async def _collect():
        items = []
        async for event in brain.stream(user_message="check btc"):
            items.append(event)
        return items

    events = asyncio.run(_collect())
    event_types = [e.get("type") for e in events]
    assert "runtime" in event_types
    assert "delta" in event_types
    assert "done" in event_types


def test_runtime_tool_states_force_sync_secondary_and_deepagents(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM(), tool_states={"memory_enabled": False})
    state = brain._build_runtime_tool_states()

    assert state.get("runtime_flow_mode") == "sync"
    assert state.get("rag_mode") == "secondary"
    assert state.get("agent_engine") == "deepagents"
    assert state.get("agent_engine_strict") is True
    assert state.get("reliability_mode") == "balanced"
    assert state.get("recovery_mode") == "recover_then_continue"
    assert int(state.get("max_tool_actions") or 0) >= 8


def test_runtime_tool_states_apply_write_reliability_floor(monkeypatch):
    brain = _build_brain(
        monkeypatch,
        _DummyLLM(),
        tool_states={
            "write": True,
            "reliability_mode": "balanced",
            "max_tool_actions": 4,
            "max_tool_calls": 4,
            "tool_retry_max": 1,
            "tool_retry_max_attempts": 1,
        },
    )
    state = brain._build_runtime_tool_states()

    assert int(state.get("max_tool_actions") or 0) >= 8
    assert int(state.get("max_tool_calls") or 0) >= 8
    assert int(state.get("tool_retry_max") or 0) >= 2
    assert int(state.get("tool_retry_max_attempts") or 0) >= 2


def test_should_rag_fallback_when_confidence_is_low_even_if_tool_succeeds(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    packet = {
        "tool_results": [
            ToolResult(name="get_price", args={}, ok=True, data={"price": 100}),
        ]
    }
    should_fallback = brain._should_rag_fallback(
        "please analysis market structure btc",
        "Per-symbol confidence=30/100 due to partial evidence.",
        packet,
        {"knowledge_enabled": True, "rag_mode": "secondary"},
    )
    assert should_fallback is True


def test_should_not_rag_fallback_when_confidence_high_and_critical_tool_ok(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    packet = {
        "tool_results": [
            ToolResult(name="get_technical_analysis", args={}, ok=True, data={"trend": "up"}),
            ToolResult(name="get_price", args={}, ok=True, data={"price": 100}),
        ]
    }
    should_fallback = brain._should_rag_fallback(
        "analysis btc setup now",
        "Bias remains valid. confidence=85/100.",
        packet,
        {"knowledge_enabled": True, "rag_mode": "secondary"},
    )
    assert should_fallback is False


def test_should_not_rag_fallback_for_smalltalk_with_runtime_context(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    wrapped = "[RUNTIME_CONTEXT]\nmarket_symbol=BTC-USD\n[/RUNTIME_CONTEXT]\n\nhai"

    should_fallback = brain._should_rag_fallback(
        wrapped,
        "Hi there! What can I help you with?",
        {"tool_results": []},
        {"knowledge_enabled": True, "rag_mode": "secondary"},
    )
    assert should_fallback is False


def test_should_not_rag_fallback_when_no_tools_and_no_low_confidence(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())

    should_fallback = brain._should_rag_fallback(
        "analysis btc setup",
        "Bias is neutral while waiting confirmation.",
        {"tool_results": []},
        {"knowledge_enabled": True, "rag_mode": "secondary"},
    )
    assert should_fallback is False


def test_chat_stores_memory_turn_when_memory_enabled(monkeypatch):
    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            return {
                "content": "ok",
                "usage": {},
                "thoughts": ["ok"],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    calls = []

    async def _fake_add_memory_messages(user_id, messages, metadata=None):
        calls.append({"user_id": user_id, "messages": messages, "metadata": metadata or {}})
        return {"stored": True}

    monkeypatch.setattr("backend.agent.Core.agent_brain.add_memory_messages", _fake_add_memory_messages)
    brain = _build_brain(
        monkeypatch,
        _DummyLLM(),
        deep_runtime_cls=_DeepRuntime,
        tool_states={"memory_enabled": True},
        user_context={"user_address": "0xabc", "session_id": "s-1"},
    )

    _ = asyncio.run(brain.chat(user_message="check btc", history=[]))

    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == "0xabc"
    assert len(call["messages"]) == 2
    assert call["messages"][0]["role"] == "user"
    assert call["messages"][1]["role"] == "assistant"
    assert call["metadata"].get("session_id") == "s-1"


def test_deepagents_rotates_to_next_groq_key_on_rate_limit(monkeypatch):
    class _GroqLLM:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            return None

        async def astream(self, messages):
            if False:
                yield messages

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            if getattr(self.llm, "name", "") != "secondary":
                raise RuntimeError("429 Too Many Requests: rate limit reached")
            return {
                "content": "secondary-deep-ok",
                "usage": {},
                "thoughts": ["switched"],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    primary = _GroqLLM("primary")
    secondary = _GroqLLM("secondary")

    def _fake_get_llm(model_id, **kwargs):
        if kwargs.get("groq_key_index") == 1:
            return secondary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2"])
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _DeepRuntime)

    brain = AgentBrain(model_id="groq/openai/gpt-oss-120b", tool_states={"agent_engine": "deepagents"})
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "secondary-deep-ok"
    assert brain._groq_key_index == 1


def test_deepagents_rotates_until_quaternary_when_first_three_rate_limited(monkeypatch):
    class _GroqLLM:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            return None

        async def astream(self, messages):
            if False:
                yield messages

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            if getattr(self.llm, "name", "") != "quaternary":
                raise RuntimeError("429 Too Many Requests: rate limit reached")
            return {
                "content": "quaternary-deep-ok",
                "usage": {},
                "thoughts": ["switched"],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    primary = _GroqLLM("primary")
    secondary = _GroqLLM("secondary")
    tertiary = _GroqLLM("tertiary")
    quaternary = _GroqLLM("quaternary")

    def _fake_get_llm(model_id, **kwargs):
        index = kwargs.get("groq_key_index", 0)
        if index == 1:
            return secondary
        if index == 2:
            return tertiary
        if index == 3:
            return quaternary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2", "k3", "k4"])
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _DeepRuntime)

    brain = AgentBrain(model_id="groq/openai/gpt-oss-120b", tool_states={"agent_engine": "deepagents"})
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "quaternary-deep-ok"
    assert brain._groq_key_index == 3


def test_deepagents_normalizes_legacy_nvidia_prefix_to_openrouter(monkeypatch):
    class _NamedLLM:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, messages):
            return None

        async def astream(self, messages):
            if False:
                yield messages

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            return {
                "content": "openrouter-ok",
                "usage": {},
                "thoughts": ["normalized"],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    openrouter_llm = _NamedLLM("openrouter")

    def _fake_get_llm(model_id, **kwargs):
        assert model_id == "nvidia/moonshotai/kimi-k2.5"
        return openrouter_llm

    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _DeepRuntime)

    brain = AgentBrain(model_id="nvidia/moonshotai/kimi-k2.5", tool_states={"agent_engine": "deepagents"})
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "openrouter-ok"
    assert brain._runtime_model_provider() == "openrouter"


def test_predictable_cache_key_ignores_runtime_context_wrapper(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    wrapped = "[RUNTIME_CONTEXT]\nsource=frontend_toolbar\n[/RUNTIME_CONTEXT]\n\nhai"

    plain_key = brain._predictable_response_cache_key("hai", {})
    wrapped_key = brain._predictable_response_cache_key(wrapped, {})

    assert plain_key == wrapped_key


def test_predictable_fast_reply_skips_deepagents_for_runtime_context_greeting(monkeypatch):
    calls = {"run": 0}

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            calls["run"] += 1
            return {
                "content": "should-not-run",
                "usage": {},
                "thoughts": [],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    brain = _build_brain(monkeypatch, _DummyLLM(), deep_runtime_cls=_DeepRuntime)
    wrapped = "[RUNTIME_CONTEXT]\nsource=frontend_toolbar\n[/RUNTIME_CONTEXT]\n\nhai"
    result = asyncio.run(brain.chat(user_message=wrapped))

    assert calls["run"] == 0
    assert "Hi!" in result.get("content", "")
    phase_names = [str(item.get("name")) for item in (result.get("runtime", {}) or {}).get("phases", [])]
    assert "quick_reply" in phase_names


def test_predictable_fast_reply_skips_deepagents_for_greeting_with_assistant_name(monkeypatch):
    calls = {"run": 0}

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            calls["run"] += 1
            return {
                "content": "should-not-run",
                "usage": {},
                "thoughts": [],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    brain = _build_brain(monkeypatch, _DummyLLM(), deep_runtime_cls=_DeepRuntime)
    wrapped = "[RUNTIME_CONTEXT]\nsource=frontend_toolbar\n[/RUNTIME_CONTEXT]\n\nhai osmo"
    result = asyncio.run(brain.chat(user_message=wrapped))

    assert calls["run"] == 0
    assert "Hi!" in result.get("content", "")
    phase_names = [str(item.get("name")) for item in (result.get("runtime", {}) or {}).get("phases", [])]
    assert "quick_reply" in phase_names


def test_tool_request_routes_to_runtime_prepare_primary_without_deepagents(monkeypatch):
    class _Resp:
        def __init__(self, content: str):
            self.content = content
            self.usage_metadata = {"total_tokens": 12}

    class _TaggedLLM:
        async def ainvoke(self, messages):
            return _Resp("<final>fallback-runtime-ok</final>\n<reasoning>\n- tool execution verified\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    calls = {"deep_run": 0}

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            calls["deep_run"] += 1
            return {"content": "should-not-run", "usage": {}, "thoughts": [], "runtime": {"plan": None, "tool_results": [], "phases": []}}

    class _RuntimeWithTools:
        async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
            return {
                "plan": None,
                "runtime_context": "RUNTIME_CONTEXT: executed deterministic primary runtime",
                "tool_results": [
                    ToolResult(
                        name="set_symbol",
                        args={"symbol": "BTC-USD", "target_symbol": "ETH-USD"},
                        ok=True,
                        data={"status": "completed"},
                    )
                ],
                "phases": [{"name": "tool_execution", "status": "done"}],
            }

    brain = _build_brain(
        monkeypatch,
        _TaggedLLM(),
        deep_runtime_cls=_DeepRuntime,
        runtime_cls=_RuntimeWithTools,
        tool_states={"write": True, "knowledge_enabled": False},
    )

    result = asyncio.run(brain.chat(user_message="set symbol to ETH then add indicator RSI"))
    assert result["content"] == "fallback-runtime-ok"
    assert calls["deep_run"] == 0

    runtime = result.get("runtime", {}) or {}
    tool_results = runtime.get("tool_results") or []
    assert len(tool_results) == 1
    assert tool_results[0].get("name") == "set_symbol"


def test_runtime_tool_states_bridge_max_tool_and_retry_fields(monkeypatch):
    brain = _build_brain(
        monkeypatch,
        _DummyLLM(),
        tool_states={
            "max_tool_actions": 7,
            "tool_retry_max": 2,
        },
    )
    state = brain._build_runtime_tool_states()
    assert state.get("max_tool_calls") == 7
    assert state.get("tool_retry_max_attempts") == 2


def test_tool_execution_detector_matches_sequence_style_prompt(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    msg = (
        "check current symbol > change time frame to 1m > "
        "add indicator stochastic rsi > get indicators > done"
    )
    assert brain._is_tool_execution_request(msg) is True


def test_language_detection_is_dynamic_for_non_english(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    assert brain._detect_user_language("cambiar simbolo y agregar indicador rsi ahora") == "es"
    assert brain._build_response_language_instruction("es").startswith(
        "Response language policy: answer in the same language"
    )


def test_normalization_handles_typos_and_non_english_commands(monkeypatch):
    brain = _build_brain(monkeypatch, _DummyLLM())
    raw = "cheked sekaang symbo > chnage timefrmae to 1m > add indikatr rsi > donde"
    normalized = brain._normalize_command_phrases(raw).lower()
    assert "check" in normalized
    assert "symbol" in normalized
    assert "change" in normalized
    assert "timeframe" in normalized or "time frame" in normalized
    assert "indicator" in normalized
    assert "done" in normalized


def test_runtime_primary_includes_input_normalization_metadata(monkeypatch):
    class _Resp:
        def __init__(self, content: str):
            self.content = content
            self.usage_metadata = {"total_tokens": 8}

    class _TaggedLLM:
        async def ainvoke(self, messages):
            return _Resp("<final>ok</final><reasoning>- done</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            return {"content": "should-not-run", "usage": {}, "thoughts": [], "runtime": {"plan": None, "tool_results": [], "phases": []}}

    class _RuntimeWithTools:
        async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
            return {
                "plan": None,
                "runtime_context": "runtime context",
                "tool_results": [ToolResult(name="set_symbol", args={"target_symbol": "ETH-USD"}, ok=True, data={"status": "ok"})],
                "phases": [{"name": "tool_execution", "status": "done"}],
            }

    brain = _build_brain(
        monkeypatch,
        _TaggedLLM(),
        deep_runtime_cls=_DeepRuntime,
        runtime_cls=_RuntimeWithTools,
        tool_states={"write": True},
    )
    result = asyncio.run(brain.chat(user_message="cek simbol sekarang lalu ubah timeframe 1m"))
    runtime = result.get("runtime", {}) or {}
    meta = runtime.get("input_normalization") or {}
    assert meta.get("user_language") == "id"
    assert meta.get("normalization_applied") is True


def test_runtime_primary_no_tool_result_returns_planner_hint(monkeypatch):
    class _DeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            return {"content": "should-not-run", "usage": {}, "thoughts": [], "runtime": {"plan": None, "tool_results": [], "phases": []}}

    class _RuntimeNoTools:
        async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
            return {
                "plan": {"warnings": ["No symbol detected. Provide a ticker (example: BTC, ETH, SOL)."]},
                "runtime_context": "",
                "tool_results": [],
                "phases": [],
            }

    brain = _build_brain(
        monkeypatch,
        _DummyLLM(),
        deep_runtime_cls=_DeepRuntime,
        runtime_cls=_RuntimeNoTools,
        tool_states={"write": True},
    )
    result = asyncio.run(
        brain.chat(user_message="please change timeframe to 1m and add indicator rsi")
    )
    content = str(result.get("content") or "")
    assert "No tools were executed for this request" in content
    assert "Planner hint:" in content
    assert "No symbol detected" in content
