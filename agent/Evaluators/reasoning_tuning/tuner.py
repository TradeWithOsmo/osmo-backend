from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from .client import BaseReasoningClient
from .dataset_loader import load_benchmark
from .prompts import build_messages
from .schema import (
    BenchmarkTask,
    EffortLevel,
    EffortProfile,
    EffortReport,
    EvaluationSummary,
    ModelOutput,
    TaskResult,
    TuningConfig,
)
from .scorer import aggregate_metrics, parse_model_output, score_task


DEFAULT_EFFORT_PROFILES: Dict[EffortLevel, EffortProfile] = {
    "low": EffortProfile(
        effort="low",
        temperature=0.0,
        self_consistency_samples=1,
        tool_budget=1,
        prompt_flags=["LOGICAL_REASONING", "TOOL_MINIMALITY"],
    ),
    "medium": EffortProfile(
        effort="medium",
        temperature=0.1,
        self_consistency_samples=2,
        tool_budget=2,
        prompt_flags=["LOGICAL_REASONING", "CONTEXT_AUDIT", "SELF_EVALUATION", "TOOL_MINIMALITY"],
    ),
    "high": EffortProfile(
        effort="high",
        temperature=0.15,
        self_consistency_samples=3,
        tool_budget=2,
        prompt_flags=[
            "LOGICAL_REASONING",
            "CONTEXT_AUDIT",
            "SELF_EVALUATION",
            "CALIBRATION_CHECK",
            "ERROR_ANALYSIS",
            "TOOL_MINIMALITY",
        ],
    ),
    "extra_high": EffortProfile(
        effort="extra_high",
        temperature=0.2,
        self_consistency_samples=4,
        tool_budget=2,
        prompt_flags=[
            "LOGICAL_REASONING",
            "CONTEXT_AUDIT",
            "SELF_EVALUATION",
            "CALIBRATION_CHECK",
            "ERROR_ANALYSIS",
            "ITERATIVE_REFINEMENT",
            "TOOL_MINIMALITY",
        ],
    ),
}


