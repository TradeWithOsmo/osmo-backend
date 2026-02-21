"""
Benchmark latency per tool category and compute p95/p99.

Usage example:
  backend/.venv/Scripts/python.exe scripts/benchmark_tools_latency.py \
    --base-url http://localhost:8000 \
    --token <jwt> \
    --wallet 0x... \
    --iterations 30 \
    --warmup 5 \
    --json-out reports/tools-latency.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import httpx


@dataclass(frozen=True)
class Case:
    category: str
    name: str
    path: str
    payload: Dict[str, Any]
    method: str = "POST"


CASES: Sequence[Case] = (
    Case(
        category="market",
        name="data.price",
        path="/api/tools/data/price",
        payload={"symbol": "BTC-USD", "asset_type": "crypto"},
    ),
    Case(
        category="market",
        name="data.candles",
        path="/api/tools/data/candles",
        payload={
            "symbol": "BTC-USD",
            "timeframe": "1H",
            "limit": 120,
            "asset_type": "crypto",
        },
    ),
    Case(
        category="research",
        name="research.market",
        path="/api/tools/research/market",
        payload={"symbol": "BTC-USD", "timeframe": "1H", "include_depth": False},
    ),
    Case(
        category="research",
        name="web.search",
        path="/api/tools/web/search",
        payload={"query": "BTC market update", "mode": "quality", "source": "news"},
    ),
    Case(
        category="tradingview",
        name="tv.focus_chart",
        path="/api/tools/tradingview/focus_chart",
        payload={"symbol": "BTC-USD"},
    ),
    Case(
        category="tradingview",
        name="tv.get_screenshot",
        path="/api/tools/tradingview/get_screenshot",
        payload={"symbol": "BTC-USD"},
    ),
    Case(
        category="execution",
        name="exec.get_positions",
        path="/api/tools/trade_execution/get_positions",
        payload={"exchange": "simulation"},
    ),
    Case(
        category="execution",
        name="exec.cancel_order",
        path="/api/tools/trade_execution/cancel_order",
        payload={"order_id": "ord-benchmark-smoke"},
    ),
)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _headers(token: str, wallet: str) -> Dict[str, str]:
    out = {"Content-Type": "application/json"}
    if token:
        out["Authorization"] = f"Bearer {token}"
    if wallet:
        out["X-Wallet-Address"] = wallet
    return out


async def _run_case_once(
    client: httpx.AsyncClient,
    case: Case,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    started = time.perf_counter()
    status = 0
    ok = False
    error = ""
    try:
        if case.method.upper() == "POST":
            response = await client.post(case.path, json=case.payload, headers=headers)
        else:
            response = await client.get(case.path, params=case.payload, headers=headers)
        status = response.status_code
        ok = 200 <= response.status_code < 300
        if not ok:
            error = response.text[:300]
    except Exception as exc:
        error = str(exc)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "category": case.category,
        "name": case.name,
        "status_code": status,
        "ok": ok,
        "latency_ms": latency_ms,
        "error": error,
    }


async def benchmark(
    *,
    base_url: str,
    token: str,
    wallet: str,
    iterations: int,
    warmup: int,
    categories: List[str],
) -> Dict[str, Any]:
    selected = [
        case for case in CASES if ("all" in categories or case.category in categories)
    ]
    if not selected:
        raise ValueError("No benchmark cases selected for provided categories.")

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        hdr = _headers(token=token, wallet=wallet)

        # Warmup
        for _ in range(max(0, warmup)):
            case = random.choice(selected)
            await _run_case_once(client, case, hdr)

        # Measured runs
        for i in range(max(1, iterations)):
            case = selected[i % len(selected)]
            results.append(await _run_case_once(client, case, hdr))

    def summarize(group: List[Dict[str, Any]]) -> Dict[str, Any]:
        lats = [float(item["latency_ms"]) for item in group]
        oks = [bool(item["ok"]) for item in group]
        return {
            "requests": len(group),
            "success_rate_pct": round(
                (sum(1 for x in oks if x) / len(group)) * 100.0, 2
            )
            if group
            else 0.0,
            "avg_ms": round(statistics.mean(lats), 2) if lats else 0.0,
            "p50_ms": round(_percentile(lats, 50), 2),
            "p95_ms": round(_percentile(lats, 95), 2),
            "p99_ms": round(_percentile(lats, 99), 2),
            "max_ms": round(max(lats), 2) if lats else 0.0,
            "min_ms": round(min(lats), 2) if lats else 0.0,
        }

    by_category: Dict[str, List[Dict[str, Any]]] = {}
    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for item in results:
        by_category.setdefault(item["category"], []).append(item)
        by_case.setdefault(item["name"], []).append(item)

    category_stats = {k: summarize(v) for k, v in sorted(by_category.items())}
    case_stats = {k: summarize(v) for k, v in sorted(by_case.items())}
    overall = summarize(results)

    return {
        "config": {
            "base_url": base_url,
            "iterations": iterations,
            "warmup": warmup,
            "categories": categories,
            "cases": [case.name for case in selected],
        },
        "overall": overall,
        "by_category": category_stats,
        "by_case": case_stats,
        "samples": results,
    }


def _print_summary(report: Dict[str, Any]) -> None:
    print("Tool Latency Benchmark")
    print(f"Base URL: {report['config']['base_url']}")
    print(
        "Overall: "
        f"req={report['overall']['requests']} "
        f"ok={report['overall']['success_rate_pct']}% "
        f"avg={report['overall']['avg_ms']}ms "
        f"p95={report['overall']['p95_ms']}ms "
        f"p99={report['overall']['p99_ms']}ms"
    )
    print("By category:")
    for category, stats in report["by_category"].items():
        print(
            f"- {category:<11} req={stats['requests']:<4} "
            f"ok={stats['success_rate_pct']:>6}% "
            f"avg={stats['avg_ms']:>8}ms "
            f"p95={stats['p95_ms']:>8}ms "
            f"p99={stats['p99_ms']:>8}ms"
        )


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark tools latency by category.")
    parser.add_argument(
        "--base-url", default="", help="Backend base URL, e.g. http://localhost:8000"
    )
    parser.add_argument("--token", default="", help="JWT bearer token")
    parser.add_argument(
        "--wallet", default="", help="Wallet address (X-Wallet-Address)"
    )
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument(
        "--categories",
        default="all",
        help="Comma list: all|market|research|tradingview|execution",
    )
    parser.add_argument(
        "--json-out", default="", help="Optional JSON report output path"
    )
    args = parser.parse_args()

    env_base = (
        str(os.getenv("TOOLS_BENCH_BASE_URL", "")).strip()
        or str(os.getenv("LIVE_E2E_BACKEND_URL", "")).strip()
    )
    env_token = (
        str(os.getenv("TOOLS_BENCH_TOKEN", "")).strip()
        or str(os.getenv("LIVE_E2E_TOKEN", "")).strip()
    )
    env_wallet = (
        str(os.getenv("TOOLS_BENCH_WALLET", "")).strip()
        or str(os.getenv("LIVE_E2E_WALLET", "")).strip()
    )
    env_iterations = int(str(os.getenv("TOOLS_BENCH_ITERATIONS", "80")).strip() or "80")
    env_warmup = int(str(os.getenv("TOOLS_BENCH_WARMUP", "8")).strip() or "8")

    base_url = str(args.base_url or env_base).rstrip("/")
    if not base_url:
        raise ValueError(
            "Missing --base-url (or set TOOLS_BENCH_BASE_URL / LIVE_E2E_BACKEND_URL)."
        )

    categories = [
        part.strip().lower() for part in str(args.categories).split(",") if part.strip()
    ]
    report = await benchmark(
        base_url=base_url,
        token=str(args.token or env_token).strip(),
        wallet=str(args.wallet or env_wallet).strip(),
        iterations=max(1, int(args.iterations or env_iterations)),
        warmup=max(0, int(args.warmup or env_warmup)),
        categories=categories or ["all"],
    )
    _print_summary(report)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
