"""Phase 8: lokal kunlik jamlanma, guruh kesimi, grafik va CSV eksport.

Faqat tasdiqlangan cheklar hisoblanadi. Guruh kesimida moliyaviy tushum
ko'rsatilmaydi — chekda guruh FK yo'q, soxta bo'lib ketmasin.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus, PaymentStatus
from app.db.models import (
    Ad,
    Category,
    CleanupLog,
    CounterMessageCheck,
    Group,
    GroupMessageAction,
    InviteEvent,
    Payment,
    PostLog,
    Seller,
    StatsDaily,
    Violation,
)
from app.services.settings_service import settings_service
from app.utils.time import utcnow

_METRICS = ("posts", "active_ads", "joins", "leaves", "violations",
            "deleted_msgs", "new_sellers", "payments_amount")
_BLOCKS = "▁▂▃▄▅▆▇█"


async def report_timezone(session: AsyncSession) -> ZoneInfo:
    name = str(await settings_service.get("timezone", "Asia/Tashkent", session))
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


async def last_closed_day(session: AsyncSession) -> date:
    return utcnow().astimezone(await report_timezone(session)).date() - timedelta(days=1)


async def _counts(session: AsyncSession, model, column, *conditions) -> dict[int, int]:
    rows = (await session.execute(select(model.group_id, func.count(column))
                                  .where(*conditions).group_by(model.group_id))).all()
    return {int(group_id): int(n) for group_id, n in rows if group_id is not None}


async def rollup_day(session: AsyncSession, day: date, tz: ZoneInfo) -> int:
    """Berilgan lokal kunni DB'da qayta hisoblash; har guruh alohida yozuv.

    Kun chegaralari UTC'ga o'tkaziladi (DST bo'lsa ham 23/25 soat to'g'ri).
    PK bo'yicha UPSERT — bir nechta scheduler process qayta ishlasa ham dubl yo'q.
    """
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    groups = (await session.execute(select(Group.id))).scalars().all()
    posts = await _counts(session, PostLog, PostLog.id,
                          PostLog.status == "ok", PostLog.created_at >= start,
                          PostLog.created_at < end)
    joins = await _counts(session, InviteEvent, InviteEvent.id,
                          InviteEvent.counted.is_(True), InviteEvent.created_at >= start,
                          InviteEvent.created_at < end)
    leaves = await _counts(session, InviteEvent, InviteEvent.id,
                           InviteEvent.reject_reason == "left_early", InviteEvent.updated_at >= start,
                           InviteEvent.updated_at < end)
    violations = await _counts(session, Violation, Violation.id,
                               Violation.created_at >= start, Violation.created_at < end)
    cleaned = (await session.execute(select(CleanupLog.group_id,
                                            func.coalesce(func.sum(CleanupLog.deleted_count), 0))
                                     .where(CleanupLog.created_at >= start, CleanupLog.created_at < end)
                                     .group_by(CleanupLog.group_id))).all()
    deleted = {int(group_id): int(n) for group_id, n in cleaned}
    guard_deleted = await _counts(session, GroupMessageAction, GroupMessageAction.id,
                                  GroupMessageAction.source == "guard",
                                  GroupMessageAction.planned_action == "delete",
                                  GroupMessageAction.status == "done",
                                  GroupMessageAction.updated_at >= start,
                                  GroupMessageAction.updated_at < end)
    counter_deleted = await _counts(session, CounterMessageCheck, CounterMessageCheck.id,
                                    CounterMessageCheck.status == "deleted",
                                    CounterMessageCheck.updated_at >= start,
                                    CounterMessageCheck.updated_at < end)
    for counts in (guard_deleted, counter_deleted):
        for group_id, n in counts.items():
            deleted[group_id] = deleted.get(group_id, 0) + n
    active_rows = (await session.execute(select(Category.group_id, func.count(Ad.id))
                                         .join(Ad, Ad.category_id == Category.id)
                                         .where(Ad.status == AdStatus.ACTIVE,
                                                Category.group_id.is_not(None))
                                         .group_by(Category.group_id))).all()
    active = {int(gid): int(n) for gid, n in active_rows}
    active_total = int((await session.execute(select(func.count(Ad.id)).where(
        Ad.status == AdStatus.ACTIVE,
    ))).scalar_one())
    new_sellers = int((await session.execute(select(func.count(Seller.id)).where(
        Seller.created_at >= start, Seller.created_at < end,
    ))).scalar_one())
    amount = (await session.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == PaymentStatus.APPROVED,
        Payment.decided_at >= start, Payment.decided_at < end,
    ))).scalar_one()

    dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
    upsert = sqlite_insert if dialect == "sqlite" else pg_insert
    for group_id in (0, *groups):
        values = dict(day=day, group_id=group_id,
                      posts=sum(posts.values()) if group_id == 0 else posts.get(group_id, 0),
                      active_ads=active_total if group_id == 0 else active.get(group_id, 0),
                      joins=sum(joins.values()) if group_id == 0 else joins.get(group_id, 0),
                      leaves=sum(leaves.values()) if group_id == 0 else leaves.get(group_id, 0),
                      violations=(sum(violations.values()) if group_id == 0
                                  else violations.get(group_id, 0)),
                      deleted_msgs=(sum(deleted.values()) if group_id == 0
                                    else deleted.get(group_id, 0)),
                      new_sellers=new_sellers if group_id == 0 else 0,
                      payments_amount=amount if group_id == 0 else Decimal("0"),
                      created_at=utcnow(), updated_at=utcnow())
        stmt = upsert(StatsDaily).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[StatsDaily.day, StatsDaily.group_id],
            set_={**{key: values[key] for key in _METRICS}, "updated_at": utcnow()},
        )
        await session.execute(stmt)
    return len(groups) + 1


async def day_series(session: AsyncSession, days: int = 7,
                     group_id: int = 0) -> list[StatsDaily | None]:
    if days not in (1, 7, 30):
        raise ValueError("Kunlar oralig'i 1, 7 yoki 30 bo'lishi kerak.")
    if group_id != 0 and await session.get(Group, group_id) is None:
        raise ValueError("Guruh topilmadi.")
    end = await last_closed_day(session)
    start = end - timedelta(days=days - 1)
    rows = (await session.execute(select(StatsDaily).where(
        StatsDaily.group_id == group_id, StatsDaily.day >= start, StatsDaily.day <= end,
    ).order_by(StatsDaily.day))).scalars().all()
    by_day = {row.day: row for row in rows}
    return [by_day.get(start + timedelta(days=i)) for i in range(days)]


def sparkline(values: list[int | float]) -> str:
    if not values:
        return "—"
    maximum = max(values)
    return "".join("·" if not x else _BLOCKS[min(7, round(x / maximum * 7))]
                   for x in values) if maximum else "·" * len(values)


async def csv_export(session: AsyncSession, days: int, group_id: int | None = None) -> bytes:
    """Yopiq kunlar CSV; group_id=None — barcha guruhlar + umumiy satr.

    Guruh nomidagi CSV formula injeksiyasi bartaraf etiladi; 20k qatordan
    katta eksport uchun aniq guruh tanlash talab qilinadi.
    """
    if days not in (1, 7, 30):
        raise ValueError("Eksport davri 1, 7 yoki 30 kun bo'lsin.")
    if group_id is not None and group_id != 0 and await session.get(Group, group_id) is None:
        raise ValueError("Guruh topilmadi.")
    end = await last_closed_day(session)
    start = end - timedelta(days=days - 1)
    stmt = (select(StatsDaily, Group.title).outerjoin(Group, StatsDaily.group_id == Group.id)
            .where(StatsDaily.day >= start, StatsDaily.day <= end)
            .order_by(StatsDaily.day, StatsDaily.group_id).limit(20_001))
    if group_id is not None:
        stmt = stmt.where(StatsDaily.group_id == group_id)
    rows = (await session.execute(stmt)).all()
    if len(rows) > 20_000:
        raise ValueError("Eksport 20 000 qatordan katta. Bitta guruhni tanlang.")
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("kun", "guruh_id", "guruh", "postlar", "faol_elonlar_snapshot",
                     "taklif_bilan_kirish", "erta_chiqish", "qoidabuzarlik", "ochirilgan",
                     "yangi_sotuvchi", "tasdiqlangan_bank_uzs"))
    for row, name in rows:
        title = name or ("Umumiy" if row.group_id == 0 else "—")
        if title.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            title = "'" + title
        writer.writerow((row.day.isoformat(), row.group_id, title, row.posts, row.active_ads,
                         row.joins, row.leaves, row.violations, row.deleted_msgs,
                         row.new_sellers, row.payments_amount))
    return ("\ufeff" + output.getvalue()).encode("utf-8")
