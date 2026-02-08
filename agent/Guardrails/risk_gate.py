from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class RiskGate:
    """Lightweight execution guardrails for agentic trading flows."""

    _EXECUTION_PATTERN = re.compile(
        r"\b("
        r"buy|sell|long|short|open|close|execute|place order|entry|tp|sl|stop loss|take profit"
        r")\b",
        re.IGNORECASE,
    )

    _MAX_LEVERAGE_PATTERN = re.compile(r"\b(\d{2,3})\s*x\b", re.IGNORECASE)

    @classmethod
    def wants_execution(cls, text: str) -> bool:
        return bool(cls._EXECUTION_PATTERN.search(text or ""))

    @classmethod
    def extract_requested_leverage(cls, text: str) -> Optional[int]:
        match = cls._MAX_LEVERAGE_PATTERN.search(text or "")
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    @classmethod
    def evaluate(cls, text: str, tool_states: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
        tool_states = tool_states or {}
        warnings: List[str] = []
        blocks: List[str] = []

        wants_exec = cls.wants_execution(text)
        execution_enabled = bool(tool_states.get("execution"))

        if wants_exec and not execution_enabled:
            blocks.append("Execution intent detected, but Auto Execution is disabled.")

        requested_lev = cls.extract_requested_leverage(text)
        if requested_lev and requested_lev > 50:
            warnings.append(
                "High leverage request detected (>50x). Confirm margin and liquidation risk before any execution."
            )

        if wants_exec:
            warnings.append(
                "Execution-related request detected. Treat LLM output as a signal draft until validated by risk checks."
            )

        max_leverage = int(tool_states.get("max_leverage", 50) or 50)
        max_notional = float(tool_states.get("max_notional_usd", 5000) or 5000)

        requested_amount = tool_states.get("requested_amount_usd")
        if requested_amount is not None:
            try:
                amount = float(requested_amount)
                if amount > max_notional:
                    blocks.append(
                        f"Requested notional ${amount:.2f} exceeds max_notional_usd=${max_notional:.2f}."
                    )
            except Exception:
                pass

        requested_lev_state = tool_states.get("requested_leverage")
        if requested_lev_state is not None:
            try:
                lev = int(requested_lev_state)
                if lev > max_leverage:
                    blocks.append(
                        f"Requested leverage {lev}x exceeds max_leverage={max_leverage}x."
                    )
            except Exception:
                pass

        return {"warnings": warnings, "blocks": blocks}
