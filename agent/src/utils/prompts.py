"""
Prompts utility for building system prompts and managing prompt templates.
"""

from typing import Any, Dict, Optional


def build_system_prompt(
    reasoning_effort: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a system prompt with optional reasoning effort and tool states.

    Args:
        reasoning_effort: Level of reasoning effort (low, medium, high)
        tool_states: Dictionary of available tools and their states

    Returns:
        Formatted system prompt string
    """
    base_prompt = """You are a helpful AI assistant designed to assist with various tasks.
You have access to tools that can help you accomplish your goals.
Always be clear, concise, and helpful in your responses.
When using tools, explain your reasoning and next steps."""

    if reasoning_effort:
        base_prompt += f"\n\nReasoning Effort Level: {reasoning_effort.upper()}"

    if tool_states:
        base_prompt += "\n\nAvailable Tools:"
        for tool_name, tool_info in tool_states.items():
            if isinstance(tool_info, dict):
                enabled = bool(tool_info.get("enabled", True))
            elif isinstance(tool_info, bool):
                enabled = tool_info
            elif isinstance(tool_info, str):
                enabled = tool_info.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                    "enabled",
                }
            else:
                enabled = bool(tool_info) if tool_info is not None else True

            status = "Enabled" if enabled else "Disabled"
            base_prompt += f"\n- {tool_name}: {status}"

    return base_prompt


def get_specialized_prompt(model_id: str, base_prompt: str) -> str:
    """
    Get a specialized prompt based on model tier/type.

    Args:
        model_id: The model identifier
        base_prompt: The base system prompt

    Returns:
        Specialized prompt for the model
    """
    if "sovereign" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 2 Active"
    if "oracle" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 3 Active"
    if "quant" in model_id.lower():
        return f"{base_prompt}\n\nStatus: Class 4 Active"

    return base_prompt
