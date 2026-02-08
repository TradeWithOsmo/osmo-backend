from backend.agent.Evaluators.reasoning_tuning.client import MockReasoningClient
from backend.agent.Evaluators.reasoning_tuning.dataset_loader import load_benchmark
from backend.agent.Evaluators.reasoning_tuning.schema import TuningConfig
from backend.agent.Evaluators.reasoning_tuning.tuner import ReasoningTuningLoop


def test_dataset_has_more_than_ten_references_and_tasks():
    tasks, references = load_benchmark()
    assert len(tasks) >= 10
    assert len(references) > 10


def test_tuning_loop_reports_all_effort_levels_and_improves():
    config = TuningConfig(
        model_id="groq/openai/gpt-oss-120b",
        max_rounds=4,
        target_success=0.99,
        max_tasks=8,
        output_dir="d:/WorkingSpace/backend/agent/Evaluators/reasoning_tuning/reports_test",
    )
    loop = ReasoningTuningLoop(client=MockReasoningClient(), config=config)
    result = loop.run()

    assert result["rounds"], "Expected at least one evaluation round."
    first = result["rounds"][0]["global_aggregate"]["overall"]
    last = result["rounds"][-1]["global_aggregate"]["overall"]
    assert last >= first

    effort_names = [item["effort"] for item in result["rounds"][-1]["effort_reports"]]
    assert effort_names == ["low", "medium", "high", "extra_high"]

