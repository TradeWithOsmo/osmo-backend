from __future__ import annotations

from typing import Dict, List

from .schema import BenchmarkTask, EffortProfile


def _policy_instructions(flags: List[str]) -> str:
    chunks: List[str] = []
    if "CONTEXT_AUDIT" in flags:
        chunks.append(
            "Before answering, explicitly extract entities, constraints, and objective from references."
        )
    if "LOGICAL_REASONING" in flags:
        chunks.append(
            "Use explicit logical checks and verify each major inference against given facts."
        )
    if "CALIBRATION_CHECK" in flags:
        chunks.append(
            "Calibrate confidence numerically (0..1) based on evidence strength and uncertainty."
        )
    if "SELF_EVALUATION" in flags:
        chunks.append(
            "Self-evaluate your draft, identify issues, and revise when needed."
        )
    if "ERROR_ANALYSIS" in flags:
        chunks.append(
            "Actively list potential failure points and edge cases before finalizing."
        )
    if "ITERATIVE_REFINEMENT" in flags:
        chunks.append(
            "Compare at least two candidate answers internally and keep the best-supported one."
        )
    if "TOOL_MINIMALITY" in flags:
        chunks.append(
            "Use minimal tools. Propose tools only when they materially improve correctness."
        )
    return "\n".join(f"- {line}" for line in chunks)


def build_messages(
    task: BenchmarkTask,
    references: Dict[str, str],
    profile: EffortProfile,
    max_references: int,
) -> List[Dict[str, str]]:
    selected_refs: List[str] = []
    for ref_id in task.reference_ids[:max_references]:
        value = references.get(ref_id)
        if value:
            selected_refs.append(f"{ref_id}: {value}")

    references_block = "\n".join(selected_refs) if selected_refs else "none"
    allowed_tools = ", ".join(task.allowed_tools) if task.allowed_tools else "none"
    policy_block = _policy_instructions(profile.prompt_flags)

    system_prompt = (
        "You are a Codex-style reasoning evaluator candidate.\n"
        "Follow strict phases: CONTEXT -> REASON -> ACTION PLAN -> VALIDATION -> FINAL.\n"
        "Do not expose chain-of-thought. Provide concise high-level checks only.\n"
        "Return strict JSON with fields:\n"
        "{\n"
        '  "final_answer": "string",\n'
        '  "confidence": 0.0,\n'
        '  "context_summary": ["..."],\n'
        '  "reasoning_checks": ["..."],\n'
        '  "self_evaluation": {"status":"pass|fail|uncertain","issues":["..."],"revised_answer":"optional"},\n'
        '  "tool_plan": [{"tool":"name","needed":true,"purpose":"..."}]\n'
        "}\n"
        f"Reasoning effort profile: {profile.effort}.\n"
        "Policy directives:\n"
        f"{policy_block if policy_block else '- Keep baseline behavior.'}"
    )

    user_prompt = (
        f"Task ID: {task.id}\n"
        f"Category: {task.category}\n"
        f"Difficulty: {task.difficulty}\n"
        f"Allowed tools: {allowed_tools}\n"
        f"Maximum tool calls: {min(task.max_tool_calls, profile.tool_budget)}\n"
        "References:\n"
        f"{references_block}\n\n"
        "Task:\n"
        f"{task.prompt}\n"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

