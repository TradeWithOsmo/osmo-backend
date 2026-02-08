from __future__ import annotations

import json
import os
import random
import time
from abc import ABC, abstractmethod
from typing import Dict, List

import httpx

from .schema import EffortLevel


class BaseReasoningClient(ABC):
    @abstractmethod
    def generate(
        self,
        model_id: str,
        effort: EffortLevel,
        messages: List[Dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> str:
        raise NotImplementedError

    def list_models(self) -> List[str]:
        return []


class GroqReasoningClient(BaseReasoningClient):
    def __init__(
        self,
        groq_api_key: str | None = None,
        max_retries: int = 6,
        base_backoff_sec: float = 2.0,
        max_backoff_sec: float = 45.0,
        min_interval_sec: float = 0.0,
    ):
        self.groq_api_key = groq_api_key
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.min_interval_sec = max(0.0, float(min_interval_sec))
        self._last_call_at: float = 0.0

    def generate(
        self,
        model_id: str,
        effort: EffortLevel,
        messages: List[Dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> str:
        try:
            from agent.Core.llm_factory import LLMFactory
        except Exception:
            from backend.agent.Core.llm_factory import LLMFactory

        if self.groq_api_key:
            os.environ["GROQ_API_KEY"] = self.groq_api_key.strip()

        _ = top_p
        effort_arg = "high" if effort == "extra_high" else effort
        llm = LLMFactory.get_llm(
            model_id=model_id,
            temperature=temperature,
            reasoning_effort=effort_arg,
        )

        now = time.monotonic()
        elapsed = now - self._last_call_at
        if self.min_interval_sec > 0 and elapsed < self.min_interval_sec:
            time.sleep(self.min_interval_sec - elapsed)

        last_error: Exception | None = None
        for attempt in range(0, self.max_retries + 1):
            try:
                response = llm.invoke(messages)
                self._last_call_at = time.monotonic()
                return (response.content or "").strip()
            except Exception as exc:
                last_error = exc
                if not _is_retryable_error(exc):
                    raise
                if attempt >= self.max_retries:
                    break
                # Exponential backoff + jitter for 429 / transient failures.
                delay = min(self.max_backoff_sec, self.base_backoff_sec * (2 ** attempt))
                delay += random.uniform(0.0, 0.75)
                time.sleep(delay)

        raise RuntimeError(f"Groq request failed after retries: {last_error}")

    def list_models(self) -> List[str]:
        key = self.groq_api_key
        if not key:
            return []
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                response.raise_for_status()
                payload = response.json()
            return sorted(str(item.get("id")) for item in payload.get("data", []) if item.get("id"))
        except Exception:
            return []


class MockReasoningClient(BaseReasoningClient):
    """
    Offline client for deterministic tests.
    Improves behavior when more policy flags are present.
    """

    def generate(
        self,
        model_id: str,
        effort: EffortLevel,
        messages: List[Dict[str, str]],
        temperature: float,
        top_p: float,
    ) -> str:
        _ = (model_id, temperature, top_p)
        system = messages[0]["content"]
        user = messages[1]["content"]
        task_id = "unknown"
        for line in user.splitlines():
            if line.startswith("Task ID:"):
                task_id = line.split(":", 1)[1].strip()
                break

        has_context_audit = "CONTEXT_AUDIT" in system
        has_calibration = "CALIBRATION_CHECK" in system
        has_refinement = "ITERATIVE_REFINEMENT" in system
        has_self_eval = "SELF_EVALUATION" in system
        has_tool_min = "TOOL_MINIMALITY" in system

        expected = _mock_expected_answer(task_id)
        is_good = (
            (effort in ("high", "extra_high"))
            or (has_context_audit and has_calibration and has_self_eval)
            or (has_refinement and has_tool_min)
        )

        if not is_good:
            payload = {
                "final_answer": "uncertain",
                "confidence": 0.92,
                "context_summary": ["Partial context only."],
                "reasoning_checks": ["Basic pass."],
                "self_evaluation": {"status": "pass", "issues": [], "revised_answer": ""},
                "tool_plan": [{"tool": "search_news", "needed": True, "purpose": "generic"}],
            }
            return json.dumps(payload)

        payload = {
            "final_answer": expected,
            "confidence": 0.84 if has_calibration else 0.65,
            "context_summary": [
                "Entities and constraints extracted from references.",
                "Task objective is explicit.",
            ],
            "reasoning_checks": [
                "Cross-checked constraints against candidate answer.",
                "Validated edge conditions.",
            ],
            "self_evaluation": {
                "status": "pass",
                "issues": [] if has_self_eval else ["self-check not fully complete"],
                "revised_answer": expected if has_refinement else "",
            },
            "tool_plan": [] if has_tool_min else [{"tool": "get_price", "needed": False, "purpose": "optional"}],
        }
        return json.dumps(payload)


def _mock_expected_answer(task_id: str) -> str:
    table = {
        "T001": "42",
        "T002": "buy",
        "T003": "ETH-USD",
        "T004": "no_trade",
        "T005": "medium",
        "T006": "3",
        "T007": "false",
        "T008": "stop_limit",
        "T009": "30m",
        "T010": "5",
        "T011": "no_trade",
        "T012": "2",
    }
    return table.get(task_id, "unknown")


def _is_retryable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    retry_tokens = (
        "rate limit",
        "429",
        "api connection",
        "connection error",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "server overload",
    )
    return any(token in msg for token in retry_tokens)
