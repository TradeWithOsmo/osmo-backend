import asyncio
import json
import os
from collections import defaultdict
from typing import Dict, List, Tuple

import httpx
import websockets

API_BASE = os.getenv("CHECK_API_BASE", "http://127.0.0.1:8000")
WS_BASE = os.getenv("CHECK_WS_BASE", "ws://127.0.0.1:8000/ws")
MAX_PER_SOURCE = int(os.getenv("MAX_PER_SOURCE", "0"))  # 0 = all symbols
OPEN_TIMEOUT_S = float(os.getenv("WS_OPEN_TIMEOUT_S", "2.5"))
TIMEOUT_S = float(os.getenv("WS_TIMEOUT_S", "3.0"))
CONCURRENCY = int(os.getenv("CHECK_CONCURRENCY", "80"))
MAX_BAD_SAMPLES = int(os.getenv("MAX_BAD_SAMPLES", "8"))


def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _valid_orderbook_payload(message: Dict) -> bool:
    if message.get("type") != "l2Book":
        return False
    data = message.get("data", {})
    levels = data.get("levels")
    if not isinstance(levels, list) or len(levels) != 2:
        return False

    for side in levels:
        for lv in side or []:
            px = _safe_float((lv or {}).get("px"))
            sz = _safe_float((lv or {}).get("sz"))
            if px > 0 and sz > 0:
                return True
    return False


def _valid_trades_payload(message: Dict) -> bool:
    if message.get("type") != "trades":
        return False
    rows = message.get("data", [])
    if not isinstance(rows, list) or not rows:
        return False
    for t in rows:
        px = _safe_float((t or {}).get("px"))
        sz = _safe_float((t or {}).get("sz"))
        if px > 0 and sz > 0:
            return True
    return False


async def _check_ws(url: str, validator) -> str:
    try:
        async with websockets.connect(url, open_timeout=OPEN_TIMEOUT_S) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_S)
                msg = json.loads(raw)
                if validator(msg):
                    return "ok"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception:
        return "error"


async def check_symbol(symbol: str) -> Tuple[str, str]:
    ob_task = asyncio.create_task(_check_ws(f"{WS_BASE}/orderbook/{symbol}", _valid_orderbook_payload))
    tr_task = asyncio.create_task(_check_ws(f"{WS_BASE}/trades/{symbol}", _valid_trades_payload))
    ob_status, tr_status = await asyncio.gather(ob_task, tr_task)
    return ob_status, tr_status


async def _check_with_semaphore(source: str, symbol: str, sem: asyncio.Semaphore):
    async with sem:
        ob_status, tr_status = await check_symbol(symbol)
        return source, symbol, ob_status, tr_status


async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(f"{API_BASE}/api/markets/?canonical_only=true")
        resp.raise_for_status()
        markets = resp.json().get("markets", [])

    grouped: Dict[str, List[str]] = defaultdict(list)
    for m in markets:
        src = str(m.get("source", "")).lower().strip()
        sym = str(m.get("symbol", "")).strip()
        if src and sym:
            grouped[src].append(sym)

    symbols_by_source: Dict[str, List[str]] = {}
    for src, syms in grouped.items():
        unique = list(dict.fromkeys(syms))
        symbols_by_source[src] = unique[:MAX_PER_SOURCE] if MAX_PER_SOURCE > 0 else unique

    sem = asyncio.Semaphore(max(1, CONCURRENCY))
    tasks = []
    for src in sorted(symbols_by_source.keys()):
        for sym in symbols_by_source[src]:
            tasks.append(asyncio.create_task(_check_with_semaphore(src, sym, sem)))

    stats = {
        src: {
            "tested": 0,
            "ob_ok": 0,
            "tr_ok": 0,
            "ob_timeout": 0,
            "tr_timeout": 0,
            "ob_error": 0,
            "tr_error": 0,
        }
        for src in symbols_by_source.keys()
    }
    bad_samples: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for coro in asyncio.as_completed(tasks):
        src, sym, ob_status, tr_status = await coro
        row = stats[src]
        row["tested"] += 1
        row[f"ob_{ob_status}"] += 1
        row[f"tr_{tr_status}"] += 1

        if (ob_status != "ok" or tr_status != "ok") and len(bad_samples[src]) < MAX_BAD_SAMPLES:
            bad_samples[src].append({"symbol": sym, "ob": ob_status, "tr": tr_status})

    total_tested = sum(v["tested"] for v in stats.values())
    print(f"Total markets from API: {len(markets)}")
    print(f"Total tested symbols: {total_tested}")
    print(
        f"Config: max_per_source={MAX_PER_SOURCE or 'all'}, "
        f"concurrency={CONCURRENCY}, ws_open_timeout={OPEN_TIMEOUT_S}s, ws_timeout={TIMEOUT_S}s"
    )
    print("-" * 115)
    print(
        f"{'Source':<15} {'Tested':>6} {'OB OK':>7} {'TR OK':>7} "
        f"{'OB Timeout':>10} {'TR Timeout':>10} {'OB Error':>9} {'TR Error':>9}"
    )
    print("-" * 115)

    for src in sorted(stats.keys()):
        row = stats[src]
        print(
            f"{src:<15} {row['tested']:>6} {row['ob_ok']:>7} {row['tr_ok']:>7} "
            f"{row['ob_timeout']:>10} {row['tr_timeout']:>10} {row['ob_error']:>9} {row['tr_error']:>9}"
        )

    print("\nSample non-OK symbols:")
    for src in sorted(bad_samples.keys()):
        print(f"[{src}]")
        for item in bad_samples[src]:
            print(item)


if __name__ == "__main__":
    asyncio.run(main())
