"""
Base Agent class using LangChain
Provides core functionality for building agents with tool support
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from .llm_factory import LLMFactory


class BaseAgent(ABC):
    """
    Base agent class providing core functionality for LangChain agents.
    """

    def __init__(
        self,
        name: str,
        model_id: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.7,
        tools: Optional[List[BaseTool]] = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Initialize the base agent.

        Args:
            name: Name of the agent
            model_id: LLM model identifier
            temperature: Temperature for LLM sampling
            tools: List of tools available to the agent
            system_prompt: Custom system prompt
        """
        self.name = name
        self.model_id = model_id
        self.temperature = temperature
        self.tools = tools or []
        self.system_prompt = system_prompt or self._default_system_prompt()

        # Initialize LLM
        self.llm = LLMFactory.get_llm(
            model_id=model_id,
            temperature=temperature,
        )

        # Initialize executor if tools are provided
        self.executor: Optional[AgentExecutor] = None
        if self.tools:
            self._setup_executor()

    def _default_system_prompt(self) -> str:
        """Default system prompt for the agent."""
        return f"""You are {self.name}, a helpful AI assistant.
You have access to various tools to complete tasks.
Be precise, clear, and helpful in your responses.
Always use the appropriate tools when needed."""

    def _setup_executor(self) -> None:
        """Setup the agent executor with tools."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        self.executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
        )

    def add_tools(self, tools: List[BaseTool]) -> None:
        """Add tools to the agent."""
        self.tools.extend(tools)
        if self.executor:
            self._setup_executor()

    async def invoke(
        self,
        input_data: Union[str, Dict[str, Any]],
        chat_history: Optional[List[BaseMessage]] = None,
    ) -> Dict[str, Any]:
        """
        Invoke the agent with input.

        Args:
            input_data: Input string or dict
            chat_history: Previous messages for context

        Returns:
            Agent response
        """
        if isinstance(input_data, str):
            input_data = {"input": input_data}

        if chat_history:
            input_data["chat_history"] = chat_history

        if self.executor:
            return await self.executor.ainvoke(input_data)
        else:
            # Fallback to direct LLM call without tools
            from langchain_core.messages import HumanMessage

            result = await self.llm.ainvoke([HumanMessage(content=input_data["input"])])
            return {"output": result.content}

    async def stream(
        self,
        input_data: Union[str, Dict[str, Any]],
        chat_history: Optional[List[BaseMessage]] = None,
    ):
        """
        Stream the agent response.

        Args:
            input_data: Input string or dict
            chat_history: Previous messages for context

        Yields:
            Streamed chunks
        """
        if isinstance(input_data, str):
            input_data = {"input": input_data}

        if chat_history:
            input_data["chat_history"] = chat_history

        if self.executor:
            async for chunk in self.executor.astream(input_data):
                yield chunk
        else:
            # Fallback to direct LLM streaming
            from langchain_core.messages import HumanMessage

            async for chunk in self.llm.astream(
                [HumanMessage(content=input_data["input"])]
            ):
                yield chunk

    def get_tools_description(self) -> Dict[str, str]:
        """Get descriptions of available tools."""
        return {tool.name: tool.description for tool in self.tools}

    @abstractmethod
    def configure(self) -> None:
        """Configure agent-specific settings. Must be implemented by subclasses."""
        pass
