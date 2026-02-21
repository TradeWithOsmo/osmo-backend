"""
Main Agent Implementation using LangChain
Orchestrates the agent workflow with tools and chain management
"""

import logging
from typing import Any, Dict, List, Optional, Union

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from ..core import LLMFactory
from ..utils.prompts import build_system_prompt

logger = logging.getLogger(__name__)


class Agent:
    """
    Main agent class that orchestrates LangChain-based AI agent workflows.
    Supports tool integration, custom prompts, and multiple LLM providers.
    """

    def __init__(
        self,
        name: str,
        model_id: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.7,
        tools: Optional[List[BaseTool]] = None,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        verbose: bool = False,
    ):
        """
        Initialize the agent.

        Args:
            name: Agent name identifier
            model_id: LLM model to use (default: Groq Mixtral)
            temperature: LLM temperature (0.0-1.0)
            tools: List of tools available to agent
            system_prompt: Custom system prompt
            max_iterations: Maximum agent iterations before stopping
            verbose: Enable verbose logging
        """
        self.name = name
        self.model_id = model_id
        self.temperature = temperature
        self.tools = tools or []
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Initialize LLM
        self.llm = LLMFactory.get_llm(
            model_id=model_id,
            temperature=temperature,
        )

        # Set system prompt
        self.system_prompt = system_prompt or self._build_default_prompt()

        # Initialize executor
        self.executor: Optional[AgentExecutor] = None
        if self.tools:
            self._initialize_executor()

        logger.info(
            f"Agent '{name}' initialized with model {model_id} "
            f"and {len(self.tools)} tools"
        )

    def _build_default_prompt(self) -> str:
        """Build the default system prompt for this agent."""
        base_prompt = f"""You are {self.name}, a helpful AI assistant.
You have access to tools to complete tasks efficiently.
Follow these guidelines:
- Be clear and concise in your responses
- Use available tools when appropriate
- Provide reasoning for your actions
- Ask for clarification when needed"""

        tool_states = None
        if self.tools:
            tool_states = {tool.name: {"enabled": True} for tool in self.tools}

        return build_system_prompt(tool_states=tool_states)

    def _initialize_executor(self) -> None:
        """Initialize the agent executor with tools."""
        if not self.tools:
            logger.warning(f"Agent {self.name} has no tools configured")
            return

        # Create prompt template
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        # Create tool-calling agent
        agent = create_tool_calling_agent(self.llm, self.tools, prompt)

        # Create executor
        self.executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            max_iterations=self.max_iterations,
            verbose=self.verbose,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

        logger.info(f"Executor initialized for agent {self.name}")

    def add_tool(self, tool: BaseTool) -> None:
        """
        Add a single tool to the agent.

        Args:
            tool: Tool to add
        """
        self.tools.append(tool)
        self._initialize_executor()
        logger.info(f"Tool {tool.name} added to agent {self.name}")

    def add_tools(self, tools: List[BaseTool]) -> None:
        """
        Add multiple tools to the agent.

        Args:
            tools: List of tools to add
        """
        self.tools.extend(tools)
        self._initialize_executor()
        logger.info(f"Added {len(tools)} tools to agent {self.name}")

    def get_tools(self) -> List[BaseTool]:
        """Get list of available tools."""
        return self.tools

    def get_tools_description(self) -> Dict[str, str]:
        """Get description of all available tools."""
        return {tool.name: tool.description for tool in self.tools}

    async def ainvoke(
        self,
        input_data: Union[str, Dict[str, Any]],
        chat_history: Optional[List[BaseMessage]] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously invoke the agent.

        Args:
            input_data: User input (string or dict)
            chat_history: Previous conversation messages

        Returns:
            Agent response dictionary with output and steps
        """
        if isinstance(input_data, str):
            input_data = {"input": input_data}

        if chat_history:
            input_data["chat_history"] = chat_history

        try:
            if self.executor:
                result = await self.executor.ainvoke(input_data)
            else:
                # Fallback: Direct LLM call without tools
                logger.warning(
                    f"No executor for agent {self.name}, using direct LLM call"
                )
                result = await self._direct_llm_call(input_data["input"])

            logger.info(f"Agent {self.name} invocation successful")
            return result

        except Exception as e:
            logger.error(f"Error invoking agent {self.name}: {e}")
            raise

    async def astream(
        self,
        input_data: Union[str, Dict[str, Any]],
        chat_history: Optional[List[BaseMessage]] = None,
    ):
        """
        Stream agent response asynchronously.

        Args:
            input_data: User input
            chat_history: Previous conversation messages

        Yields:
            Response chunks
        """
        if isinstance(input_data, str):
            input_data = {"input": input_data}

        if chat_history:
            input_data["chat_history"] = chat_history

        try:
            if self.executor:
                async for chunk in self.executor.astream(input_data):
                    yield chunk
            else:
                # Fallback: Direct LLM streaming
                async for chunk in self.llm.astream(
                    [HumanMessage(content=input_data["input"])]
                ):
                    yield chunk

        except Exception as e:
            logger.error(f"Error streaming agent {self.name}: {e}")
            raise

    async def _direct_llm_call(self, user_input: str) -> Dict[str, Any]:
        """
        Make a direct LLM call without tools.

        Args:
            user_input: User input string

        Returns:
            Response dictionary
        """
        message = await self.llm.ainvoke([HumanMessage(content=user_input)])
        return {
            "input": user_input,
            "output": message.content,
            "output_message": message,
            "intermediate_steps": [],
        }

    def update_system_prompt(self, new_prompt: str) -> None:
        """
        Update the system prompt for the agent.

        Args:
            new_prompt: New system prompt text
        """
        self.system_prompt = new_prompt
        if self.tools:
            self._initialize_executor()
        logger.info(f"System prompt updated for agent {self.name}")

    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get information about the agent.

        Returns:
            Dictionary with agent metadata
        """
        return {
            "name": self.name,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "tools_count": len(self.tools),
            "max_iterations": self.max_iterations,
            "tools": self.get_tools_description(),
        }

    def __repr__(self) -> str:
        """String representation of the agent."""
        return (
            f"Agent(name={self.name}, model={self.model_id}, tools={len(self.tools)})"
        )
