from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .schema import BenchmarkTask


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = BASE_DIR / "datasets" / "tasks.json"
DEFAULT_REFERENCES_PATH = BASE_DIR / "datasets" / "references.json"


def load_benchmark(
    dataset_path: str | None = None,
    references_path: str | None = None,
) -> Tuple[List[BenchmarkTask], Dict[str, str]]:
    ds_path = Path(dataset_path) if dataset_path else DEFAULT_DATASET_PATH
    ref_path = Path(references_path) if references_path else DEFAULT_REFERENCES_PATH

    tasks_data = json.loads(ds_path.read_text(encoding="utf-8"))
    refs_data = json.loads(ref_path.read_text(encoding="utf-8"))

    tasks: List[BenchmarkTask] = []
    for item in tasks_data:
        tasks.append(
            BenchmarkTask(
                id=item["id"],
                prompt=item["prompt"],
                expected_answer=str(item["expected_answer"]),
                acceptable_answers=[str(x) for x in item.get("acceptable_answers", [])],
                category=item.get("category", "general"),
                difficulty=item.get("difficulty", "medium"),
                required_context=[str(x) for x in item.get("required_context", [])],
                reference_ids=[str(x) for x in item.get("reference_ids", [])],
                allowed_tools=[str(x) for x in item.get("allowed_tools", [])],
                max_tool_calls=int(item.get("max_tool_calls", 2)),
            )
        )

    references: Dict[str, str] = {str(k): str(v) for k, v in refs_data.items()}
    return tasks, references

