from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


EffortLevel = Literal["low", "medium", "high", "extra_high"]


@dataclass
class BenchmarkTask:
    id: str
    prompt: str
    expected_answer: str
    acceptable_answers: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "medium"
    required_context: List[str] = field(default_factory=list)
    reference_ids: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    max_tool_calls: int = 2


@dataclass
class ModelOutput:
    final_answer: str
    confidence: float
    context_summary: List[str] = field(default_factory=list)
    reasoning_checks: List[str] = field(default_factory=list)
    self_eval_status: str = "uncertain"
    self_eval_issues: List[str] = field(default_factory=list)
    revised_answer: Optional[str] = None
    tool_plan: List[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class TaskMetrics:
    correctness: float = 0.0
    context_accuracy: float = 0.0
    logical_reasoning: float = 0.0
    calibration: float = 0.0
    self_evaluation: float = 0.0
    iterative_refinement: float = 0.0
    tool_alignment: float = 0.0
    consistency: float = 0.0
    overall: float = 0.0


@dataclass
class TaskResult:
    task_id: str
    effort: EffortLevel
    metrics: TaskMetrics
    selected_output: ModelOutput
    outputs: List[ModelOutput] = field(default_factory=list)


@dataclass
class EffortProfile:
    effort: EffortLevel
    temperature: float
    self_consistency_samples: int
    tool_budget: int
    prompt_flags: List[str] = field(default_factory=list)
    top_p: float = 1.0


@dataclass
class EffortReport:
    effort: EffortLevel
    profile: EffortProfile
    task_results: List[TaskResult]
    aggregate: Dict[str, float]


@dataclass
class EvaluationSummary:
    round_index: int
    model_id: str
    wallet_address: str
    effort_reports: List[EffortReport]
    global_aggregate: Dict[str, float]
    suggestions: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class TuningConfig:
    model_id: str = "groq/openai/gpt-oss-120b"
    wallet_address: str = "0x31B91aDB9EC04a3BE391D4899E4ba0572DA32Bfc"
    max_rounds: int = 6
    target_success: float = 1.0
    max_tasks: Optional[int] = None
    output_dir: str = "backend/agent/Evaluators/reasoning_tuning/reports"
    strict_json: bool = True
    max_references_per_task: int = 12

