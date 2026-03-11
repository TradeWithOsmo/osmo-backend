import asyncio
import os
import sys

# In container, app root is /app
sys.path.append("/app")

try:
    from agent.Core.agent_brain import AgentBrain
except Exception as e:
    print(f"Cannot import AgentBrain in container: {e}")
    sys.exit(1)

async def test_agent_knowledge():
    print("Test in container: Initializing AgentBrain to test exchange knowledge...")
    
    brain = AgentBrain(
        model_id="alibaba/qwen-plus",
        reasoning_effort="medium",
        tool_states={
            "agent_engine": "reflexion",
            "agent_engine_strict": True,
        },
        user_context={}
    )
    
    test_query = "What exchanges or data sources do you support according to your core system instructions? List them by name."
    print(f"\nSending message: '{test_query}'...")
    
    try:
        result = await brain.chat(
            user_message=test_query,
            history=[],
            attachments=[]
        )
        
        print("\n================== AGENT RESPONSE ==================")
        print(result.get("content", "NO CONTENT"))
        print("====================================================")
        
    except Exception as e:
        print(f"Error during agent chat in container: {e}")

if __name__ == "__main__":
    asyncio.run(test_agent_knowledge())
