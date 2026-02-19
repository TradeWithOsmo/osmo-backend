"""
Tools module for LangChain agent.
Integrates legacy tools and new Langchain-compatible tools.
"""

from .base_tool import LangChainTool, create_simple_tool

__all__ = ["LangChainTool", "create_simple_tool"]
