"""
Agent Brain
Core logic for the Osmo AI Agent.
Handles model routing, prompt preparation, and execution.
"""

from typing import List, Dict, Any
from agent.Core.llm_factory import LLMFactory

class AgentBrain:
    """The central intelligence unit for Osmo."""
    
    def __init__(self, model_id: str = "anthropic/claude-3.5-sonnet"):
        self.model_id = model_id
        self.llm = LLMFactory.get_llm(model_id)
        self.system_prompt = LLMFactory.get_system_prompt(model_id)
        
    async def chat(self, user_message: str, history: List[Dict[str, str]] = None) -> str:
        """
        Processes a user message and returns the response.
        
        Args:
            user_message: The current user message.
            history: Optional list of previous messages [{"role": "user", "content": "..."}]
            
        Returns:
            AI response string.
        """
        # Prepare messages
        messages = [{"role": "system", "content": self.system_prompt}]
        
        if history:
            messages.extend(history)
            
        messages.append({"role": "user", "content": user_message})
        
        # Call LLM
        # Note: In a real implementation with LangChain, we'd use invoke() 
        # but here we're keeping it modular for high-level logic.
        response = await self.llm.ainvoke(messages)
        return response.content
