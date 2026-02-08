import asyncio

from langchain_core.messages import AIMessage

from backend.agent.Core.agent_brain import AgentBrain
from backend.agent.Schema.agent_runtime import ToolResult


class _FakeRuntime:
    async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
        return {"plan": None, "tool_results": [], "runtime_context": "", "phases": []}


def _build_brain(monkeypatch, llm, tool_states=None, user_context=None):
    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", lambda *args, **kwargs: llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    return AgentBrain(model_id="test/model", tool_states=tool_states, user_context=user_context)


def test_chat_sanitizes_history_and_drops_non_chat_roles(monkeypatch):
    class _CaptureLLM:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, messages):
            self.calls.append(messages)
            return AIMessage(content="<final>ok</final>\n<reasoning>\n- fine\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    llm = _CaptureLLM()
    brain = _build_brain(monkeypatch, llm)

    history = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "content": "hidden"},
        {"role": "assistant", "content": "done", "tool_calls": [{"id": "x"}]},
        {"role": "function", "content": "skip"},
    ]
    _ = asyncio.run(brain.chat(user_message="check", history=history))

    sent = llm.calls[0]
    roles = [m["role"] for m in sent]
    assert "tool" not in roles
    assert "function" not in roles
    assert roles.count("assistant") == 1


def test_chat_retries_once_on_tool_choice_conflict(monkeypatch):
    class _RetryLLM:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise RuntimeError("Tool choice is none, but model called a tool")
            return AIMessage(content="<final>recovered</final>\n<reasoning>\n- fallback\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    llm = _RetryLLM()
    brain = _build_brain(monkeypatch, llm)

    result = asyncio.run(brain.chat(user_message="price btc"))
    assert result["content"] == "recovered"
    assert len(llm.calls) == 2
    assert llm.calls[1][0]["role"] == "system"
    assert "STRICT OUTPUT MODE" in llm.calls[1][0]["content"]


def test_stream_falls_back_to_ainvoke_on_tool_choice_conflict(monkeypatch):
    class _StreamRetryLLM:
        def __init__(self):
            self.stream_calls = []
            self.invoke_calls = []

        async def ainvoke(self, messages):
            self.invoke_calls.append(messages)
            return AIMessage(content="<final>stream-recovered</final>\n<reasoning>\n- fallback\n</reasoning>")

        async def astream(self, messages):
            self.stream_calls.append(messages)
            raise RuntimeError("Tool choice is none, but model called a tool")
            if False:
                yield messages

    llm = _StreamRetryLLM()
    brain = _build_brain(monkeypatch, llm)

    async def _collect():
        events = []
        async for event in brain.stream(user_message="check btc"):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1
    assert done[0]["content"] == "stream-recovered"
    assert len(llm.stream_calls) == 1
    assert len(llm.invoke_calls) == 1
    assert "STRICT OUTPUT MODE" in llm.invoke_calls[0][0]["content"]


def test_chat_returns_safe_fallback_when_tool_choice_conflict_persists(monkeypatch):
    class _AlwaysConflictLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("tool_choice is none, but model called a tool")

        async def astream(self, messages):
            if False:
                yield messages

    llm = _AlwaysConflictLLM()
    brain = _build_brain(monkeypatch, llm)

    result = asyncio.run(brain.chat(user_message="check btc"))
    assert "tool-routing mismatch" in result["content"].lower()
    assert any("tool call mode conflicted" in line.lower() for line in result["thoughts"])


def test_chat_rewrites_overprecise_levels_when_data_gaps_exist(monkeypatch):
    class _GapRuntime:
        async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
            return {
                "plan": None,
                "runtime_context": "",
                "phases": [],
                "tool_results": [
                    ToolResult(
                        name="get_technical_analysis",
                        args={"symbol": "USD-CHF", "timeframe": "1H", "asset_type": "rwa"},
                        ok=False,
                        error="technical unavailable",
                        data={"error": "technical unavailable"},
                    )
                ],
            }

    class _RewriteLLM:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content=(
                        "<final>USD-CHF setup: entry 0.785, stop 0.782, TP 0.795.</final>\n"
                        "<reasoning>\n- draft\n</reasoning>"
                    )
                )
            return AIMessage(
                content=(
                    "<final>Data technical untuk USD-CHF gagal, jadi tidak ada level entry/SL/TP numerik. "
                    "Tunggu konfirmasi breakout dengan indikator.</final>\n"
                    "<reasoning>\n- revised for data gap\n</reasoning>"
                )
            )

        async def astream(self, messages):
            if False:
                yield messages

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _GapRuntime)
    llm = _RewriteLLM()
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", lambda *args, **kwargs: llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")

    brain = AgentBrain(model_id="test/model")
    result = asyncio.run(brain.chat(user_message="check usd/chf setup"))

    assert llm.calls == 2
    assert "tidak ada level entry/sl/tp" in result["content"].lower()


