# Reasoning Tuning Framework (Groq)

This module provides a measurable and iterative evaluation-improvement loop for reasoning quality.

## What it does

- Evaluates reasoning in four effort levels:
`low`, `medium`, `high`, `extra_high`.
- Scores each task across:
`correctness`, `context_accuracy`, `logical_reasoning`, `calibration`,
`self_evaluation`, `iterative_refinement`, `tool_alignment`, `consistency`.
- Runs iterative policy tuning:
error analysis -> profile updates -> re-evaluation.
- Generates per-round reports and final summary JSON.

## Run (offline mock)

```powershell
python -m backend.agent.Evaluators.reasoning_tuning.cli --offline-mock
```

## Run (Groq)

```powershell
$env:GROQ_API_KEY="your_key"
python -m backend.agent.Evaluators.reasoning_tuning.cli `
  --model-id groq/openai/gpt-oss-120b `
  --wallet-address 0x31B91aDB9EC04a3BE391D4899E4ba0572DA32Bfc `
  --max-rounds 8 `
  --target-success 1.0
```

## Output

- Round reports:
`backend/agent/Evaluators/reasoning_tuning/reports/round_XX.json`
- Final report:
`backend/agent/Evaluators/reasoning_tuning/reports/final_report.json`

