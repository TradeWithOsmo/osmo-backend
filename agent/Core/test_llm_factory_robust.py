
import sys
import os
from dotenv import load_dotenv

# Add paths to sys.path to mimic the docker environment structure
sys.path.append("/app")

# Load environment variables explicitly from the .env file in the websocket directory
env_path = "/app/websocket/.env" 
load_dotenv(dotenv_path=env_path)

try:
    from agent.Core.llm_factory import LLMFactory
    from langchain_core.messages import HumanMessage
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def test_llm():
    try:
        print("Testing LLMFactory with explict environment loading...")
        
        # Verify Key Presence
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("ERROR: OPENROUTER_API_KEY not found in environment!")
            return
        else:
            masked_key = f"{api_key[:10]}...{api_key[-5:]}"
            print(f"OPENROUTER_API_KEY found: {masked_key}")

        # Use a model that definitely exists in OpenRouter
        model_id = "google/gemini-2.0-flash-exp:free" 
        llm = LLMFactory.get_llm(model_id)
        print(f"LLM Initialized successfully: {type(llm)}")
        
        print(f"Attempting to invoke {model_id}...")
        messages = [HumanMessage(content="Hello! Just reply with 'OK'.")]
        response = llm.invoke(messages)
        
        print(f"Response received: {response.content}")
        print("Test PASSED.")
    except Exception as e:
        print(f"Test FAILED with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_llm()
