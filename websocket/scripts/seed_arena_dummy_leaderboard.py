import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta

# Add parent directory (websocket/) to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import AsyncSessionLocal, init_db
from database.models import LeaderboardSnapshot
from database.arena_models import ArenaLeaderboard


AI_MODELS = [
    "gpt-4o",
    "claude-3.5-sonnet",
    "gemini-1.5-pro",
    "deepseek-v3",
    "qwen-2.5",
]


def _addr(base_hex: int, i: int) -> str:
    # Produce a valid 20-byte hex address.
    return f"0x{(base_hex + i):040x}"


def _gen_rows(snapshot_date: date, timeframe: str, per_side: int):
    rng = random.Random(42)

    # Keep them within valid 160-bit ranges.
    base_human = int("1000000000000000000000000000000000000000", 16)
    base_ai = int("2000000000000000000000000000000000000000", 16)

    rows = []

    for i in range(1, per_side + 1):
        addr = _addr(base_human, i)
        account_value = 25_000 + (per_side - i) * 900 + rng.randint(-300, 300)
        pnl = rng.randint(-800, 4_500)
        roi = (pnl / max(1.0, account_value)) * 100.0
        volume = float(account_value) * rng.uniform(8.0, 35.0)
        trade_count = rng.randint(3, 120)
        win_rate = rng.uniform(32.0, 78.0)

        rows.append(
            dict(
                snapshot_date=snapshot_date,
                timeframe=timeframe,
                user_address=addr,
                account_value=float(account_value),
                pnl=float(pnl),
                roi=float(roi),
                volume=float(volume),
                trade_count=int(trade_count),
                win_rate=float(win_rate),
                agent_model=None,
                rank=i,
                created_at=datetime.utcnow(),
            )
        )

    # AI rows: keep ranks after humans to avoid tie-order issues in the "all traders" view.
    for i in range(1, per_side + 1):
        addr = _addr(base_ai, i)
        model = AI_MODELS[(i - 1) % len(AI_MODELS)]
        account_value = 30_000 + (per_side - i) * 1_100 + rng.randint(-500, 500)
        pnl = rng.randint(-500, 6_500)
        roi = (pnl / max(1.0, account_value)) * 100.0
        volume = float(account_value) * rng.uniform(10.0, 45.0)
        trade_count = rng.randint(5, 160)
        win_rate = rng.uniform(35.0, 82.0)

        rows.append(
            dict(
                snapshot_date=snapshot_date,
                timeframe=timeframe,
                user_address=addr,
                account_value=float(account_value),
                pnl=float(pnl),
                roi=float(roi),
                volume=float(volume),
                trade_count=int(trade_count),
                win_rate=float(win_rate),
                agent_model=model,
                rank=per_side + i,
                created_at=datetime.utcnow(),
            )
        )

    # ArenaLeaderboard (optional) so /api/arena/leaderboard stays non-empty too.
    arena_rows = []
    now = datetime.utcnow()
    for i in range(1, per_side + 1):
        arena_rows.append(
            dict(
                user_address=_addr(base_human, i),
                side="human",
                pnl=float(rows[i - 1]["pnl"]),
                roi=float(rows[i - 1]["roi"]),
                volume=float(rows[i - 1]["volume"]),
                rank=i,
                last_updated=now,
            )
        )
    for i in range(1, per_side + 1):
        idx = per_side + (i - 1)
        arena_rows.append(
            dict(
                user_address=_addr(base_ai, i),
                side="ai",
                pnl=float(rows[idx]["pnl"]),
                roi=float(rows[idx]["roi"]),
                volume=float(rows[idx]["volume"]),
                rank=i,
                last_updated=now,
            )
        )

    return rows, arena_rows


async def seed(snapshot_date: date, timeframe: str, per_side: int):
    await init_db()

    trader_rows, arena_rows = _gen_rows(snapshot_date, timeframe, per_side)
    addrs = [r["user_address"] for r in trader_rows]

    async with AsyncSessionLocal() as db:
        # Remove prior dummy rows for a clean reseed.
        await db.execute(
            delete(LeaderboardSnapshot).where(
                LeaderboardSnapshot.snapshot_date == snapshot_date,
                LeaderboardSnapshot.timeframe == timeframe,
                LeaderboardSnapshot.user_address.in_(addrs),
            )
        )
        await db.execute(delete(ArenaLeaderboard).where(ArenaLeaderboard.user_address.in_(addrs)))
        await db.commit()

        # Upsert leaderboard snapshots.
        stmt = pg_insert(LeaderboardSnapshot).values(trader_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["snapshot_date", "timeframe", "user_address"],
            set_={
                "account_value": stmt.excluded.account_value,
                "pnl": stmt.excluded.pnl,
                "roi": stmt.excluded.roi,
                "volume": stmt.excluded.volume,
                "trade_count": stmt.excluded.trade_count,
                "win_rate": stmt.excluded.win_rate,
                "agent_model": stmt.excluded.agent_model,
                "rank": stmt.excluded.rank,
                "created_at": stmt.excluded.created_at,
            },
        )
        await db.execute(stmt)

        # Insert arena leaderboard rows (simple table; delete+insert is enough).
        await db.execute(pg_insert(ArenaLeaderboard).values(arena_rows))

        await db.commit()

    print(
        f"Seeded dummy Arena leaderboard data: {per_side} human + {per_side} ai "
        f"into leaderboard_snapshots(timeframe={timeframe}, date={snapshot_date.isoformat()}) "
        f"and arena_leaderboard."
    )


def _parse_args(argv):
    # Minimal args parsing; keep it dependency-free.
    snapshot_date = date.today()
    timeframe = "7d"
    per_side = 40

    for a in argv[1:]:
        if a.startswith("--date="):
            snapshot_date = date.fromisoformat(a.split("=", 1)[1])
        elif a.startswith("--timeframe="):
            timeframe = a.split("=", 1)[1]
        elif a.startswith("--per-side="):
            per_side = int(a.split("=", 1)[1])

    if timeframe not in ("24h", "7d", "30d", "all"):
        raise SystemExit("--timeframe must be one of: 24h, 7d, 30d, all")
    if per_side < 1 or per_side > 2000:
        raise SystemExit("--per-side must be between 1 and 2000")

    return snapshot_date, timeframe, per_side


if __name__ == "__main__":
    d, tf, n = _parse_args(sys.argv)
    asyncio.run(seed(d, tf, n))

