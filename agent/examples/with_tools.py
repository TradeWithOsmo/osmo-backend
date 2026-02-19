"""
Example: Using the Agent with Tools

This example demonstrates how to create an agent with tools
and use it to solve problems.
"""

import asyncio
import logging
from typing import Optional

from langchain_core.tools import tool
from src.chains import Agent
from src.utils import get_env, require_env

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define some example tools
@tool
def calculator(expression: str) -> str:
    """
    A simple calculator tool that evaluates mathematical expressions.
    Input should be a valid Python mathematical expression.
    """
    try:
        result = eval(expression)
        return f"The result of {expression} is {result}"
    except Exception as e:
        return f"Error evaluating expression: {str(e)}"


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def search_knowledge(query: str) -> str:
    """
    Search through a knowledge base.
    This is a placeholder for a real knowledge base search.
    """
    knowledge_base = {
        "python": "Python is a high-level programming language",
        "langchain": "LangChain is a framework for developing applications powered by language models",
        "agent": "An agent is an autonomous entity that perceives and acts in an environment",
    }

    query_lower = query.lower()
    for key, value in knowledge_base.items():
        if key in query_lower:
            return value

    return f"No information found for '{query}'"


async def main():
    """Main example function."""

    # Get configuration from environment
    model_id = get_env("DEFAULT_MODEL", "anthropic/claude-3.5-sonnet")
    temperature = float(get_env("DEFAULT_TEMPERATURE", "0.7"))

    # Create an agent with tools
    agent = Agent(
        name="ToolAgent",
        model_id=model_id,
        temperature=temperature,
        tools=[calculator, get_current_time, search_knowledge],
        verbose=True,
    )

    # Print agent info
    print("\n" + "=" * 60)
    print("Agent Information")
    print("=" * 60)
    print(f"Name: {agent.name}")
    print(f"Model: {agent.model_id}")
    print(f"Temperature: {agent.temperature}")
    print(f"Available Tools: {len(agent.get_tools())}")
    print("\nTools Description:")
    for tool_name, description in agent.get_tools_description().items():
        print(f"  - {tool_name}: {description}")

    # Example queries
    queries = [
        "What is 25 * 4 + 10?",
        "What time is it right now?",
        "Tell me about langchain",
        "Calculate the square root of 144 divided by 12",
    ]

    print("\n" + "=" * 60)
    print("Running Agent with Sample Queries")
    print("=" * 60)

    for query in queries:
        print(f"\nQuery: {query}")
        print("-" * 60)
        try:
            result = await agent.ainvoke(query)
            print(f"Response: {result.get('output', 'No output')}")

            # Print intermediate steps if available
            if result.get("intermediate_steps"):
                print("\nIntermediate Steps:")
                for step in result["intermediate_steps"]:
                    print(f"  {step}")

        except Exception as e:
            logger.error(f"Error processing query: {e}")


async def interactive_mode():
    """Run the agent in interactive mode."""

    # Create agent with tools
    agent = Agent(
        name="InteractiveAgent",
        model_id=get_env("DEFAULT_MODEL", "anthropic/claude-3.5-sonnet"),
        temperature=float(get_env("DEFAULT_TEMPERATURE", "0.7")),
        tools=[calculator, get_current_time, search_knowledge],
        verbose=False,
    )

    print("\n" + "=" * 60)
    print("Interactive Agent with Tools")
    print("=" * 60)
    print("Type 'exit' or 'quit' to exit")
    print("Available tools:")
    for tool_name in agent.get_tools_description():
        print(f"  - {tool_name}")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            if not user_input:
                continue

            print("\nAgent is thinking...")
            result = await agent.ainvoke(user_input)
            print(f"\nAgent: {result.get('output', 'No response')}")

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"Error: {e}")


if __name__ == "__main__":
    import sys

    # Run batch examples
    print("\n🚀 Starting Agent with Tools Example")
    asyncio.run(main())

    # Optionally run interactive mode
    # Uncomment the line below to run interactive mode instead
    # asyncio.run(interactive_mode())
