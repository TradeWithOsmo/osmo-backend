from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlanContext:
    symbol: Optional[str] = None
    timeframe: str = "1H"
    requested_execution: bool = False
    requested_news: bool = False
    requested_sentiment: bool = False
    requested_whales: bool = False
    side: Optional[str] = None
    order_type: str = "market"
    amount_usd: Optional[float] = None
    leverage: int = 1
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ToolResult:
    name: str
    args: Dict[str, Any]
    ok: bool
    data: Any = None
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass
class AgentPlan:
    intent: str
    context: PlanContext
    tool_calls: List[ToolCall] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
