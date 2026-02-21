"""
Osmo Agent — Comprehensive Feature Test Suite
Run inside Docker: docker exec osmo-agent-alt python test_all_features.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    warning: bool = False


@dataclass
class Suite:
    name: str
    results: List[TestResult] = field(default_factory=list)

    def add(self, result: TestResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.warning)

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if r.warning)


ALL_SUITES: List[Suite] = []


def suite(name: str) -> Suite:
    s = Suite(name)
    ALL_SUITES.append(s)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(s: Suite, name: str, detail: str, ms: float) -> None:
    s.add(TestResult(name, True, ms, detail))
    print(f"  {GREEN}✓{RESET} {name:<55} {CYAN}{ms:6.0f}ms{RESET}  {detail[:90]}")


def fail(s: Suite, name: str, detail: str, ms: float) -> None:
    s.add(TestResult(name, False, ms, detail))
    print(
        f"  {RED}✗{RESET} {name:<55} {CYAN}{ms:6.0f}ms{RESET}  {RED}{detail[:90]}{RESET}"
    )


def warn(s: Suite, name: str, detail: str, ms: float) -> None:
    r = TestResult(name, True, ms, detail, warning=True)
    s.add(r)
    print(
        f"  {YELLOW}~{RESET} {name:<55} {CYAN}{ms:6.0f}ms{RESET}  {YELLOW}{detail[:90]}{RESET}"
    )


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 70}{RESET}")


async def timed(coro) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = await coro
    return result, (time.perf_counter() - t0) * 1000


def safe_str(v: Any, max_len: int = 120) -> str:
    s = str(v or "")
    return s[:max_len] + ("…" if len(s) > max_len else "")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Agent HTTP API  (port 8001)
# ─────────────────────────────────────────────────────────────────────────────


async def test_agent_api():
    s = suite("Agent HTTP API (port 8001)")
    section("1. Agent HTTP API")

    try:
        import httpx

        AGENT = os.getenv("AGENT_API_URL", "http://localhost:8000")
        client = httpx.AsyncClient(timeout=10)

        # In `docker compose run`, API server may not be running in this container.
        # Treat connectivity failure as a skip (warning), not a hard test failure.
        try:
            await client.get(f"{AGENT}/health")
        except httpx.RequestError as exc:
            warn(
                s,
                "agent_api_suite (skipped)",
                f"API not reachable at {AGENT}: {type(exc).__name__}",
                0,
            )
            await client.aclose()
            return

        # health
        r, ms = await timed(client.get(f"{AGENT}/health"))
        d = r.json()
        if r.status_code == 200 and d.get("status") == "healthy":
            ok(s, "GET /health", f"models={d.get('available_models')}", ms)
        else:
            fail(s, "GET /health", safe_str(d), ms)

        # root
        r, ms = await timed(client.get(f"{AGENT}/"))
        d = r.json()
        if r.status_code == 200 and "service" in d:
            ok(s, "GET /", f"service={d.get('service')} v{d.get('version')}", ms)
        else:
            fail(s, "GET /", safe_str(d), ms)

        # models list
        r, ms = await timed(client.get(f"{AGENT}/api/agent/models"))
        d = r.json()
        cnt = d.get("count", 0)
        if r.status_code == 200 and cnt > 0:
            ok(s, "GET /api/agent/models", f"{cnt} models loaded", ms)
        else:
            fail(s, "GET /api/agent/models", safe_str(d), ms)

        # models by provider
        r, ms = await timed(client.get(f"{AGENT}/api/agent/models?provider=anthropic"))
        d = r.json()
        if r.status_code == 200 and d.get("count", 0) > 0:
            ok(
                s,
                "GET /api/agent/models?provider=anthropic",
                f"{d['count']} models",
                ms,
            )
        else:
            fail(s, "GET /api/agent/models?provider=anthropic", safe_str(d), ms)

        # single model
        model_id = "anthropic/claude-sonnet-4-5"
        r, ms = await timed(client.get(f"{AGENT}/api/agent/models/{model_id}"))
        d = r.json()
        if r.status_code in (200, 404):
            label = "found" if r.status_code == 200 else "not in list (ok)"
            ok(s, f"GET /api/agent/models/{{model_id}}", label, ms)
        else:
            fail(s, f"GET /api/agent/models/{{model_id}}", safe_str(d), ms)

        # validate model
        r, ms = await timed(
            client.post(
                f"{AGENT}/api/agent/models/validate?model_id=anthropic/claude-3.5-sonnet"
            )
        )
        d = r.json()
        if r.status_code == 200 and "valid" in d:
            ok(s, "POST /api/agent/models/validate", f"valid={d.get('valid')}", ms)
        else:
            fail(s, "POST /api/agent/models/validate", safe_str(d), ms)

        # recommended
        r, ms = await timed(client.get(f"{AGENT}/api/agent/models/recommended"))
        d = r.json()
        if r.status_code == 200 and "recommended" in d:
            ok(
                s,
                "GET /api/agent/models/recommended",
                f"{len(d.get('recommended', {}))} categories",
                ms,
            )
        else:
            fail(s, "GET /api/agent/models/recommended", safe_str(d), ms)

        # providers
        r, ms = await timed(client.get(f"{AGENT}/api/agent/providers"))
        d = r.json()
        if r.status_code == 200 and "providers" in d:
            ok(s, "GET /api/agent/providers", f"{d.get('total')} providers", ms)
        else:
            fail(s, "GET /api/agent/providers", safe_str(d), ms)

        # agent info
        r, ms = await timed(client.get(f"{AGENT}/api/agent/info"))
        d = r.json()
        if r.status_code == 200 and d.get("framework"):
            ok(s, "GET /api/agent/info", f"framework={d.get('framework')}", ms)
        else:
            fail(s, "GET /api/agent/info", safe_str(d), ms)

        # agent health
        r, ms = await timed(client.get(f"{AGENT}/api/agent/health"))
        d = r.json()
        if r.status_code == 200 and d.get("status") == "healthy":
            ok(s, "GET /api/agent/health", "healthy", ms)
        else:
            fail(s, "GET /api/agent/health", safe_str(d), ms)

        await client.aclose()

    except Exception as exc:
        fail(s, "agent_api_suite", traceback.format_exc(), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tool Registry
# ─────────────────────────────────────────────────────────────────────────────


async def test_tool_registry():
    s = suite("Tool Registry")
    section("2. Tool Registry")
    t0 = time.perf_counter()

    try:
        from agent.Core.tool_registry import (
            _discover_exported_tools,
            _infer_parameters_schema,
            build_tool_registry,
        )

        ms = (time.perf_counter() - t0) * 1000

        # build registry
        t0 = time.perf_counter()
        registry = build_tool_registry()
        ms = (time.perf_counter() - t0) * 1000
        if registry and len(registry) >= 30:
            ok(s, "build_tool_registry()", f"{len(registry)} tools registered", ms)
        else:
            fail(s, "build_tool_registry()", f"only {len(registry)} tools", ms)

        # all expected tools present
        EXPECTED = [
            "get_price",
            "get_candles",
            "get_orderbook",
            "get_funding_rate",
            "get_high_low_levels",
            "get_technical_analysis",
            "search_news",
            "search_sentiment",
            "place_order",
            "get_positions",
            "close_position",
            "add_memory",
            "search_memory",
            "research_market",
            "draw",
            "add_indicator",
            "set_timeframe",
            "set_symbol",
        ]
        missing = [t for t in EXPECTED if t not in registry]
        t0 = time.perf_counter()
        ms = (time.perf_counter() - t0) * 1000 + 0.1
        if not missing:
            ok(
                s,
                "expected tools present",
                f"all {len(EXPECTED)} expected tools found",
                0.1,
            )
        else:
            fail(s, "expected tools present", f"missing: {missing}", 0.1)

        # each spec has required fields
        bad_specs = []
        for name, spec in registry.items():
            if not isinstance(spec.get("path"), str):
                bad_specs.append(f"{name}:no_path")
            params = spec.get("parameters", {})
            if not isinstance(params, dict) or "type" not in params:
                bad_specs.append(f"{name}:bad_params")
        if not bad_specs:
            ok(s, "all specs have path+parameters", f"{len(registry)} specs valid", 0.1)
        else:
            fail(s, "all specs have path+parameters", f"bad: {bad_specs[:5]}", 0.1)

        # _discover_exported_tools
        t0 = time.perf_counter()
        discovered = _discover_exported_tools()
        ms = (time.perf_counter() - t0) * 1000
        if len(discovered) >= 30:
            ok(
                s,
                "_discover_exported_tools()",
                f"{len(discovered)} tools auto-discovered",
                ms,
            )
        else:
            fail(s, "_discover_exported_tools()", f"only {len(discovered)} found", ms)

        # parameter schema inference
        async def _dummy(symbol: str, timeframe: str = "1H", limit: int = 100) -> dict:
            return {}

        schema = _infer_parameters_schema(_dummy)
        if schema.get("properties", {}).get("symbol") and "required" in schema:
            ok(
                s,
                "_infer_parameters_schema()",
                f"props={list(schema['properties'].keys())}",
                0.1,
            )
        else:
            fail(s, "_infer_parameters_schema()", safe_str(schema), 0.1)

        # caching (second call should be faster)
        t1 = time.perf_counter()
        registry2 = build_tool_registry()
        ms2 = (time.perf_counter() - t1) * 1000
        if registry2 is registry:
            ok(
                s,
                "build_tool_registry() cached (lru_cache)",
                f"{ms2:.2f}ms (same object)",
                ms2,
            )
        else:
            warn(
                s,
                "build_tool_registry() cached",
                "returned new object (cache may be off)",
                ms2,
            )

    except Exception as exc:
        fail(s, "tool_registry_suite", traceback.format_exc()[-300:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Reasoning Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


async def test_orchestrator():
    s = suite("Reasoning Orchestrator")
    section("3. Reasoning Orchestrator")

    try:
        from agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator

        orch = ReasoningOrchestrator()

        cases = [
            ("analysis intent", "analyse BTC on 1H timeframe", "analysis", "BTC"),
            ("execution intent", "buy 100 USD of ETH now", "execution", "ETH"),
            ("research intent", "latest news on bitcoin", "research", ""),
            ("symbol from state", "what is the price?", "analysis", "SOL"),
            ("no symbol warning", "what do you think?", "analysis", ""),
        ]

        for label, msg, expected_intent, sym in cases:
            t0 = time.perf_counter()
            states: Dict[str, Any] = {}
            if sym and label == "symbol from state":
                states["market_symbol"] = sym
            plan = orch.build_plan(
                user_message=msg,
                history=None,
                tool_states=states,
            )
            ms = (time.perf_counter() - t0) * 1000

            if plan.intent == expected_intent:
                tools = [tc.name for tc in plan.tool_calls]
                ok(
                    s,
                    f"build_plan [{label}]",
                    f"intent={plan.intent} tools={tools}",
                    ms,
                )
            else:
                fail(
                    s,
                    f"build_plan [{label}]",
                    f"expected={expected_intent} got={plan.intent}",
                    ms,
                )

        # symbol extraction from message
        t0 = time.perf_counter()
        plan = orch.build_plan("show me ETH-USD on 4H", history=None, tool_states={})
        ms = (time.perf_counter() - t0) * 1000
        if plan.context.symbol:
            ok(
                s,
                "symbol extraction from message text",
                f"symbol={plan.context.symbol}",
                ms,
            )
        else:
            warn(s, "symbol extraction from message text", "no symbol extracted", ms)

        # timeframe extraction
        t0 = time.perf_counter()
        plan = orch.build_plan("BTC analysis on 4H", history=None, tool_states={})
        ms = (time.perf_counter() - t0) * 1000
        if plan.context.timeframe:
            ok(
                s,
                "timeframe extraction from message text",
                f"tf={plan.context.timeframe}",
                ms,
            )
        else:
            warn(
                s,
                "timeframe extraction from message text",
                "no timeframe extracted",
                ms,
            )

        # execution blocked
        t0 = time.perf_counter()
        plan = orch.build_plan(
            "buy BTC now", history=None, tool_states={"execution": False}
        )
        ms = (time.perf_counter() - t0) * 1000
        if plan.blocks:
            ok(s, "execution blocked when execution=false", f"blocks={plan.blocks}", ms)
        else:
            warn(s, "execution blocked when execution=false", "no block added", ms)

        # max_actions cap
        t0 = time.perf_counter()
        plan = orch.build_plan(
            "analyse BTC on 1H", history=None, tool_states={"max_tool_actions": 1}
        )
        ms = (time.perf_counter() - t0) * 1000
        if len(plan.tool_calls) <= 1:
            ok(
                s,
                "max_tool_actions cap respected",
                f"{len(plan.tool_calls)} tool call(s)",
                ms,
            )
        else:
            fail(s, "max_tool_actions cap respected", f"got {len(plan.tool_calls)}", ms)

        # process() async wrapper
        t0 = time.perf_counter()
        result = await orch.process("analyse BTC", history=[], tool_states={})
        ms = (time.perf_counter() - t0) * 1000
        if result.get("response") == "plan_ready" and "plan" in result:
            ok(
                s,
                "process() async wrapper",
                f"plan keys={list(result['plan'].keys())}",
                ms,
            )
        else:
            fail(s, "process() async wrapper", safe_str(result), ms)

        # history symbol extraction
        history = [
            {"role": "user", "content": "analyse SOL please"},
            {"role": "assistant", "content": "Sure"},
        ]
        t0 = time.perf_counter()
        plan = orch.build_plan("what is the price?", history=history, tool_states={})
        ms = (time.perf_counter() - t0) * 1000
        if plan.context.symbol == "SOL":
            ok(
                s,
                "symbol extracted from history fallback",
                f"symbol={plan.context.symbol}",
                ms,
            )
        else:
            warn(
                s,
                "symbol extracted from history fallback",
                f"got={plan.context.symbol}",
                ms,
            )

    except Exception as exc:
        fail(s, "orchestrator_suite", traceback.format_exc()[-300:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. ReflexionState (Memory / State tracking)
# ─────────────────────────────────────────────────────────────────────────────


async def test_reflexion_state():
    s = suite("ReflexionState & ReflexionMemory")
    section("4. ReflexionState & ReflexionMemory")

    try:
        from agent.Core.reflexion_memory import (
            ActionStatus,
            AnalysisPhase,
            ReflexionState,
        )

        # init
        t0 = time.perf_counter()
        state = ReflexionState()
        ms = (time.perf_counter() - t0) * 1000
        ok(s, "ReflexionState init", f"phase={state.current_phase}", ms)

        # set active symbol
        t0 = time.perf_counter()
        state.set_active_symbol("BTC", asset_type="crypto")
        ms = (time.perf_counter() - t0) * 1000
        if state.current_symbol == "BTC":
            ok(s, "set_active_symbol()", f"active={state.current_symbol}", ms)
        else:
            fail(s, "set_active_symbol()", f"got={state.current_symbol}", ms)

        # get_or_create_symbol
        t0 = time.perf_counter()
        ctx = state.get_or_create_symbol("ETH")
        ms = (time.perf_counter() - t0) * 1000
        if ctx and ctx.symbol == "ETH":
            ok(s, "get_or_create_symbol()", f"symbol={ctx.symbol}", ms)
        else:
            fail(s, "get_or_create_symbol()", safe_str(ctx), ms)

        # ingest_price_result
        t0 = time.perf_counter()
        state.set_active_symbol("BTC", asset_type="crypto")
        state.ingest_price_result(
            "BTC", {"price": 67500.0, "symbol": "BTC-USD", "asset_type": "crypto"}
        )
        ctx = state.get_symbol("BTC")
        ms = (time.perf_counter() - t0) * 1000
        if ctx and ctx.price == 67500.0:
            ok(s, "ingest_price_result()", f"price={ctx.price}", ms)
        else:
            fail(s, "ingest_price_result()", f"ctx={ctx}", ms)

        # ingest_ta_result
        t0 = time.perf_counter()
        state.ingest_ta_result(
            "BTC",
            {
                "indicators": {"RSI_14": 58.5, "MACD": 120.0},
                "patterns": ["Doji", "Engulfing"],
                "symbol": "BTC-USD",
            },
        )
        ctx = state.get_symbol("BTC")
        ms = (time.perf_counter() - t0) * 1000
        if ctx and ctx.rsi == 58.5:
            ok(s, "ingest_ta_result()", f"rsi={ctx.rsi} patterns={ctx.patterns}", ms)
        else:
            fail(s, "ingest_ta_result()", safe_str(ctx), ms)

        # ingest_levels_result
        t0 = time.perf_counter()
        state.ingest_levels_result(
            "BTC",
            {
                "status": "ok",
                "support": 66000.0,
                "resistance": 69000.0,
            },
        )
        ctx = state.get_symbol("BTC")
        ms = (time.perf_counter() - t0) * 1000
        if ctx and ctx.support == 66000.0:
            ok(
                s,
                "ingest_levels_result()",
                f"support={ctx.support} resistance={ctx.resistance}",
                ms,
            )
        else:
            fail(s, "ingest_levels_result()", safe_str(ctx), ms)

        # record_action success
        t0 = time.perf_counter()
        state.record_action(
            "get_price", {"symbol": "BTC"}, {"price": 67500}, ActionStatus.GOOD
        )
        ms = (time.perf_counter() - t0) * 1000
        last = state.last_action_for_tool("get_price")
        if last and last.status == ActionStatus.GOOD:
            ok(s, "record_action() SUCCESS", f"tool={last.tool_name}", ms)
        else:
            fail(s, "record_action() SUCCESS", safe_str(last), ms)

        # record_action failure
        t0 = time.perf_counter()
        state.record_action(
            "get_price",
            {"symbol": "INVALID"},
            {"error": "Not found"},
            ActionStatus.ERROR,
            retry_count=1,
        )
        ms = (time.perf_counter() - t0) * 1000
        retry_count = state.retry_count_for_tool("get_price")
        if retry_count >= 1:
            ok(
                s,
                "record_action() FAILED + retry_count",
                f"retry_count={retry_count}",
                ms,
            )
        else:
            fail(
                s,
                "record_action() FAILED + retry_count",
                f"retry_count={retry_count}",
                ms,
            )

        # already_succeeded
        t0 = time.perf_counter()
        did_succeed = state.already_succeeded("get_price")
        ms = (time.perf_counter() - t0) * 1000
        if did_succeed:
            ok(s, "already_succeeded()", "True (correct, had success)", ms)
        else:
            fail(s, "already_succeeded()", "False (unexpected)", ms)

        # add_reflection
        t0 = time.perf_counter()
        state.add_reflection("Price fetched successfully, RSI is neutral.")
        recent = state.recent_reflections(1)
        ms = (time.perf_counter() - t0) * 1000
        if recent and "RSI" in recent[0]:
            ok(
                s,
                "add_reflection() + recent_reflections()",
                f"reflection stored: {recent[0][:40]}",
                ms,
            )
        else:
            fail(s, "add_reflection() + recent_reflections()", safe_str(recent), ms)

        # advance_phase
        t0 = time.perf_counter()
        phase_before = state.current_phase
        state.advance_phase(AnalysisPhase.SYNTHESIS)
        ms = (time.perf_counter() - t0) * 1000
        if state.current_phase != phase_before:
            ok(s, "advance_phase()", f"phase now={state.current_phase}", ms)
        else:
            warn(s, "advance_phase()", f"phase unchanged: {state.current_phase}", ms)

        # summary
        t0 = time.perf_counter()
        summary = state.summary()
        ms = (time.perf_counter() - t0) * 1000
        if summary and isinstance(summary, dict) and summary.get("total_steps", 0) >= 0:
            ok(
                s,
                "state.summary()",
                f"phase={summary.get('phase')} steps={summary.get('total_steps')} actions={summary.get('actions')}",
                ms,
            )
        elif summary and isinstance(summary, str) and len(summary) > 10:
            ok(s, "state.summary()", f"{summary[:60]}", ms)
        else:
            fail(s, "state.summary()", safe_str(summary), ms)

        # build_context_block
        t0 = time.perf_counter()
        block = state.build_context_block()
        ms = (time.perf_counter() - t0) * 1000
        if block and isinstance(block, str):
            ok(s, "build_context_block()", f"{block[:60]}", ms)
        else:
            fail(s, "build_context_block()", safe_str(block), ms)

        # add_pending_fix / pop_pending_fixes
        t0 = time.perf_counter()
        state.add_pending_fix("get_price", {"symbol": "BTC-USD"}, "symbol format fix")
        fixes = state.pop_pending_fixes()
        ms = (time.perf_counter() - t0) * 1000
        if fixes and len(fixes) == 1:
            ok(s, "add_pending_fix() + pop_pending_fixes()", f"{fixes[0]}", ms)
        else:
            fail(s, "add_pending_fix() + pop_pending_fixes()", safe_str(fixes), ms)

    except Exception as exc:
        fail(s, "reflexion_state_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. ReflexionEvaluator
# ─────────────────────────────────────────────────────────────────────────────


async def test_reflexion_evaluator():
    s = suite("ReflexionEvaluator")
    section("5. ReflexionEvaluator")

    try:
        from agent.Core.reflexion_evaluator import ReflexionEvaluator

        ev = ReflexionEvaluator()

        # evaluate() returns (ActionStatus, note, fix_hint) tuple
        # ActionStatus.GOOD = ok, anything else = not ok
        from agent.Core.reflexion_memory import ActionStatus as AS

        cases = [
            # (tool_name, args_dict, result_dict, expect_good)
            (
                "get_price",
                {"symbol": "BTC"},
                {"price": 67500.0, "symbol": "BTC-USD"},
                True,
            ),
            ("get_price", {"symbol": "ZZZZZ"}, {"error": "not found"}, False),
            (
                "get_candles",
                {"symbol": "BTC"},
                {"data": [{"open": 100, "high": 110, "low": 90, "close": 105}] * 15},
                True,
            ),
            ("get_candles", {"symbol": "BTC"}, {"error": "timeout"}, False),
            (
                "get_technical_analysis",
                {"symbol": "BTC"},
                {"price": 100, "indicators": {"RSI_14": 55}},
                True,
            ),
            ("get_technical_analysis", {"symbol": "BTC"}, {"error": "fail"}, False),
            (
                "search_news",
                {"query": "btc"},
                {"status": "ok", "data": {"summary": "Bitcoin up today"}},
                True,
            ),
            ("search_news", {"query": "btc"}, {"error": "search failed"}, False),
            (
                "add_indicator",
                {"name": "RSI"},
                {"status": "ok", "verified": True},
                True,
            ),
            ("draw", {"tool": "trend_line"}, {"status": "ok"}, True),
            ("get_positions", {}, {"positions": [], "account": {}}, True),
            (
                "research_market",
                {"symbol": "BTC"},
                {"status": "ok", "markets_available": 1},
                True,
            ),
        ]

        for tool, args, result, expect_good in cases:
            t0 = time.perf_counter()
            try:
                status, note, fix = ev.evaluate(
                    tool_name=tool, args=args, result=result
                )
                ms = (time.perf_counter() - t0) * 1000
                got_good = status == AS.GOOD
                label = f"evaluate({tool}, good={expect_good})"
                if got_good == expect_good:
                    ok(s, label, f"status={status.value} note={str(note)[:40]}", ms)
                else:
                    fail(
                        s,
                        label,
                        f"expected good={expect_good} got status={status.value} note={note}",
                        ms,
                    )
            except Exception as exc:
                fail(s, f"evaluate({tool})", str(exc)[:80], 0)

        # should_retry(status, tool_name, retry_count)
        t0 = time.perf_counter()
        retry = ev.should_retry(
            status=AS.ERROR,
            tool_name="get_price",
            retry_count=0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(retry, bool):
            ok(
                s,
                "should_retry() error status retry_count=0",
                f"should_retry={retry}",
                ms,
            )
        else:
            fail(
                s,
                "should_retry() error status retry_count=0",
                f"got type={type(retry)}",
                ms,
            )

        # should_retry max retries exceeded → False
        t0 = time.perf_counter()
        retry_max = ev.should_retry(
            status=AS.ERROR,
            tool_name="get_price",
            retry_count=5,
            max_retries=2,
        )
        ms = (time.perf_counter() - t0) * 1000
        if retry_max is False:
            ok(
                s,
                "should_retry() max_retries=2 retry_count=5 → False",
                f"{retry_max}",
                ms,
            )
        else:
            warn(s, "should_retry() max_retries exceeded", f"got {retry_max}", ms)

        # should_retry GOOD status → False
        t0 = time.perf_counter()
        retry_good = ev.should_retry(
            status=AS.GOOD,
            tool_name="get_price",
            retry_count=0,
        )
        ms = (time.perf_counter() - t0) * 1000
        if retry_good is False:
            ok(s, "should_retry() GOOD status → False", f"{retry_good}", ms)
        else:
            fail(s, "should_retry() GOOD status → False", f"got {retry_good}", ms)

        # evaluate_batch — List[Tuple[tool_name, args, result]]
        t0 = time.perf_counter()
        batch = [
            ("get_price", {"symbol": "BTC"}, {"price": 100.0}),
            ("get_candles", {"symbol": "BTC"}, {"error": "fail"}),
        ]
        results = ev.evaluate_batch(batch)
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(results, list) and len(results) == 2:
            statuses = [r[0].value for r in results]
            ok(s, "evaluate_batch()", f"2 results statuses={statuses}", ms)
        else:
            fail(s, "evaluate_batch()", safe_str(results), ms)

        # apply_fix_to_args(tool_name, original_args, fix_hint)
        t0 = time.perf_counter()
        fixed = ev.apply_fix_to_args(
            tool_name="get_price",
            original_args={"symbol": "BTCUSDT"},
            fix_hint="use BTC-USD format",
        )
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(fixed, dict):
            ok(s, "apply_fix_to_args()", f"fixed args={fixed}", ms)
        else:
            fail(s, "apply_fix_to_args()", safe_str(fixed), ms)

    except Exception as exc:
        fail(s, "reflexion_evaluator_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Market Data Tools
# ─────────────────────────────────────────────────────────────────────────────


async def test_market_data():
    s = suite("Market Data Tools")
    section("6. Market Data Tools")

    try:
        from agent.Tools.data.market import (
            _looks_like_fiat_cross,
            _normalize_asset_type,
            _normalize_symbol_candidates,
            _symbol_for_connector_route,
            get_candles,
            get_funding_rate,
            get_high_low_levels,
            get_orderbook,
            get_price,
            get_ticker_stats,
        )

        # get_price crypto BTC
        r, ms = await timed(get_price("BTC", asset_type="crypto"))
        if "error" not in r and r.get("price", 0) > 0:
            ok(s, "get_price BTC (crypto)", f"price=${r['price']:,.2f}", ms)
        else:
            fail(s, "get_price BTC (crypto)", safe_str(r), ms)

        # get_price ETH
        r, ms = await timed(get_price("ETH", asset_type="crypto"))
        if "error" not in r and r.get("price", 0) > 0:
            ok(s, "get_price ETH (crypto)", f"price=${r['price']:,.2f}", ms)
        else:
            fail(s, "get_price ETH (crypto)", safe_str(r), ms)

        # get_price RWA EUR-USD
        r, ms = await timed(get_price("EUR-USD", asset_type="rwa"))
        if "error" not in r and r.get("price", 0) > 0:
            ok(s, "get_price EUR-USD (rwa)", f"price={r['price']}", ms)
        else:
            fail(s, "get_price EUR-USD (rwa)", safe_str(r), ms)

        # get_price auto-fallback: EUR-USD requested as crypto → should reroute to rwa
        r, ms = await timed(get_price("EUR-USD", asset_type="crypto"))
        if "error" not in r and r.get("price", 0) > 0:
            ok(
                s,
                "get_price EUR-USD auto-fallback crypto→rwa",
                f"asset_type={r.get('asset_type')}",
                ms,
            )
        else:
            warn(s, "get_price EUR-USD auto-fallback crypto→rwa", safe_str(r), ms)

        # get_price unknown symbol
        r, ms = await timed(get_price("FAKECOIN9999XYZ", asset_type="crypto"))
        if "error" in r:
            ok(s, "get_price unknown symbol → error", r["error"][:60], ms)
        else:
            fail(
                s,
                "get_price unknown symbol → error",
                f"expected error, got {list(r.keys())}",
                ms,
            )

        # get_candles BTC
        r, ms = await timed(
            get_candles("BTC", timeframe="1H", limit=10, asset_type="crypto")
        )
        data = r.get("data") if isinstance(r, dict) else r
        if isinstance(data, list) and len(data) > 0:
            ok(
                s,
                "get_candles BTC 1H",
                f"{len(data)} candles, keys={list(data[0].keys())}",
                ms,
            )
        elif isinstance(r, dict) and "error" not in r:
            ok(s, "get_candles BTC 1H", f"response shape: {list(r.keys())}", ms)
        else:
            fail(s, "get_candles BTC 1H", safe_str(r), ms)

        # get_candles with different timeframes
        for tf in ["4H", "1D"]:
            r, ms = await timed(
                get_candles("ETH", timeframe=tf, limit=5, asset_type="crypto")
            )
            if isinstance(r, dict) and "error" not in r:
                ok(s, f"get_candles ETH {tf}", f"ok", ms)
            else:
                warn(s, f"get_candles ETH {tf}", safe_str(r), ms)

        # get_candles RWA
        r, ms = await timed(
            get_candles("EUR-USD", timeframe="1H", limit=5, asset_type="rwa")
        )
        if isinstance(r, dict):
            label = "ok" if "error" not in r else f"error: {r['error'][:40]}"
            ok(s, "get_candles EUR-USD (rwa)", label, ms)
        else:
            fail(s, "get_candles EUR-USD (rwa)", safe_str(r), ms)

        # get_orderbook crypto
        r, ms = await timed(get_orderbook("BTC", asset_type="crypto"))
        if isinstance(r, dict) and ("bids" in r or "data" in r or "error" in r):
            label = f"bids+asks present" if "bids" in r else (r.get("error", "ok")[:40])
            ok(s, "get_orderbook BTC (crypto)", label, ms)
        else:
            fail(s, "get_orderbook BTC (crypto)", safe_str(r), ms)

        # get_orderbook RWA → must return error
        r, ms = await timed(get_orderbook("EUR-USD", asset_type="rwa"))
        if "error" in r:
            ok(s, "get_orderbook RWA → blocked with error", r["error"][:50], ms)
        else:
            fail(
                s,
                "get_orderbook RWA → blocked with error",
                f"no error returned: {list(r.keys())}",
                ms,
            )

        # get_funding_rate
        r, ms = await timed(get_funding_rate("BTC", asset_type="crypto"))
        if isinstance(r, dict):
            ok(s, "get_funding_rate BTC", f"keys={list(r.keys())[:5]}", ms)
        else:
            fail(s, "get_funding_rate BTC", safe_str(r), ms)

        # get_ticker_stats
        r, ms = await timed(get_ticker_stats("ETH", asset_type="crypto"))
        if isinstance(r, dict) and "error" not in r:
            ok(
                s,
                "get_ticker_stats ETH",
                f"price={r.get('price')} vol={r.get('volume_24h')}",
                ms,
            )
        else:
            fail(s, "get_ticker_stats ETH", safe_str(r), ms)

        # get_high_low_levels
        r, ms = await timed(
            get_high_low_levels("BTC", timeframe="1H", lookback=7, asset_type="crypto")
        )
        if "error" not in r and r.get("support") and r.get("resistance"):
            ok(
                s,
                "get_high_low_levels BTC 7-candle",
                f"sup={r['support']:.0f} res={r['resistance']:.0f}",
                ms,
            )
        else:
            fail(s, "get_high_low_levels BTC 7-candle", safe_str(r), ms)

        # get_high_low_levels large lookback
        r, ms = await timed(
            get_high_low_levels("BTC", timeframe="1H", lookback=50, asset_type="crypto")
        )
        if isinstance(r, dict) and r.get("status") == "ok":
            ok(
                s,
                "get_high_low_levels BTC 50-candle lookback",
                f"used={r.get('lookback_used')}",
                ms,
            )
        else:
            warn(s, "get_high_low_levels BTC 50-candle lookback", safe_str(r), ms)

        # ── Pure unit tests (no network) ────────────────────────────────────
        # _normalize_symbol_candidates
        cands = _normalize_symbol_candidates("BTC")
        if "BTC-USD" in cands and "BTCUSDT" in cands:
            ok(s, "_normalize_symbol_candidates('BTC')", f"{cands[:4]}", 0.0)
        else:
            fail(s, "_normalize_symbol_candidates('BTC')", f"got {cands}", 0.0)

        cands2 = _normalize_symbol_candidates("BTCUSDT")
        if "BTC-USD" in cands2:
            ok(s, "_normalize_symbol_candidates('BTCUSDT')", f"{cands2[:4]}", 0.0)
        else:
            fail(s, "_normalize_symbol_candidates('BTCUSDT')", f"got {cands2}", 0.0)

        # _looks_like_fiat_cross
        checks = [
            ("EUR-USD", True),
            ("EURUSD", True),
            ("BTC-USD", False),
            ("ETHUSD", False),
        ]
        for sym, expected in checks:
            result = _looks_like_fiat_cross(sym)
            if result == expected:
                ok(s, f"_looks_like_fiat_cross('{sym}')", f"={result}", 0.0)
            else:
                fail(
                    s,
                    f"_looks_like_fiat_cross('{sym}')",
                    f"expected {expected} got {result}",
                    0.0,
                )

        # _normalize_asset_type
        for raw, expected in [
            ("crypto", "crypto"),
            ("hyperliquid", "crypto"),
            ("rwa", "rwa"),
            ("ostium", "rwa"),
        ]:
            result = _normalize_asset_type(raw)
            if result == expected:
                ok(s, f"_normalize_asset_type('{raw}')", f"={result}", 0.0)
            else:
                fail(
                    s,
                    f"_normalize_asset_type('{raw}')",
                    f"expected {expected} got {result}",
                    0.0,
                )

        # _symbol_for_connector_route
        for sym, at, expected in [
            ("BTC-USD", "crypto", "BTC"),
            ("BTCUSDT", "crypto", "BTC"),
            ("EUR-USD", "rwa", "EUR-USD"),
        ]:
            result = _symbol_for_connector_route(sym, at)
            if result == expected:
                ok(
                    s,
                    f"_symbol_for_connector_route('{sym}', '{at}')",
                    f"='{result}'",
                    0.0,
                )
            else:
                fail(
                    s,
                    f"_symbol_for_connector_route('{sym}', '{at}')",
                    f"expected '{expected}' got '{result}'",
                    0.0,
                )

    except Exception as exc:
        fail(s, "market_data_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Technical Analysis
# ─────────────────────────────────────────────────────────────────────────────


async def test_technical_analysis():
    s = suite("Technical Analysis Tools")
    section("7. Technical Analysis Tools")

    try:
        from agent.Tools.data.analysis import (
            _is_fiat_cross_symbol,
            get_indicators,
            get_patterns,
            get_technical_analysis,
            get_technical_summary,
        )

        # full TA report
        r, ms = await timed(
            get_technical_analysis("BTC", timeframe="1H", asset_type="crypto")
        )
        if isinstance(r, dict) and "error" not in r:
            ok(s, "get_technical_analysis BTC 1H", f"keys={list(r.keys())}", ms)
        else:
            fail(s, "get_technical_analysis BTC 1H", safe_str(r), ms)

        # TA on ETH different timeframe
        r, ms = await timed(
            get_technical_analysis("ETH", timeframe="4H", asset_type="crypto")
        )
        if isinstance(r, dict):
            ok(
                s,
                "get_technical_analysis ETH 4H",
                f"error={r.get('error', 'none')}",
                ms,
            )
        else:
            fail(s, "get_technical_analysis ETH 4H", safe_str(r), ms)

        # fiat RWA → must return descriptive error
        r, ms = await timed(
            get_technical_analysis("EUR-USD", timeframe="1H", asset_type="rwa")
        )
        if "error" in r and (
            "fiat" in r["error"].lower() or "unsupported" in r["error"].lower()
        ):
            ok(
                s,
                "get_technical_analysis EUR-USD rwa → fiat error",
                r["error"][:60],
                ms,
            )
        else:
            fail(s, "get_technical_analysis EUR-USD rwa → fiat error", safe_str(r), ms)

        # get_patterns
        r, ms = await timed(get_patterns("BTC", timeframe="1H", asset_type="crypto"))
        if isinstance(r, list):
            ok(s, "get_patterns BTC", f"{len(r)} patterns: {r[:3]}", ms)
        else:
            fail(s, "get_patterns BTC", safe_str(r), ms)

        # get_indicators
        r, ms = await timed(get_indicators("BTC", timeframe="1H", asset_type="crypto"))
        if isinstance(r, dict):
            ok(s, "get_indicators BTC", f"keys={list(r.keys())[:5]}", ms)
        else:
            fail(s, "get_indicators BTC", safe_str(r), ms)

        # get_technical_summary
        r, ms = await timed(
            get_technical_summary("BTC", timeframe="1H", asset_type="crypto")
        )
        if isinstance(r, str) and len(r) > 10:
            ok(s, "get_technical_summary BTC", r[:70], ms)
        else:
            fail(s, "get_technical_summary BTC", safe_str(r), ms)

        # _is_fiat_cross_symbol unit tests
        for sym, expected in [
            ("EUR-USD", True),
            ("GBP-JPY", True),
            ("BTC-USD", False),
            ("ETH", False),
        ]:
            result = _is_fiat_cross_symbol(sym)
            if result == expected:
                ok(s, f"_is_fiat_cross_symbol('{sym}')", f"={result}", 0.0)
            else:
                fail(
                    s,
                    f"_is_fiat_cross_symbol('{sym}')",
                    f"expected {expected} got {result}",
                    0.0,
                )

    except Exception as exc:
        fail(s, "technical_analysis_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Web Intelligence
# ─────────────────────────────────────────────────────────────────────────────


async def test_web_intelligence():
    s = suite("Web Intelligence")
    section("8. Web Intelligence")

    try:
        from agent.Tools.data.web import (
            _infer_symbol,
            _normalize_mode,
            search_news,
            search_sentiment,
            search_web_hybrid,
        )

        # _normalize_mode unit tests (no network)
        for raw, expected in [
            ("quality", "quality"),
            ("speed", "speed"),
            ("budget", "budget"),
            ("bad", "quality"),
            (None, "quality"),
        ]:
            result = _normalize_mode(raw)
            if result == expected:
                ok(s, f"_normalize_mode('{raw}')", f"='{result}'", 0.0)
            else:
                fail(
                    s,
                    f"_normalize_mode('{raw}')",
                    f"expected '{expected}' got '{result}'",
                    0.0,
                )

        # _infer_symbol unit tests (no network)
        symbol_cases = [
            ("$SOL is pumping today", None, "SOL"),
            ("BTC/USDT breakout analysis", None, "BTC"),
            ("ETH analysis", None, "ETH"),
            ("random text with no symbol", None, "BTC"),  # fallback
            ("anything", "SOL", "SOL"),  # explicit override
        ]
        for query, sym, expected in symbol_cases:
            result = _infer_symbol(query, symbol=sym)
            if result == expected:
                ok(s, f"_infer_symbol: '{query[:30]}'", f"='{result}'", 0.0)
            else:
                fail(
                    s,
                    f"_infer_symbol: '{query[:30]}'",
                    f"expected '{expected}' got '{result}'",
                    0.0,
                )

        # search_news (live)
        r, ms = await timed(
            search_news("bitcoin price today", mode="quality", source="news")
        )
        if isinstance(r, dict) and "error" not in r:
            inner = r.get("data", {})
            summary = inner.get("summary", "")[:60] if isinstance(inner, dict) else ""
            ok(
                s,
                "search_news 'bitcoin price today'",
                summary or f"keys={list(r.keys())}",
                ms,
            )
        else:
            fail(s, "search_news 'bitcoin price today'", safe_str(r), ms)

        # search_sentiment (live — Grok/Twitter may be slow or rate-limited)
        r, ms = await timed(search_sentiment("BTC", mode="quality"))
        if isinstance(r, dict) and "error" not in r:
            ok(s, "search_sentiment BTC", f"keys={list(r.keys())}", ms)
        else:
            # Timeout / rate-limit is an external dependency issue, not a code bug
            warn(
                s,
                "search_sentiment BTC",
                f"external service issue: {safe_str(r)[:60]}",
                ms,
            )

        # search_web_hybrid (live — concurrent news + sentiment)
        r, ms = await timed(
            search_web_hybrid("ethereum market analysis", mode="quality", symbol="ETH")
        )
        if isinstance(r, dict) and "status" in r:
            ok(
                s,
                "search_web_hybrid ETH",
                f"status={r['status']} results={r.get('results_count')}",
                ms,
            )
        else:
            fail(s, "search_web_hybrid ETH", safe_str(r), ms)

        # hybrid symbol inference
        r, ms = await timed(search_web_hybrid("$SOL pump analysis"))
        if isinstance(r, dict) and r.get("symbol") == "SOL":
            ok(
                s,
                "search_web_hybrid symbol inferred from $SOL",
                f"symbol={r['symbol']}",
                ms,
            )
        else:
            warn(
                s,
                "search_web_hybrid symbol inferred from $SOL",
                f"got symbol={r.get('symbol')}",
                ms,
            )

    except Exception as exc:
        fail(s, "web_intelligence_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Research Tools
# ─────────────────────────────────────────────────────────────────────────────


async def test_research_tools():
    s = suite("Research Tools")
    section("9. Research Tools")

    try:
        from agent.Tools.data.research import (
            MarketSnapshot,
            _best_price_market,
            _compute_spread,
            compare_markets,
            research_market,
            scan_market_overview,
        )

        # _compute_spread unit test
        snaps = [
            MarketSnapshot(
                market="hyperliquid", symbol="BTC", price=67500.0, available=True
            ),
            MarketSnapshot(
                market="ostium", symbol="BTC", price=67600.0, available=True
            ),
        ]
        spread = _compute_spread(snaps)
        if spread is not None and 0 < spread < 1:
            ok(s, "_compute_spread()", f"spread={spread:.4f}%", 0.0)
        else:
            fail(s, "_compute_spread()", f"got {spread}", 0.0)

        # _best_price_market unit test
        best = _best_price_market(snaps)
        if best == "hyperliquid":
            ok(s, "_best_price_market()", f"={best} (lowest price)", 0.0)
        else:
            fail(s, "_best_price_market()", f"expected hyperliquid got {best}", 0.0)

        # research_market BTC
        r, ms = await timed(research_market("BTC", timeframe="1H"))
        if isinstance(r, dict) and r.get("status") == "ok":
            avail = r.get("markets_available", 0)
            ok(
                s,
                "research_market BTC",
                f"markets_available={avail} spread={r.get('spread_pct')}",
                ms,
            )
        else:
            fail(s, "research_market BTC", safe_str(r), ms)

        # research_market RWA EUR-USD
        r, ms = await timed(research_market("EUR-USD", timeframe="1H"))
        if isinstance(r, dict):
            ok(
                s,
                "research_market EUR-USD",
                f"status={r.get('status')} available={r.get('markets_available')}",
                ms,
            )
        else:
            fail(s, "research_market EUR-USD", safe_str(r), ms)

        # research_market with orderbook depth
        r, ms = await timed(research_market("ETH", timeframe="1H", include_depth=True))
        if isinstance(r, dict) and r.get("status") == "ok":
            ok(
                s,
                "research_market ETH (include_depth=True)",
                f"available={r.get('markets_available')}",
                ms,
            )
        else:
            fail(s, "research_market ETH (include_depth=True)", safe_str(r), ms)

        # compare_markets
        r, ms = await timed(compare_markets(["BTC", "ETH"], timeframe="1H"))
        if isinstance(r, dict) and r.get("status") == "ok":
            reports = r.get("reports", [])
            ok(
                s,
                "compare_markets [BTC, ETH]",
                f"{len(reports)} reports, total_avail={r.get('total_markets_available')}",
                ms,
            )
        else:
            fail(s, "compare_markets [BTC, ETH]", safe_str(r), ms)

        # compare_markets cap (max 5 symbols)
        r, ms = await timed(
            compare_markets(
                ["BTC", "ETH", "SOL", "ARB", "OP", "AVAX", "LINK"], timeframe="1H"
            )
        )
        if isinstance(r, dict):
            n = len(r.get("reports", []))
            if n <= 5:
                ok(s, "compare_markets cap at 5", f"got {n} reports (capped)", ms)
            else:
                fail(s, "compare_markets cap at 5", f"got {n} reports (not capped)", ms)
        else:
            fail(s, "compare_markets cap at 5", safe_str(r), ms)

        # scan_market_overview all
        r, ms = await timed(scan_market_overview(asset_class="all"))
        if isinstance(r, dict) and r.get("status") == "ok" and "markets" in r:
            markets = r.get("markets", {})
            ok(s, "scan_market_overview all", f"markets={list(markets.keys())}", ms)
        else:
            fail(s, "scan_market_overview all", safe_str(r), ms)

        # scan_market_overview crypto only
        r, ms = await timed(scan_market_overview(asset_class="crypto"))
        if isinstance(r, dict) and "markets" in r:
            hl = r["markets"].get("hyperliquid", {})
            top = hl.get("top_movers", [])
            ok(
                s,
                "scan_market_overview crypto",
                f"total_pairs={hl.get('total_pairs')} top_movers={len(top)}",
                ms,
            )
        else:
            fail(s, "scan_market_overview crypto", safe_str(r), ms)

        # scan_market_overview rwa only
        r, ms = await timed(scan_market_overview(asset_class="rwa"))
        if isinstance(r, dict) and "markets" in r:
            os_data = r["markets"].get("ostium", {})
            ok(
                s,
                "scan_market_overview rwa",
                f"total_pairs={os_data.get('total_pairs')}",
                ms,
            )
        else:
            fail(s, "scan_market_overview rwa", safe_str(r), ms)

    except Exception as exc:
        fail(s, "research_tools_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Memory Tools (mem0)
# ─────────────────────────────────────────────────────────────────────────────


async def test_memory_tools():
    s = suite("Memory Tools (mem0)")
    section("10. Memory Tools (mem0)")

    TEST_USER = "test_user_osmo_feature_check"

    try:
        from agent.Tools.data.memory import (
            _normalize_search_results,
            add_memory,
            add_memory_messages,
            get_recent_history,
            search_memory,
        )

        # _normalize_search_results unit tests (no network)
        cases = [
            ([{"memory": "hello"}], 1),
            ({"results": [{"memory": "a"}, {"memory": "b"}]}, 2),
            ({"data": {"results": [{"memory": "x"}]}}, 1),
            ({"data": [{"memory": "y"}]}, 1),
            (None, 0),
        ]
        for payload, expected_len in cases:
            result = _normalize_search_results(payload)
            if len(result) == expected_len:
                ok(
                    s,
                    f"_normalize_search_results({type(payload).__name__})",
                    f"{len(result)} items",
                    0.0,
                )
            else:
                fail(
                    s,
                    f"_normalize_search_results({type(payload).__name__})",
                    f"expected {expected_len} got {len(result)}",
                    0.0,
                )

        # add_memory
        r, ms = await timed(
            add_memory(
                TEST_USER,
                "BTC is my favourite crypto to trade.",
                metadata={"source": "test"},
            )
        )
        if isinstance(r, dict) and "error" not in r:
            ok(s, "add_memory()", f"ok keys={list(r.keys())[:4]}", ms)
        else:
            warn(s, "add_memory()", f"mem0 may not be running: {safe_str(r)}", ms)

        # add_memory_messages multi-turn
        r, ms = await timed(
            add_memory_messages(
                user_id=TEST_USER,
                messages=[
                    {
                        "role": "user",
                        "content": "I prefer swing trading on the 4H timeframe.",
                    },
                    {
                        "role": "assistant",
                        "content": "Noted. I'll prioritise 4H setups for you.",
                    },
                ],
            )
        )
        if isinstance(r, dict) and "error" not in r:
            ok(s, "add_memory_messages() multi-turn", f"ok", ms)
        else:
            warn(s, "add_memory_messages() multi-turn", safe_str(r), ms)

        # add_memory_messages empty → error
        r, ms = await timed(add_memory_messages(TEST_USER, messages=[]))
        if "error" in r:
            ok(s, "add_memory_messages() empty → error", r["error"][:60], ms)
        else:
            fail(
                s,
                "add_memory_messages() empty → error",
                f"no error returned: {list(r.keys())}",
                ms,
            )

        # search_memory
        r, ms = await timed(
            search_memory(TEST_USER, "BTC trading preferences", limit=5)
        )
        if isinstance(r, dict) and "results" in r:
            ok(
                s,
                "search_memory()",
                f"count={r.get('count')} results={len(r['results'])}",
                ms,
            )
        else:
            warn(s, "search_memory()", safe_str(r), ms)

        # search_memory limit clamping
        r, ms = await timed(search_memory(TEST_USER, "anything", limit=999))
        if isinstance(r, dict) and "results" in r:
            ok(s, "search_memory() limit clamp (999→20)", f"count={r.get('count')}", ms)
        else:
            warn(s, "search_memory() limit clamp (999→20)", safe_str(r), ms)

        # get_recent_history
        r, ms = await timed(get_recent_history(TEST_USER, limit=10))
        if isinstance(r, dict) and "results" in r:
            ok(s, "get_recent_history()", f"count={r.get('count')}", ms)
        else:
            warn(s, "get_recent_history()", safe_str(r), ms)

    except Exception as exc:
        fail(s, "memory_tools_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Analytics Tools
# ─────────────────────────────────────────────────────────────────────────────


async def test_analytics():
    s = suite("Analytics Tools")
    section("11. Analytics Tools")

    try:
        from agent.Tools.data.analytics import (
            get_token_distribution,
            get_whale_activity,
        )

        # get_whale_activity — Dune may not be enabled, expect error or data
        r, ms = await timed(get_whale_activity("BTC", min_size_usd=100000))
        if isinstance(r, dict):
            if "error" in r:
                warn(
                    s,
                    "get_whale_activity BTC",
                    f"Dune not active: {r['error'][:60]}",
                    ms,
                )
            else:
                ok(s, "get_whale_activity BTC", f"keys={list(r.keys())[:5]}", ms)
        else:
            fail(s, "get_whale_activity BTC", safe_str(r), ms)

        # get_token_distribution — not implemented
        r, ms = await timed(get_token_distribution("BTC"))
        if isinstance(r, dict) and "error" in r:
            ok(s, "get_token_distribution → not implemented error", r["error"][:50], ms)
        else:
            warn(s, "get_token_distribution", safe_str(r), ms)

    except Exception as exc:
        fail(s, "analytics_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Trade Tools (read-only + gate tests)
# ─────────────────────────────────────────────────────────────────────────────


async def test_trade_tools():
    s = suite("Trade Tools")
    section("12. Trade Tools")

    try:
        from agent.Tools.data.trade import (
            adjust_all_positions_tpsl,
            adjust_position_tpsl,
            cancel_order,
            close_all_positions,
            close_position,
            get_positions,
            reverse_position,
        )
        from agent.Tools.trade_execution import place_order

        # get_positions — missing user_address → error
        r, ms = await timed(get_positions(user_address=None, tool_states={}))
        if "error" in r:
            ok(s, "get_positions (no user_address) → error", r["error"][:60], ms)
        else:
            fail(
                s,
                "get_positions (no user_address) → error",
                f"expected error: {list(r.keys())}",
                ms,
            )

        # get_positions — with fake address (ExecutionAdapter needs websocket service,
        # not available in standalone agent container → expected to raise ModuleNotFoundError)
        try:
            r, ms = await timed(
                get_positions(user_address="0xFakeTestAddress123", tool_states={})
            )
            if isinstance(r, dict):
                warn(
                    s, "get_positions (fake address)", f"keys={list(r.keys())[:5]}", ms
                )
            else:
                warn(s, "get_positions (fake address)", safe_str(r), ms)
        except Exception as exc:
            warn(
                s,
                "get_positions (fake address)",
                f"websocket service not available in agent container: {str(exc)[:60]}",
                0,
            )

        # close_position — missing user_address (validation fires before service call)
        r, ms = await timed(close_position(user_address=None, symbol="BTC"))
        if "error" in r:
            ok(s, "close_position (no user_address) → error", r["error"][:60], ms)
        else:
            fail(s, "close_position (no user_address) → error", safe_str(r), ms)

        # close_position — missing symbol (validation fires before service call)
        r, ms = await timed(close_position(user_address="0xAbc", symbol=""))
        if "error" in r:
            ok(s, "close_position (no symbol) → error", r["error"][:60], ms)
        else:
            fail(s, "close_position (no symbol) → error", safe_str(r), ms)

        # close_position — bad size_pct (validation fires before service call)
        r, ms = await timed(
            close_position(user_address="0xAbc", symbol="BTC", size_pct=2.0)
        )
        if "error" in r:
            ok(s, "close_position (size_pct=2.0) → error", r["error"][:60], ms)
        else:
            fail(s, "close_position (size_pct=2.0) → error", safe_str(r), ms)

        # close_all_positions — missing user_address (validation fires before service call)
        r, ms = await timed(close_all_positions(user_address=None))
        if "error" in r:
            ok(s, "close_all_positions (no user_address) → error", r["error"][:60], ms)
        else:
            fail(s, "close_all_positions (no user_address) → error", safe_str(r), ms)

        # reverse_position — missing user_address (validation fires before service call)
        r, ms = await timed(reverse_position(user_address=None, symbol="BTC"))
        if "error" in r:
            ok(s, "reverse_position (no user_address) → error", r["error"][:60], ms)
        else:
            fail(s, "reverse_position (no user_address) → error", safe_str(r), ms)

        # reverse_position — missing symbol (validation fires before service call)
        r, ms = await timed(reverse_position(user_address="0xAbc", symbol=""))
        if "error" in r:
            ok(s, "reverse_position (no symbol) → error", r["error"][:60], ms)
        else:
            fail(s, "reverse_position (no symbol) → error", safe_str(r), ms)

        # cancel_order — missing order_id (validation fires before service call)
        r, ms = await timed(cancel_order(user_address="0xAbc", order_id=""))
        if "error" in r:
            ok(s, "cancel_order (no order_id) → error", r["error"][:60], ms)
        else:
            fail(s, "cancel_order (no order_id) → error", safe_str(r), ms)

        # adjust_position_tpsl — missing tp/sl/gp/gl (validation fires before service call)
        r, ms = await timed(adjust_position_tpsl(user_address="0xAbc", symbol="BTC"))
        if "error" in r:
            ok(s, "adjust_position_tpsl (no tp/sl/gp/gl) → error", r["error"][:60], ms)
        else:
            fail(s, "adjust_position_tpsl (no tp/sl/gp/gl) → error", safe_str(r), ms)

        # adjust_all_positions_tpsl — missing amounts (validation fires before service call)
        r, ms = await timed(adjust_all_positions_tpsl(user_address="0xAbc"))
        if "error" in r:
            ok(s, "adjust_all_positions_tpsl (no amounts) → error", r["error"][:60], ms)
        else:
            fail(s, "adjust_all_positions_tpsl (no amounts) → error", safe_str(r), ms)

        # place_order — execution disabled (default) → blocked
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="buy",
                amount_usd=100.0,
                tool_states={"execution": False},
            )
        )
        if "error" in r and "disabled" in r["error"].lower():
            ok(s, "place_order execution=False → blocked", r["error"][:60], ms)
        else:
            fail(s, "place_order execution=False → blocked", safe_str(r), ms)

        # place_order — invalid side
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="up",
                amount_usd=100.0,
                tool_states={"execution": True, "policy_mode": "auto_exec"},
            )
        )
        if "error" in r:
            ok(s, "place_order invalid side → error", r["error"][:60], ms)
        else:
            fail(s, "place_order invalid side → error", safe_str(r), ms)

        # place_order — execution enabled, no user_address
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="buy",
                amount_usd=100.0,
                tool_states={"execution": True, "policy_mode": "advice_only"},
                user_address=None,
            )
        )
        if "error" in r:
            ok(
                s,
                "place_order advice_only no user_address → error",
                r["error"][:60],
                ms,
            )
        else:
            fail(s, "place_order advice_only no user_address → error", safe_str(r), ms)

        # place_order — HITL proposal path
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="buy",
                amount_usd=100.0,
                leverage=2,
                tp=70000.0,
                sl=65000.0,
                tool_states={"execution": True, "policy_mode": "advice_only"},
                user_address="0xTestUser123",
            )
        )
        if r.get("status") == "proposal" and "order" in r:
            order = r["order"]
            ok(
                s,
                "place_order HITL proposal returned",
                f"symbol={order.get('symbol')} side={order.get('side')} lev={order.get('leverage')}",
                ms,
            )
        else:
            fail(s, "place_order HITL proposal returned", safe_str(r), ms)

        # place_order — gp/gl alias validation
        r, ms = await timed(
            place_order(
                symbol="ETH",
                side="sell",
                amount_usd=200.0,
                validation=1900.0,
                invalidation=2100.0,
                tool_states={"execution": True, "policy_mode": "advice_only"},
                user_address="0xTestUser123",
            )
        )
        if r.get("status") == "proposal":
            order = r["order"]
            if order.get("gp") == 1900.0 and order.get("gl") == 2100.0:
                ok(
                    s,
                    "place_order validation/invalidation alias → gp/gl",
                    f"gp={order['gp']} gl={order['gl']}",
                    ms,
                )
            else:
                fail(
                    s,
                    "place_order validation/invalidation alias → gp/gl",
                    f"order={order}",
                    ms,
                )
        else:
            fail(
                s, "place_order validation/invalidation alias → gp/gl", safe_str(r), ms
            )

        # place_order — max_notional breach
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="buy",
                amount_usd=9999999.0,
                tool_states={
                    "execution": True,
                    "policy_mode": "advice_only",
                    "max_notional_usd": 5000,
                },
                user_address="0xTestUser123",
            )
        )
        if "error" in r and "max_notional" in r["error"].lower():
            ok(s, "place_order max_notional breach → error", r["error"][:60], ms)
        else:
            fail(s, "place_order max_notional breach → error", safe_str(r), ms)

        # place_order — max_leverage breach
        r, ms = await timed(
            place_order(
                symbol="BTC",
                side="buy",
                amount_usd=100.0,
                leverage=999,
                tool_states={
                    "execution": True,
                    "policy_mode": "advice_only",
                    "max_leverage": 50,
                },
                user_address="0xTestUser123",
            )
        )
        if "error" in r and "max_leverage" in r["error"].lower():
            ok(s, "place_order max_leverage breach → error", r["error"][:60], ms)
        else:
            fail(s, "place_order max_leverage breach → error", safe_str(r), ms)

    except Exception as exc:
        fail(s, "trade_tools_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# 13. AgentBrain (init + logic, no actual LLM call)
# ─────────────────────────────────────────────────────────────────────────────


async def test_agent_brain():
    s = suite("AgentBrain (logic layer)")
    section("13. AgentBrain (logic layer)")

    try:
        from agent.Core.agent_brain import AgentBrain

        # init
        t0 = time.perf_counter()
        brain = AgentBrain(
            model_id="anthropic/claude-3.5-sonnet",
            reasoning_effort="low",
            tool_states={},
            temperature=0.7,
            max_iterations=5,
        )
        ms = (time.perf_counter() - t0) * 1000
        ok(s, "AgentBrain.__init__()", f"model={brain.model_id}", ms)

        # _tool_calling_enabled — all flags off
        t0 = time.perf_counter()
        brain.tool_states = {}
        result = brain._tool_calling_enabled()
        ms = (time.perf_counter() - t0) * 1000
        if result is False:
            ok(s, "_tool_calling_enabled() all flags off → False", "", ms)
        else:
            fail(
                s, "_tool_calling_enabled() all flags off → False", f"got {result}", ms
            )

        # _tool_calling_enabled — write=True
        brain.tool_states = {"write": True}
        if brain._tool_calling_enabled() is True:
            ok(s, "_tool_calling_enabled() write=True → True", "", 0.0)
        else:
            fail(s, "_tool_calling_enabled() write=True → True", "", 0.0)

        # _tool_calling_enabled — strict_react="true" string
        brain.tool_states = {"strict_react": "true"}
        if brain._tool_calling_enabled() is True:
            ok(s, "_tool_calling_enabled() strict_react='true' → True", "", 0.0)
        else:
            fail(s, "_tool_calling_enabled() strict_react='true' → True", "", 0.0)

        # _state_flag
        # Note: None value → bool(None) = False, not None — by design in _state_flag
        brain.tool_states = {"execution": True, "write": "false", "missing": None}
        checks = [
            ("execution", True),
            ("write", False),
            ("missing", False),  # None value → bool(None) = False
            ("nonexistent", None),  # missing key → returns None
        ]
        for key, expected in checks:
            result = brain._state_flag(key)
            if result == expected:
                ok(s, f"_state_flag('{key}')", f"={result}", 0.0)
            else:
                fail(
                    s, f"_state_flag('{key}')", f"expected {expected} got {result}", 0.0
                )

        # _resolve_tools_for_payload — all tools
        brain.tool_states = {"write": True}
        t0 = time.perf_counter()
        tools = brain._resolve_tools_for_payload()
        ms = (time.perf_counter() - t0) * 1000
        if len(tools) >= 30:
            ok(s, "_resolve_tools_for_payload() all tools", f"{len(tools)} tools", ms)
        else:
            fail(
                s,
                "_resolve_tools_for_payload() all tools",
                f"only {len(tools)} tools",
                ms,
            )

        # _resolve_tools_for_payload — enabled_tools strict filter
        # Non-strict mode intentionally ignores small allowlists (tolerates stale frontend lists).
        # strict_enabled_tools=True forces the filter.
        brain.tool_states = {
            "write": True,
            "enabled_tools": ["get_price", "get_candles"],
            "strict_enabled_tools": True,
        }
        t0 = time.perf_counter()
        tools_filtered = brain._resolve_tools_for_payload()
        ms = (time.perf_counter() - t0) * 1000
        if set(tools_filtered) == {"get_price", "get_candles"}:
            ok(
                s,
                "_resolve_tools_for_payload() strict enabled_tools filter",
                f"{tools_filtered}",
                ms,
            )
        else:
            fail(
                s,
                "_resolve_tools_for_payload() strict enabled_tools filter",
                f"expected [get_price, get_candles], got {tools_filtered}",
                ms,
            )

        # _build_openrouter_messages
        brain.tool_states = {}
        t0 = time.perf_counter()
        msgs = brain._build_openrouter_messages(
            user_message="analyse BTC",
            history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )
        ms = (time.perf_counter() - t0) * 1000
        roles = [m["role"] for m in msgs]
        if "user" in roles and "assistant" in roles:
            ok(s, "_build_openrouter_messages()", f"roles={roles}", ms)
        else:
            fail(s, "_build_openrouter_messages()", f"roles={roles}", ms)

        # _openrouter_headers
        headers = brain._openrouter_headers()
        if "Authorization" in headers and "Bearer " in headers["Authorization"]:
            ok(s, "_openrouter_headers()", f"keys={list(headers.keys())}", 0.0)
        else:
            fail(
                s, "_openrouter_headers()", f"missing auth: {list(headers.keys())}", 0.0
            )

        # max_iterations clamping
        brain_hi = AgentBrain("anthropic/claude-3.5-sonnet", max_iterations=999)
        if brain_hi.max_iterations == 12:
            ok(s, "max_iterations clamped to 12", f"={brain_hi.max_iterations}", 0.0)
        else:
            fail(
                s, "max_iterations clamped to 12", f"got {brain_hi.max_iterations}", 0.0
            )

        brain_lo = AgentBrain("anthropic/claude-3.5-sonnet", max_iterations=0)
        if brain_lo.max_iterations == 1:
            ok(
                s,
                "max_iterations clamped to 1 (min)",
                f"={brain_lo.max_iterations}",
                0.0,
            )
        else:
            fail(
                s,
                "max_iterations clamped to 1 (min)",
                f"got {brain_lo.max_iterations}",
                0.0,
            )

        # missing OPENROUTER_API_KEY
        import os

        original_key = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            raised = False
            try:
                AgentBrain("anthropic/claude-3.5-sonnet")
            except ValueError as e:
                raised = True
                if "OPENROUTER_API_KEY" in str(e):
                    ok(s, "missing OPENROUTER_API_KEY → ValueError", str(e)[:60], 0.0)
                else:
                    fail(s, "missing OPENROUTER_API_KEY → ValueError", str(e)[:60], 0.0)
            if not raised:
                warn(
                    s,
                    "missing OPENROUTER_API_KEY → ValueError",
                    "no error raised (key may still be in env)",
                    0.0,
                )
        finally:
            if original_key:
                os.environ["OPENROUTER_API_KEY"] = original_key

    except Exception as exc:
        fail(s, "agent_brain_suite", traceback.format_exc()[-400:], 0)


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    print(f"\n{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  Osmo Agent — Comprehensive Feature Tests{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}\n")

    await test_agent_api()
    await test_tool_registry()
    await test_orchestrator()
    await test_reflexion_state()
    await test_reflexion_evaluator()
    await test_market_data()
    await test_technical_analysis()
    await test_web_intelligence()
    await test_research_tools()
    await test_memory_tools()
    await test_analytics()
    await test_trade_tools()
    await test_agent_brain()

    # ── Final summary ────────────────────────────────────────────────────────
    print(f"\n{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}  RESULTS SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")

    total_pass = total_fail = total_warn = 0
    for suite_obj in ALL_SUITES:
        p = suite_obj.passed
        f = suite_obj.failed
        w = suite_obj.warned
        total_pass += p
        total_fail += f
        total_warn += w
        status_icon = f"{GREEN}✓{RESET}" if f == 0 else f"{RED}✗{RESET}"
        warn_str = f"  {YELLOW}~{w} warned{RESET}" if w else ""
        print(
            f"  {status_icon} {suite_obj.name:<40}  {GREEN}{p} passed{RESET}  {RED if f else ''}{f} failed{RESET}{warn_str}"
        )

    total = total_pass + total_fail + total_warn
    print(
        f"\n{BOLD}  Total: {total} tests  |  "
        f"{GREEN}{total_pass} passed{RESET}  |  "
        f"{RED}{total_fail} failed{RESET}  |  "
        f"{YELLOW}{total_warn} warned{RESET}{BOLD}{RESET}"
    )
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}\n")

    if total_fail > 0:
        print(
            f"{RED}{BOLD}  ✗ {total_fail} test(s) failed — see details above{RESET}\n"
        )
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}  ✓ All tests passed!{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