class ReasoningTuningLoop:
    def __init__(
        self,
        client: BaseReasoningClient,
        config: TuningConfig,
        tasks: List[BenchmarkTask] | None = None,
        references: Dict[str, str] | None = None,
        effort_profiles: Dict[EffortLevel, EffortProfile] | None = None,
        efforts: List[EffortLevel] | None = None,
    ):
        self.client = client
        self.config = config
        self.tasks, self.references = (tasks, references) if tasks is not None and references is not None else load_benchmark()
        self.effort_profiles = effort_profiles or {
            key: EffortProfile(**asdict(value)) for key, value in DEFAULT_EFFORT_PROFILES.items()
        }
        default_efforts: List[EffortLevel] = ["low", "medium", "high", "extra_high"]
        if efforts:
            normalized = [e for e in efforts if e in self.effort_profiles]
            self.efforts = normalized if normalized else default_efforts
        else:
            self.efforts = default_efforts
        if config.max_tasks is not None:
            self.tasks = self.tasks[: max(0, config.max_tasks)]

    def run(self) -> Dict[str, object]:
        reports: List[EvaluationSummary] = []
        best_overall = 0.0
        no_gain_rounds = 0

        for round_index in range(1, self.config.max_rounds + 1):
            summary = self._evaluate_round(round_index)
            reports.append(summary)
            current_overall = summary.global_aggregate["overall"]

            if current_overall > best_overall + 1e-9:
                best_overall = current_overall
                no_gain_rounds = 0
            else:
                no_gain_rounds += 1

            self._write_round(summary)

            if self._is_target_met(summary):
                break

            if no_gain_rounds >= 2:
                self._tighten_determinism()

            self._improve_profiles(summary)

        final = {
            "model_id": self.config.model_id,
            "wallet_address": self.config.wallet_address,
            "rounds": [self._summary_to_dict(item) for item in reports],
            "best_overall": best_overall,
            "target_success": self.config.target_success,
            "target_met": bool(reports and self._is_target_met(reports[-1])),
        }
        self._write_final(final)
        return final

    def _evaluate_round(self, round_index: int) -> EvaluationSummary:
        effort_reports: List[EffortReport] = []
        suggestions: Dict[str, List[str]] = {}

        for effort in self.efforts:
            profile = self.effort_profiles[effort]
            task_results = [self._evaluate_task(task, profile) for task in self.tasks]
            aggregate = aggregate_metrics([result.metrics for result in task_results])
            effort_reports.append(
                EffortReport(
                    effort=effort,
                    profile=EffortProfile(**asdict(profile)),
                    task_results=task_results,
                    aggregate=aggregate,
                )
            )
            suggestions[effort] = self._error_analysis(aggregate)

        global_aggregate = aggregate_metrics(
            [task_result.metrics for report in effort_reports for task_result in report.task_results]
        )
        return EvaluationSummary(
            round_index=round_index,
            model_id=self.config.model_id,
            wallet_address=self.config.wallet_address,
            effort_reports=effort_reports,
            global_aggregate=global_aggregate,
            suggestions=suggestions,
        )

    def _evaluate_task(self, task: BenchmarkTask, profile: EffortProfile) -> TaskResult:
        samples: List[ModelOutput] = []
        for _ in range(max(1, profile.self_consistency_samples)):
            messages = build_messages(
                task=task,
                references=self.references,
                profile=profile,
                max_references=self.config.max_references_per_task,
            )
            raw = self.client.generate(
                model_id=self.config.model_id,
                effort=profile.effort,
                messages=messages,
                temperature=profile.temperature,
                top_p=profile.top_p,
            )
            samples.append(parse_model_output(raw))

        selected, consistency = self._select_output(samples)
        metrics = score_task(task, selected, consistency=consistency)
        return TaskResult(
            task_id=task.id,
            effort=profile.effort,
            metrics=metrics,
            selected_output=selected,
            outputs=samples,
        )

    def _select_output(self, samples: List[ModelOutput]) -> Tuple[ModelOutput, float]:
        counts = Counter(sample.final_answer.strip().lower() for sample in samples if sample.final_answer.strip())
        if not counts:
            return samples[0], 0.0

        winner, winner_count = counts.most_common(1)[0]
        candidates = [item for item in samples if item.final_answer.strip().lower() == winner]
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        selected = candidates[0] if candidates else samples[0]
        consistency = winner_count / max(1, len(samples))
        return selected, consistency

    def _error_analysis(self, aggregate: Dict[str, float]) -> List[str]:
        notes: List[str] = []
        if aggregate["context_accuracy"] < 0.98:
            notes.append("Increase context extraction rigor.")
        if aggregate["logical_reasoning"] < 0.98:
            notes.append("Add stronger logical verification checks.")
        if aggregate["calibration"] < 0.98:
            notes.append("Improve confidence calibration and uncertainty handling.")
        if aggregate["self_evaluation"] < 0.98:
            notes.append("Strengthen self-evaluation and explicit issue reporting.")
        if aggregate["iterative_refinement"] < 0.98:
            notes.append("Add explicit iterative refinement before final answer.")
        if aggregate["tool_alignment"] < 0.98:
            notes.append("Reduce unnecessary tools and enforce tighter tool budget.")
        if not notes:
            notes.append("Metrics stable. Keep policy and focus on consistency.")
        return notes

    def _improve_profiles(self, summary: EvaluationSummary) -> None:
        for report in summary.effort_reports:
            profile = self.effort_profiles[report.effort]
            agg = report.aggregate

            self._ensure_flag(profile, "LOGICAL_REASONING")
            if agg["context_accuracy"] < 0.99:
                self._ensure_flag(profile, "CONTEXT_AUDIT")
            if agg["calibration"] < 0.99:
                self._ensure_flag(profile, "CALIBRATION_CHECK")
            if agg["self_evaluation"] < 0.99:
                self._ensure_flag(profile, "SELF_EVALUATION")
            if agg["iterative_refinement"] < 0.99 and report.effort in ("high", "extra_high"):
                self._ensure_flag(profile, "ITERATIVE_REFINEMENT")
            if agg["logical_reasoning"] < 0.99:
                self._ensure_flag(profile, "ERROR_ANALYSIS")
            if agg["tool_alignment"] < 0.99:
                self._ensure_flag(profile, "TOOL_MINIMALITY")
                profile.tool_budget = max(1, profile.tool_budget - 1)

            if agg["overall"] < self.config.target_success:
                profile.self_consistency_samples = min(profile.self_consistency_samples + 1, 6)
                profile.temperature = max(0.0, profile.temperature - 0.02)

    def _tighten_determinism(self) -> None:
        for profile in self.effort_profiles.values():
            profile.temperature = max(0.0, profile.temperature - 0.03)

    def _ensure_flag(self, profile: EffortProfile, flag: str) -> None:
        if flag not in profile.prompt_flags:
            profile.prompt_flags.append(flag)

    def _is_target_met(self, summary: EvaluationSummary) -> bool:
        target = self.config.target_success
        if summary.global_aggregate["overall"] < target:
            return False
        for report in summary.effort_reports:
            if report.aggregate["overall"] < target:
                return False
        return True

    def _summary_to_dict(self, summary: EvaluationSummary) -> Dict[str, object]:
        return {
            "round_index": summary.round_index,
            "model_id": summary.model_id,
            "wallet_address": summary.wallet_address,
            "global_aggregate": summary.global_aggregate,
            "suggestions": summary.suggestions,
            "effort_reports": [
                {
                    "effort": report.effort,
                    "profile": asdict(report.profile),
                    "aggregate": report.aggregate,
                    "task_results": [
                        {
                            "task_id": item.task_id,
                            "effort": item.effort,
                            "metrics": asdict(item.metrics),
                            "selected_output": asdict(item.selected_output),
                        }
                        for item in report.task_results
                    ],
                }
                for report in summary.effort_reports
            ],
        }

    def _write_round(self, summary: EvaluationSummary) -> None:
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self._summary_to_dict(summary)
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        path = output_dir / f"round_{summary.round_index:02d}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_final(self, payload: Dict[str, object]) -> None:
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        path = output_dir / "final_report.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
