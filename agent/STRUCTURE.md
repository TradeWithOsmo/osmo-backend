# Backend Structure Documentation

## Overview
This document outlines the directory structure and responsibility of each module within the `backend/agent` directory. This structure is designed to support a complex, modular, and scalable AI trading agent system.

## Directory Structure
```text
backend/agent/
├── Config/            # Configuration settings (API keys, Env settings, Agent behavior flags)
├── Core/              # The "Brain" of the agent
│   └── (Contains main logic for planning, thinking loops, and decision making)
├── Evaluators/        # Self-correction logic
│   └── (Contains logic to critique and verify agent outputs before sending)
├── Guardrails/        # Safety filters 
│   └── (Contains input/output validation rules to prevent harmful actions)
├── Hooks/             # Event-driven hooks
│   └── (Contains lifecycle triggers like on_message_received, on_error, etc.)
├── Knowledge/         # RAG & Knowledge Base
│   └── (Contains static data like trading patterns JSON, strategy manuals, and loaders)
├── Memory/            # Agent's short-term and long-term memory
│   └── (Contains logic to manage chat history and database interactions)
├── Orchestrator/      # Advanced multi-agent coordination
│   └── (Contains logic for managing sub-agents or complex multi-step workflows)
├── Prompts/           # System instructions
│   └── (Contains the raw text prompts and system instructions for the LLM)
├── Resources/         # External References & Documentation
│   └── (Contains offline documentation, research papers, and reference guides, e.g., Langchain docs)
├── Schema/            # Data Types & Models
│   └── (Contains Pydantic definitions for requests, responses, and internal data structures)
├── Tools/             # Agent Capabilities
│   └── (Contains the actual functions the agent can call, e.g., market data fetchers, calculators, web browsers)
└── Utils/             # Helper functions
    └── (Contains shared utilities like loggers, string parsers, and formatters)
```

## Key Modules Explanation

### 1. Core
This directory holds the central logic that drives the agent. It should contain the code responsible for:
- Orchestrating the agent's thought process.
- Implementing the "Think-Act-Observe" loop.
- Deciding which tools to use based on user input.

### 2. Tools
The "Hands" of the agent. This folder contains pure functions that the agent is allowed to execute.
- **Content**: Scripts for fetching market prices, executing database searches, or browsing the web.

### 3. Knowledge (RAG)
The "Library" of the agent. This is where static reference data lives.
- **Content**: Trading pattern definitions (in JSON), strategy documents, and the code required to load or search through these documents.

### 4. Memory
The "Hippocampus". Manages conversation history so the agent remembers context.
- **Content**: Logic to save user chats to the database and retrieve past context when needed.

### 5. Schema
The "Dictionary". Defines strict data structures to ensure communication is consistent.
- **Content**: Class definitions (Models) that describe exactly what a "Request" from the frontend looks like, or what a "Response" from the agent should look like.

### 6. Resources
The "Reference Library". Holds external documentation and guides.
- **Content**: Offline copies of library documentation (e.g., Langchain), research papers, or any non-code reference material helpful for development.

---
*Created automatically to document the current project state.*