def test_runtime_tool_states_include_provider_and_web_observation_defaults(monkeypatch):
    class _CaptureRuntime:
        last_tool_states = None

        async def prepare(self, user_message, history=None, tool_states=None, user_context=None):
            _CaptureRuntime.last_tool_states = dict(tool_states or {})
            return {"plan": None, "tool_results": [], "runtime_context": "", "phases": []}

    class _EchoLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>ok</final>\n<reasoning>\n- ok\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _CaptureRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", lambda *args, **kwargs: _EchoLLM())
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")

    brain = AgentBrain(model_id="groq/llama-3.3-70b-versatile")
    _ = asyncio.run(brain.chat(user_message="check btc"))

    runtime_state = _CaptureRuntime.last_tool_states or {}
    assert runtime_state.get("runtime_model_provider") == "groq"
    assert runtime_state.get("runtime_model_id") == "groq/llama-3.3-70b-versatile"
    assert runtime_state.get("planner_source") == "ai"
    assert runtime_state.get("planner_model_id") == "groq/llama-3.3-70b-versatile"
    assert runtime_state.get("planner_fallback") == "none"
    assert runtime_state.get("web_observation_enabled") is True
    assert runtime_state.get("web_observation_mode") == "speed"
    assert runtime_state.get("memory_enabled") is False
    assert runtime_state.get("knowledge_enabled") is True
    assert runtime_state.get("knowledge_top_k") == 4


def test_chat_stores_memory_turn_when_memory_enabled(monkeypatch):
    class _EchoLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>ok</final>\n<reasoning>\n- ok\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    calls = []

    async def _fake_add_memory_messages(user_id, messages, metadata=None):
        calls.append({"user_id": user_id, "messages": messages, "metadata": metadata or {}})
        return {"stored": True}

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", lambda *args, **kwargs: _EchoLLM())
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.add_memory_messages", _fake_add_memory_messages)

    brain = AgentBrain(
        model_id="test/model",
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


def test_chat_rotates_to_next_groq_key_on_rate_limit(monkeypatch):
    class _PrimaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _SecondaryGroqLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>secondary-ok</final>\n<reasoning>\n- switched\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    primary = _PrimaryGroqLLM()
    secondary = _SecondaryGroqLLM()

    def _fake_get_llm(model_id, **kwargs):
        if kwargs.get("groq_key_index") == 1:
            return secondary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2"])

    brain = AgentBrain(model_id="groq/openai/gpt-oss-120b")
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "secondary-ok"
    assert brain._groq_key_index == 1


def test_deepagents_rotates_to_next_groq_key_on_rate_limit(monkeypatch):
    class _PrimaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _SecondaryGroqLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>secondary-ok</final>\n<reasoning>\n- switched\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    class _FakeDeepRuntime:
        def __init__(self, llm, system_prompt, tool_states):
            self.llm = llm

        @staticmethod
        def is_available():
            return True

        async def run_chat(self, user_message, history=None, attachments=None):
            if isinstance(self.llm, _PrimaryGroqLLM):
                raise RuntimeError("429 Too Many Requests: rate limit reached")
            return {
                "content": "secondary-deep-ok",
                "usage": {},
                "thoughts": ["switched"],
                "runtime": {"plan": None, "tool_results": [], "phases": []},
            }

    primary = _PrimaryGroqLLM()
    secondary = _SecondaryGroqLLM()

    def _fake_get_llm(model_id, **kwargs):
        if kwargs.get("groq_key_index") == 1:
            return secondary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2"])
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _FakeDeepRuntime)

    brain = AgentBrain(
        model_id="groq/openai/gpt-oss-120b",
        tool_states={"agent_engine": "deepagents", "agent_engine_strict": True},
    )
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "secondary-deep-ok"
    assert brain._groq_key_index == 1


