from __future__ import annotations

import argparse
import json
import os

from .client import GroqReasoningClient, MockReasoningClient
from .schema import EffortLevel, TuningConfig
from .tuner import ReasoningTuningLoop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Iterative reasoning effort tuning loop for Groq-compatible models."
    )
    parser.add_argument("--model-id", default="groq/openai/gpt-oss-120b")
    parser.add_argument("--wallet-address", default="0x31B91aDB9EC04a3BE391D4899E4ba0572DA32Bfc")
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--target-success", type=float, default=1.0)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        default="d:/WorkingSpace/backend/agent/Evaluators/reasoning_tuning/reports",
    )
    parser.add_argument("--max-references-per-task", type=int, default=12)
    parser.add_argument("--dataset-path", default=None)
    parser.add_argument("--references-path", default=None)
    parser.add_argument("--offline-mock", action="store_true")
    parser.add_argument("--rate-limit-safe", action="store_true")
    parser.add_argument("--samples-per-effort", type=int, default=None)
    parser.add_argument("--request-interval-sec", type=float, default=None)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--max-backoff-sec", type=float, default=None)
    parser.add_argument(
        "--efforts",
        default="low,medium,high,extra_high",
        help="Comma-separated effort levels to evaluate (e.g. 'high' or 'medium,high').",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = TuningConfig(
        model_id=args.model_id,
        wallet_address=args.wallet_address,
        max_rounds=args.max_rounds,
        target_success=args.target_success,
        max_tasks=args.max_tasks,
        output_dir=args.output_dir,
        max_references_per_task=args.max_references_per_task,
    )

    if args.offline_mock:
        client = MockReasoningClient()
    else:
        max_retries = args.max_retries if args.max_retries is not None else (2 if args.rate_limit_safe else 6)
        max_backoff_sec = args.max_backoff_sec if args.max_backoff_sec is not None else (20.0 if args.rate_limit_safe else 45.0)
        request_interval_sec = (
            args.request_interval_sec
            if args.request_interval_sec is not None
            else (1.0 if args.rate_limit_safe else 0.0)
        )
        client = GroqReasoningClient(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            max_retries=max_retries,
            max_backoff_sec=max_backoff_sec,
            min_interval_sec=request_interval_sec,
        )

    raw_efforts = [item.strip().lower() for item in str(args.efforts or "").split(",") if item.strip()]
    efforts: list[EffortLevel] = [item for item in raw_efforts if item in {"low", "medium", "high", "extra_high"}]  # type: ignore[list-item]

    loop = ReasoningTuningLoop(client=client, config=config, efforts=efforts)
    if args.rate_limit_safe:
        for profile in loop.effort_profiles.values():
            profile.self_consistency_samples = 1
            profile.temperature = min(profile.temperature, 0.12)
    if args.samples_per_effort is not None:
        sample_count = max(1, min(int(args.samples_per_effort), 6))
        for profile in loop.effort_profiles.values():
            profile.self_consistency_samples = sample_count
    result = loop.run()

    summary = {
        "model_id": result["model_id"],
        "wallet_address": result["wallet_address"],
        "best_overall": result["best_overall"],
        "target_success": result["target_success"],
        "target_met": result["target_met"],
        "rounds": len(result["rounds"]),
        "output_dir": config.output_dir,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
