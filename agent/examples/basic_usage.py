"""
Basic usage example of the Osmo Agent.
Demonstrates simple agent initialization and invocation.
"""

import asyncio
import logging
import os

# Add parent directory to path for imports
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.chains import Agent
from src.core import LLMFactory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


async def example_basic_agent():
    """
    Example 1: Basic agent without tools
    """
    logger.info("Example 1: Basic Agent Usage")
    print("\n" + "=" * 50)
    print("Example 1: Basic Agent")
    print("=" * 50)

    # Create agent
    agent = Agent(
        name="BasicAgent",
        model_id="anthropic/claude-3.5-sonnet",
        temperature=0.7,
    )

    # Get agent info
    print(f"\nAgent Info: {agent.get_agent_info()}")

    # Invoke agent
    response = await agent.ainvoke("What is the capital of France?")
    print(f"\nUser: What is the capital of France?")
    print(f"Agent: {response['output']}")


async def example_llm_factory():
    """
    Example 2: Direct LLM Factory usage
    """
    logger.info("Example 2: LLM Factory Usage")
    print("\n" + "=" * 50)
    print("Example 2: LLM Factory")
    print("=" * 50)

    # Get different models
    models = [
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus",
        "openai/gpt-4o",
    ]

    for model_id in models:
        try:
            llm = LLMFactory.get_llm(model_id=model_id, temperature=0.5)
            print(f"\n✓ Successfully initialized: {model_id}")
        except Exception as e:
            print(f"\n✗ Failed to initialize {model_id}: {e}")


async def example_streaming():
    """
    Example 3: Streaming responses
    """
    logger.info("Example 3: Streaming Responses")
    print("\n" + "=" * 50)
    print("Example 3: Streaming")
    print("=" * 50)

    agent = Agent(
        name="StreamingAgent",
        model_id="anthropic/claude-3.5-sonnet",
        temperature=0.7,
    )

    print("\nUser: Tell me a short story about a robot")
    print("\nAgent Response (streaming):")
    print("-" * 40)

    async for chunk in agent.astream("Tell me a short story about a robot"):
        if "steps" not in str(chunk):
            print(chunk, end="", flush=True)

    print("\n" + "-" * 40)


async def example_agent_info():
    """
    Example 4: Get agent information
    """
    logger.info("Example 4: Agent Information")
    print("\n" + "=" * 50)
    print("Example 4: Agent Information")
    print("=" * 50)

    agent = Agent(
        name="InfoAgent",
        model_id="anthropic/claude-3.5-sonnet",
        temperature=0.7,
    )

    info = agent.get_agent_info()
    print(f"\nAgent Information:")
    for key, value in info.items():
        print(f"  {key}: {value}")


async def main():
    """Run all examples"""
    print("\n" + "=" * 50)
    print("Osmo Agent - Usage Examples")
    print("=" * 50)

    try:
        # Run examples
        await example_basic_agent()
        await example_llm_factory()
        await example_agent_info()
        # await example_streaming()  # Uncomment to test streaming

        print("\n" + "=" * 50)
        print("All examples completed successfully!")
        print("=" * 50 + "\n")

    except Exception as e:
        logger.error(f"Error running examples: {e}")
        print(f"\nError: {e}")


if __name__ == "__main__":
    asyncio.run(main())
