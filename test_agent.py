import asyncio
import os
import sys

# Ensure imports work from /app/agent context
sys.path.append("/app/agent")

try:
    from agent.Core.agent_brain import AgentBrain
except ImportError:
    print("Cannot import AgentBrain. Make sure paths are correct.")
    sys.exit(1)

async def test_agent():
    print("Initializing AgentBrain with model alibaba/qwen-plus...")
    
    # Setup test user context (similar to what the router provides)
    user_context = {
        "user_address": "0x0000000000000000000000000000000000000000",
        "session_id": "test_session_123"
    }
    
    # Initialize the brain
    brain = AgentBrain(
        model_id="alibaba/qwen-plus",
        reasoning_effort="medium",
        tool_states={
            "agent_engine": "reflexion",
            "agent_engine_strict": True,
            "knowledge_enabled": False,
            "rag_mode": "disabled"
        },
        user_context=user_context
    )
    
    print("\nSending message: 'hai osmo'...")
    try:
        result = await brain.chat(
            user_message="hai osmo",
            history=[],
            attachments=[]
        )
        
        print("\n================== RESPONSE ==================")
        print(result.get("content", "NO CONTENT"))
        print("==============================================")
        
        usage = result.get("usage", {})
        print(f"\nUsage Stats: IN={usage.get('input_tokens')}, OUT={usage.get('output_tokens')}")
        
    except Exception as e:
        print(f"Error during agent chat: {e}")

if __name__ == "__main__":
    asyncio.run(test_agent())
