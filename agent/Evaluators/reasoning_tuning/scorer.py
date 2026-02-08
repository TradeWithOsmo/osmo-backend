from __future__ import annotations

import json
import re
from dataclasses import asdict
from statistics import mean
from typing import Dict, Iterable, List

from .schema import BenchmarkTask, ModelOutput, TaskMetrics


def parse_model_output(text: str) -> ModelOutput:
    raw = text or ""
    payload = _extract_json(raw)
    if payload is None:
        return ModelOutput(
            final_answer=raw.strip(),
            confidence=0.5,
            context_summary=[],
            reasoning_checks=[],
            self_eval_status="uncertain",
            self_eval_issues=["non_json_output"],
            revised_answer=None,
            tool_plan=[],
            raw_text=raw,
        )

    self_eval = payload.get("self_evaluation", {}) if isinstance(payload, dict) else {}
    tool_plan_raw = payload.get("tool_plan", []) if isinstance(payload, dict) else []
    tools: List[str] = []
    for entry in tool_plan_raw:
        if isinstance(entry, dict) and entry.get("tool"):
            tools.append(str(entry["tool"]))
        elif isinstance(entry, str):
            tools.append(entry)

    confidence = payload.get("confidence", 0.5)
    try:
        confidence_float = float(confidence)
    except Exception:
        confidence_float = 0.5
    confidence_float = min(1.0, max(0.0, confidence_float))

    return ModelOutput(
        final_answer=str(payload.get("final_answer", "")).strip(),
        confidence=confidence_float,
        context_summary=[str(x) for x in payload.get("context_summary", []) if str(x).strip()],
        reasoning_checks=[str(x) for x in payload.get("reasoning_checks", []) if str(x).strip()],
        self_eval_status=str(self_eval.get("status", "uncertain")).lower(),
        self_eval_issues=[str(x) for x in self_eval.get("issues", []) if str(x).strip()],
        revised_answer=str(self_eval.get("revised_answer", "")).strip() or None,
        tool_plan=tools,
        raw_text=raw,
    )


def score_task(task: BenchmarkTask, output: ModelOutput, consistency: float) -> TaskMetrics:
    correctness = _score_correctness(task, output.final_answer)
    context_accuracy = _score_context(task, output)
    logical_reasoning = _score_logical_reasoning(output, correctness)
    calibration = max(0.0, 1.0 - abs(output.confidence - correctness))
    self_evaluation = _score_self_eval(output, correctness)
    iterative_refinement = _score_refinement(output, correctness)
    tool_alignment = _score_tool_alignment(task, output)
    consistency = max(0.0, min(1.0, consistency))

    overall = (
        0.34 * correctness
        + 0.14 * context_accuracy
        + 0.12 * logical_reasoning
        + 0.10 * calibration
        + 0.10 * self_evaluation
        + 0.08 * iterative_refinement
        + 0.07 * tool_alignment
        + 0.05 * consistency
    )
    return TaskMetrics(
        correctness=round(correctness, 6),
        context_accuracy=round(context_accuracy, 6),
        logical_reasoning=round(logical_reasoning, 6),
        calibration=round(calibration, 6),
        self_evaluation=round(self_evaluation, 6),
        iterative_refinement=round(iterative_refinement, 6),
        tool_alignment=round(tool_alignment, 6),
        consistency=round(consistency, 6),
        overall=round(overall, 6),
    )


def aggregate_metrics(metrics: Iterable[TaskMetrics]) -> Dict[str, float]:
    items = list(metrics)
    if not items:
        return {
            "correctness": 0.0,
            "context_accuracy": 0.0,
            "logical_reasoning": 0.0,
            "calibration": 0.0,
            "self_evaluation": 0.0,
            "iterative_refinement": 0.0,
            "tool_alignment": 0.0,
            "consistency": 0.0,
            "overall": 0.0,
        }
    return {
        "correctness": round(mean(x.correctness for x in items), 6),
        "context_accuracy": round(mean(x.context_accuracy for x in items), 6),
        "logical_reasoning": round(mean(x.logical_reasoning for x in items), 6),
        "calibration": round(mean(x.calibration for x in items), 6),
        "self_evaluation": round(mean(x.self_evaluation for x in items), 6),
        "iterative_refinement": round(mean(x.iterative_refinement for x in items), 6),
        "tool_alignment": round(mean(x.tool_alignment for x in items), 6),
        "consistency": round(mean(x.consistency for x in items), 6),
        "overall": round(mean(x.overall for x in items), 6),
    }


def metrics_to_dict(metrics: TaskMetrics) -> Dict[str, float]:
    return asdict(metrics)


def _extract_json(raw: str) -> Dict[str, object] | None:
    if not raw:
        return None
    candidates = [raw.strip()]

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)

    brace_match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0))

    for text in candidates:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except Exception:
            continue
    return None


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[`*_\"']", "", s)
    return s


def _score_correctness(task: BenchmarkTask, answer: str) -> float:
    normalized = _normalize(answer)
    targets = [_normalize(task.expected_answer)] + [_normalize(x) for x in task.acceptable_answers]
    return 1.0 if normalized in targets else 0.0


def _score_context(task: BenchmarkTask, output: ModelOutput) -> float:
    if not task.required_context:
        return 1.0
    context_text = _normalize(" ".join(output.context_summary))
    hits = 0
    for token in task.required_context:
        if _normalize(token) in context_text:
            hits += 1
    return hits / max(1, len(task.required_context))


def _score_logical_reasoning(output: ModelOutput, correctness: float) -> float:
    checks_count = len(output.reasoning_checks)
    checks_score = min(1.0, checks_count / 3.0)
    return 0.65 * correctness + 0.35 * checks_score


def _score_self_eval(output: ModelOutput, correctness: float) -> float:
    status = output.self_eval_status
    if correctness >= 0.999 and status == "pass":
        return 1.0
    if correctness < 0.5 and status in {"fail", "uncertain"}:
        return 1.0
    if status in {"fail", "uncertain"} and output.self_eval_issues:
        return 0.7
    return 0.2


def _score_refinement(output: ModelOutput, correctness: float) -> float:
    if output.revised_answer and _normalize(output.revised_answer) == _normalize(output.final_answer):
        return 1.0 if correctness >= 0.999 else 0.7
    if output.revised_answer and _normalize(output.revised_answer) != _normalize(output.final_answer):
        return 0.5
    return 0.4 if correctness >= 0.999 else 0.2


def _score_tool_alignment(task: BenchmarkTask, output: ModelOutput) -> float:
    if not task.allowed_tools:
        return 1.0 if not output.tool_plan else max(0.0, 1.0 - 0.15 * len(output.tool_plan))

    used = output.tool_plan
    if not used:
        return 0.7

    in_allow = sum(1 for tool in used if tool in task.allowed_tools)
    allow_score = in_allow / max(1, len(used))
    over_budget = max(0, len(used) - task.max_tool_calls)
    budget_penalty = min(0.5, over_budget * 0.1)
    return max(0.0, allow_score - budget_penalty)

