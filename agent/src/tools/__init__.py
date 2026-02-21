"""
Tools module for LangChain agent.
Integrates compatibility wrappers and LangChain helper base classes.
"""

from .base_tool import LangChainTool, create_simple_tool

__all__ = ["LangChainTool", "create_simple_tool"]
