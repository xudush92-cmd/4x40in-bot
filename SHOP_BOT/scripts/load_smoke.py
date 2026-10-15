"""Phase 9: 200 guruh / 5000 e'lon / 24h tezlashtirilgan OFLAYN navbat sinovi.

Faqat vaqtinchalik SQLite bazasi va posting_service.due_group_ids / claim_post /
finish_post ishlatiladi. Telegram API, Redis, PostgreSQL, real scheduler yoki
rate-limit sinovi EMAS. Hech qachon mavjud production DB'ga ulanmaydi.

    python -m scripts.load_smoke
    python -m scripts.load_smoke --groups 4 --ads 40 --hours 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    Ad,
    Category,
    CategoryRotation,
    Group,
    GroupRotation,
    GroupSettings,
    PostLog,
    Seller,
    Subscription,
    Tariff,
)
from app.services import posting_service


def _percentile(samples: list[float], part: float) -> float:
    ordered = sorted(samples)
    return round(ordered[max(0, math.ceil(len(ordered) * part) - 1)], 2)


async def run(*, groups: int = 200, ads: int = 5000, hours: int = 24) -> dict:
    if groups < 1 or ads < groups or not 1 <= hours <= 24:
        raise ValueError("groups>=1, ads>=groups, 1<=hours<=24 bo'lishi kerak")
    started = time.perf_counter()
    # Ayni soatning boshida 24 ta tik: [t0, t0+1h, ..., t0+23h].
    horizon = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    with tempfile.TemporaryDirectory(prefix="shopbot-load-") as folder:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(folder) / 'load.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with factory() as session:
                seller = Seller(user_id=999999000, status="active")
                tariff = Tariff(name="Sintetik 5000 slot", max_ads=ads)
                session.add_all([seller, tariff])
                await session.flush()
                session.add(Subscription(
                    seller_id=seller.id, tariff_id=tariff.id,
                    starts_at=horizon - timedelta(days=1),
                    expires_at=horizon + timedelta(days=2),
                    ads_limit=ads, ads_used=ads,
                ))
                created = [
                    Group(tg_chat_id=-1000000000000 - i, title=f"Sinov {i}",
                          is_supergroup=True, bot_is_admin=True, is_active=True,
                          settings=GroupSettings(
                              posting_enabled=True, interval_sec=3600,
                              jitter_percent=0, daily_post_limit=50, timezone="UTC"),
                          rotation=GroupRotation(next_post_at=horizon))
                    for i in range(groups)
                ]
                session.add_all(created)
                await session.flush()
                categories = [
                    Category(group_id=group.id, name=f"Sinov {i}",
                             rotation=CategoryRotation(is_paused=False))
                    for i, group in enumerate(created)
                ]
                session.add_all(categories)
                await session.flush()
                rows = [
                    {"seller_id": seller.id, "category_id": categories[i % groups].id,
                     "group_id": categories[i % groups].group_id,
                     "title": f"E'lon {i}", "position": i, "status": "active"}
                    for i in range(ads)
                ]
                await session.execute(insert(Ad), rows)
                await session.commit()

            seeded = time.perf_counter()
            timings: list[float] = []
            posted = 0
            async with factory() as session:
                for hour in range(hours):
                    now = horizon + timedelta(hours=hour)
                    due = await posting_service.due_group_ids(session, now, limit=groups)
                    if len(due) != groups:
                        raise RuntimeError(f"{hour}-soat: {len(due)}/{groups} guruh navbatda")
                    for gid in due:
                        begin = time.perf_counter()
                        claim, result = await posting_service.claim_post(session, gid, now)
                        if claim is None:
                            raise RuntimeError(f"{hour}-soat, guruh {gid}: {result.status}")
                        await session.commit()  # Telegram'ga yuborishdan AVVAL band qilish
                        posted += 1
                        result = await posting_service.finish_post(session, claim, [posted], now)
                        if result.status != "sent":
                            raise RuntimeError(f"{hour}-soat, guruh {gid}: {result.status}")
                        await session.commit()  # Bot API chaqiruvi bu sinovda yo'q
                        timings.append((time.perf_counter() - begin) * 1000)
                count = (await session.execute(
                    select(func.count()).select_from(PostLog).where(PostLog.status == "ok")
                )).scalar_one()
                if count != groups * hours or posted != count:
                    raise RuntimeError(f"Postlar soni kutilganidan farqli: {count}")
            return {
                "type": "offline_sqlite_only", "groups": groups, "ads": ads,
                "simulated_hours": hours, "post_count": posted,
                "seed_seconds": round(seeded - started, 2),
                "total_seconds": round(time.perf_counter() - started, 2),
                "claim_finish_p50_ms": _percentile(timings, 0.50),
                "claim_finish_p95_ms": _percentile(timings, 0.95),
                "claim_finish_p99_ms": _percentile(timings, 0.99),
            }
        finally:
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Oflayn SQLite navbat stress-smoke (production EMAS)")
    parser.add_argument("--groups", type=int, default=200)
    parser.add_argument("--ads", type=int, default=5000)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(groups=args.groups, ads=args.ads, hours=args.hours)),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
