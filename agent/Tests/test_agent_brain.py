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


def _build_brain(monkeypatch, llm, tool_states=None, user_context=None, deep_runtime_cls=None, model_id="test/model"):
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
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


def test_deepagents_falls_back_to_openrouter_when_nvidia_auth_fails(monkeypatch):
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
            if getattr(self.llm, "name", "") == "openrouter":
                return {
                    "content": "openrouter-fallback-ok",
                    "usage": {},
                    "thoughts": ["fallback"],
                    "runtime": {"plan": None, "tool_results": [], "phases": []},
                }
            raise RuntimeError("Error code: 401 - {'error': {'message': 'User not found.', 'code': 401}}")

    nvidia_llm = _NamedLLM("nvidia")
    openrouter_llm = _NamedLLM("openrouter")

    def _fake_get_llm(model_id, **kwargs):
        if model_id == "moonshotai/kimi-k2.5":
            return openrouter_llm
        return nvidia_llm

    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _DeepRuntime)

    brain = AgentBrain(model_id="nvidia/moonshotai/kimi-k2.5", tool_states={"agent_engine": "deepagents"})
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "openrouter-fallback-ok"
    assert brain._provider_fallback_model_id == "moonshotai/kimi-k2.5"
