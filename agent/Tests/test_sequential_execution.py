"""
Test Sequential Tool Execution Enforcement

Verifikasi bahwa agent hanya menjalankan 1 tool pada satu waktu,
bukan parallel batch execution.
"""

import asyncio
import time
from typing import Dict, Any, List
from unittest.mock import Mock, AsyncMock, patch
import pytest

# Mock untuk testing tanpa dependencies penuh
class MockToolOrchestrator:
    async def run_tool(self, tool_call, tool_states):
        """Simulate tool execution dengan delay untuk test concurrency."""
        await asyncio.sleep(0.1)  # Simulate network call
        from backend.agent.Schema.agent_runtime import ToolResult
        return ToolResult(
            name=tool_call.name,
            args=tool_call.args,
            ok=True,
            data={"result": f"mock_{tool_call.name}"},
            error=None,
            latency_ms=100,
        )


@pytest.mark.asyncio
async def test_sequential_tool_execution():
    """Test bahwa tools dijalankan sequential, bukan parallel."""
    from backend.agent.Core.deepagents_runtime import DeepAgentsRuntime
    from backend.agent.Schema.agent_runtime import ToolCall
    
    # Setup mock runtime
    mock_llm = Mock()
    runtime = DeepAgentsRuntime(
        llm=mock_llm,
        system_prompt="Test prompt",
        tool_states={},
        tool_timeout_sec=5.0,
    )
    
    # Track execution timestamps
    execution_log: List[Dict[str, Any]] = []
    
    # Mock wrapper untuk capture execution timing
    original_wrapped = runtime._build_wrapped_tools
    
    async def tracking_wrapper(*args, **kwargs):
        tools = original_wrapped(*args, **kwargs)
        # Inject timing tracker
        for tool in tools:
            original_call = tool
            async def tracked_call(*call_args, __name=tool.__name__, **call_kwargs):
                start = time.time()
                execution_log.append({
                    "tool": __name,
                    "event": "start",
                    "timestamp": start,
                })
                result = await original_call(*call_args, **call_kwargs)
                end = time.time()
                execution_log.append({
                    "tool": __name,
                    "event": "end",
                    "timestamp": end,
                })
                return result
            tracked_call.__name__ = tool.__name__
            tracked_call.__signature__ = tool.__signature__
        return tools
    
    runtime._build_wrapped_tools = tracking_wrapper
    runtime._orchestrator = MockToolOrchestrator()
    
    # Simulate parallel call attempts
    tools = await runtime._build_wrapped_tools(user_message="test")
    
    # Try to call 3 tools "simultaneously"
    tasks = []
    for i, tool in enumerate(tools[:3]):
        tasks.append(tool())
    
    # Execute all tasks
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time
    
    # Verify sequential execution
    # If parallel: ~0.1s total (all run together)
    # If sequential: ~0.3s total (3 tools × 0.1s each)
    
    assert total_time >= 0.25, (
        f"Tools ran in parallel! Expected >=0.25s, got {total_time:.2f}s. "
        "This indicates concurrent execution instead of sequential."
    )
    
    # Verify no overlap in execution windows
    for i in range(len(execution_log) - 1):
        current = execution_log[i]
        next_event = execution_log[i + 1]
        
        if current["event"] == "start" and next_event["event"] == "start":
            # Two tools started at the same time = parallel execution!
            assert False, (
                f"Parallel execution detected! "
                f"{current['tool']} and {next_event['tool']} started concurrently."
            )
    
    print(f"✅ Sequential execution verified! Total time: {total_time:.2f}s")
    print(f"✅ Execution log: {len(execution_log)} events tracked")


@pytest.mark.asyncio
async def test_semaphore_enforcement():
    """Test bahwa semaphore lock bekerja dengan benar."""
    from backend.agent.Core.deepagents_runtime import DeepAgentsRuntime
    
    mock_llm = Mock()
    runtime = DeepAgentsRuntime(
        llm=mock_llm,
        system_prompt="Test",
        tool_states={},
    )
    
    # Verify semaphore initialized
    assert runtime._tool_execution_lock is not None
    assert isinstance(runtime._tool_execution_lock, asyncio.Semaphore)
    
    # Verify only 1 concurrent allowed
    assert runtime._tool_execution_lock._value == 1
    
    # Test acquire/release
    acquired = runtime._tool_execution_lock.locked()
    assert not acquired, "Lock should be free initially"
    
    # Acquire lock
    await runtime._tool_execution_lock.acquire()
    assert runtime._tool_execution_lock.locked(), "Lock should be held"
    
    # Release
    runtime._tool_execution_lock.release()
    assert not runtime._tool_execution_lock.locked(), "Lock should be free after release"
    
    print("✅ Semaphore enforcement verified!")


@pytest.mark.asyncio
async def test_runtime_prompt_includes_sequential_warning():
    """Test bahwa runtime prompt menginformasikan sequential enforcement."""
    from backend.agent.Core.deepagents_runtime import DeepAgentsRuntime
    
    mock_llm = Mock()
    runtime = DeepAgentsRuntime(
        llm=mock_llm,
        system_prompt="Test",
        tool_states={"strict_react": True},
    )
    
    prompt = runtime._build_runtime_prompt()
    
    # Verify prompt includes sequential enforcement warning
    assert "ENFORCED at system level" in prompt, (
        "Prompt should explicitly mention system-level enforcement"
    )
    assert "CANNOT call multiple tools in parallel" in prompt, (
        "Prompt should warn against parallel tool calling"
    )
    assert "block until completion" in prompt, (
        "Prompt should explain blocking behavior"
    )
    
    print("✅ Runtime prompt correctly warns about sequential enforcement!")
    print(f"Prompt excerpt:\n{prompt[:500]}...")


if __name__ == "__main__":
    print("Running Sequential Execution Tests...\n")
    
    # Run tests
    asyncio.run(test_semaphore_enforcement())
    asyncio.run(test_runtime_prompt_includes_sequential_warning())
    # asyncio.run(test_sequential_tool_execution())  # Requires full agent setup
    
    print("\n✅ All basic tests passed!")