def test_chat_rotates_until_tertiary_when_secondary_also_rate_limited(monkeypatch):
    class _PrimaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _SecondaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _TertiaryGroqLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>tertiary-ok</final>\n<reasoning>\n- switched\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    primary = _PrimaryGroqLLM()
    secondary = _SecondaryGroqLLM()
    tertiary = _TertiaryGroqLLM()

    def _fake_get_llm(model_id, **kwargs):
        index = kwargs.get("groq_key_index", 0)
        if index == 1:
            return secondary
        if index == 2:
            return tertiary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2", "k3", "k4"])

    brain = AgentBrain(model_id="groq/openai/gpt-oss-120b")
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "tertiary-ok"
    assert brain._groq_key_index == 2


def test_chat_rotates_until_quaternary_when_first_three_rate_limited(monkeypatch):
    class _PrimaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _SecondaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _TertiaryGroqLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("429 Too Many Requests: rate limit reached")

        async def astream(self, messages):
            if False:
                yield messages

    class _QuaternaryGroqLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="<final>quaternary-ok</final>\n<reasoning>\n- switched\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    primary = _PrimaryGroqLLM()
    secondary = _SecondaryGroqLLM()
    tertiary = _TertiaryGroqLLM()
    quaternary = _QuaternaryGroqLLM()

    def _fake_get_llm(model_id, **kwargs):
        index = kwargs.get("groq_key_index", 0)
        if index == 1:
            return secondary
        if index == 2:
            return tertiary
        if index == 3:
            return quaternary
        return primary

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2", "k3", "k4"])

    brain = AgentBrain(model_id="groq/openai/gpt-oss-120b")
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "quaternary-ok"
    assert brain._groq_key_index == 3


def test_deepagents_rotates_until_quaternary_when_first_three_rate_limited(monkeypatch):
    class _GroqLLM:
        def __init__(self, name: str):
            self.name = name

        async def ainvoke(self, messages):
            if self.name != "quaternary":
                raise RuntimeError("429 Too Many Requests: rate limit reached")
            return AIMessage(content="<final>quaternary-deep-ok</final>\n<reasoning>\n- switched\n</reasoning>")

        async def astream(self, messages):
            if False:
                yield messages

    class _FakeDeepRuntime:
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

    monkeypatch.setattr("backend.agent.Core.agent_brain.AgenticTradingRuntime", _FakeRuntime)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_llm", _fake_get_llm)
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.get_system_prompt", lambda *args, **kwargs: "system")
    monkeypatch.setattr("backend.agent.Core.agent_brain.LLMFactory.groq_api_keys", lambda: ["k1", "k2", "k3", "k4"])
    monkeypatch.setattr("backend.agent.Core.agent_brain.DeepAgentsRuntime", _FakeDeepRuntime)

    brain = AgentBrain(
        model_id="groq/openai/gpt-oss-120b",
        tool_states={"agent_engine": "deepagents", "agent_engine_strict": True},
    )
    result = asyncio.run(brain.chat(user_message="check btc"))

    assert result["content"] == "quaternary-deep-ok"
    assert brain._groq_key_index == 3
