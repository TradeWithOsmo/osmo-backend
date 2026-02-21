"""
Base Tool wrapper for integrating tools with LangChain agents.
Provides a foundation for creating custom tools.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain_core.tools import BaseTool, tool


class LangChainTool(BaseTool, ABC):
    """Base class for LangChain-compatible tools."""

    name: str
    description: str

    @abstractmethod
    def _run(self, *args: Any, **kwargs: Any) -> str:
        """Execute the tool. Must be implemented by subclasses."""
        raise NotImplementedError

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Async execution. Override if tool supports async."""
        return self._run(*args, **kwargs)


def create_simple_tool(
    name: str,
    description: str,
    func,
    args_schema: Optional[Any] = None,
) -> BaseTool:
    """
    Create a simple LangChain tool from a function.

    Args:
        name: Tool name
        description: Tool description
        func: The function to wrap
        args_schema: Pydantic model for arguments

    Returns:
        BaseTool instance
    """

    @tool(name, args_schema=args_schema)
    def wrapped_tool(*args, **kwargs):
        """Runtime-generated simple tool wrapper."""
        return func(*args, **kwargs)

    wrapped_tool.__doc__ = description or wrapped_tool.__doc__
    return wrapped_tool
