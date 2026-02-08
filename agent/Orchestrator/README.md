# Agentic Trading Runtime

This module implements a Codex-like loop for trading assistance:

1. `planner.py` creates a compact `AgentPlan` from user intent.
2. `risk_gate.py` blocks unsafe execution intents when execution mode is off.
3. `tool_registry.py` maps tool names to functions under `backend/agent/Tools`.
4. `runtime.py` executes the plan with timeouts and builds prompt-ready runtime context.

## Runtime Flow

```text
User Message
  -> Plan (symbol/timeframe/intent/tool calls)
  -> Guardrails (warnings/blocks)
  -> Tool Execution (async + timeout + audit)
  -> Runtime Context
  -> LLM Synthesis (AgentBrain)
```

## Design Notes

- Knowledge retrieval is intentionally excluded for now.
- Tool execution is read-focused by default.
- Execution requests are blocked unless `tool_states.execution = true`.
- Tool output is truncated before prompt injection to control token cost.

