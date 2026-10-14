"""Rejalashtirilgan vazifalar (APScheduler job'lari).

Phase 0 da ishlaydiganlari:
  * heartbeat      — tizim "tirik" ekanini Redis'ga yozish
  * rights_check   — bot admin huquqini yo'qotgan guruhlarni to'xtatish (REJA.md 8.7)
  * retention      — eski loglarni tozalash (REJA.md 11.1)
  * daily_stats    — kunlik statistika jamlanmasi (REJA.md 4.9)

Keyingi bosqichlarda qo'shiladi:
  * posting_tick   — aylanma joylash (Phase 4)
  * reminders      — tarif eslatmalari (Phase 2)
  * referral/bonus — bonus hisoblash (Phase 8)
"""

from __future__ import annotations

import time
from datetime import timedelta

from aiogram import Bot
from loguru import logger
from sqlalchemy import delete, func, select, update

from app.constants import AdStatus, RedisKey
from app.db.base import session_scope
from app.db.models import (
    Ad,
    CleanupLog,
    ErrorLog,
    Group,
    GroupRotation,
    GroupSettings,
    Payment,
    PostLog,
    Seller,
    StatsDaily,
    Subscription,
    Violation,
)
from app.redis_client import redis_manager
from app.services.group_service import apply_rights_check, check_group_rights
from app.services.notify import notify_admins
from app.services.settings_service import settings_service
from app.utils.time import utcnow

_last_posting_notice = 0.0


async def heartbeat_job() -> None:
    """Har daqiqada: qaysi process ishlayotganini Redis'ga yozamiz."""
    key = RedisKey.HEARTBEAT.format(name="bot")
    payload = utcnow().isoformat()
    await redis_manager.set(key, payload, ttl=180)
    logger.debug("Heartbeat: {}", payload)


async def posting_tick_job(bot: Bot) -> None:
    """Aylanma joylash tick'i.

    Phase 0 da: navbatga tayyor guruhlar bor-yo'qligini hisoblaydi.
    Haqiqiy joylash mantig'i Phase 4 da qo'shiladi (REJA.md 9).
    """
    global _last_posting_notice

    if not await settings_service.is_feature_enabled("posting"):
        return

    now = utcnow()
    async with session_scope() as session:
        due = (
            await session.execute(
                select(func.count())
                .select_from(GroupRotation)
                .join(Group, Group.id == GroupRotation.group_id)
                .join(GroupSettings, GroupSettings.group_id == Group.id)
                .where(
                    Group.is_active.is_(True),
                    GroupSettings.posting_enabled.is_(True),
                    GroupRotation.next_post_at.is_not(None),
                    GroupRotation.next_post_at <= now,
                )
            )
        ).scalar_one()

    if due and time.monotonic() - _last_posting_notice > 300:
        _last_posting_notice = time.monotonic()
        logger.info(
            "{} ta guruhda joylash vaqti keldi — aylanma dvigatel Phase 4 da ulanadi",
            due,
        )
    _ = bot


async def rights_check_job(bot: Bot) -> None:
    """Bot hali ham admin ekanini tekshirish (REJA.md 8.7).

    Huquq yo'qolgan bo'lsa — guruh to'xtatiladi va adminga xabar ketadi.
    Mantiq `group_service` da (admin panel tugmasi bilan bir xil kod ishlatiladi).
    """
    async with session_scope() as session:
        groups = (
            await session.execute(
                select(Group)
                .join(GroupSettings, GroupSettings.group_id == Group.id)
                .where(
                    Group.is_active.is_(True),
                    (GroupSettings.posting_enabled.is_(True))
                    | (GroupSettings.guard_enabled.is_(True))
                    | (GroupSettings.cleaner_enabled.is_(True)),
                )
                .limit(200)
            )
        ).scalars().all()

        checked = 0
        problems = 0
        for group in groups:
            result = await check_group_rights(bot, group)
            ok = await apply_rights_check(session, bot, group, result, notify=True)
            checked += 1
            problems += 0 if ok else 1

    logger.debug("Huquqlar tekshirildi: {} guruh, muammo: {}", checked, problems)


async def retention_job() -> None:
    """Eski loglarni tozalash (baza shishib ketmasligi uchun)."""
    retention_days = int(await settings_service.get("log_retention_days", 90) or 90)
    now = utcnow()
    log_cutoff = now - timedelta(days=retention_days)
    post_cutoff = now - timedelta(days=90)
    cleanup_cutoff = now - timedelta(days=60)

    async with session_scope() as session:
        r1 = await session.execute(delete(ErrorLog).where(ErrorLog.created_at < log_cutoff))
        r2 = await session.execute(delete(PostLog).where(PostLog.created_at < post_cutoff))
        r3 = await session.execute(delete(CleanupLog).where(CleanupLog.created_at < cleanup_cutoff))

    logger.info(
        "Retention: error_log -{}, post_log -{}, cleanup_log -{} (eski yozuvlar o'chirildi)",
        r1.rowcount,
        r2.rowcount,
        r3.rowcount,
    )


async def daily_stats_job() -> None:
    """Kechagi kun uchun jamlanma statistika (grafiklar tez chiqishi uchun)."""
    yesterday = (utcnow() - timedelta(days=1)).date()
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    end = start + timedelta(days=1)

    async with session_scope() as session:
        posts = (
            await session.execute(
                select(func.count()).select_from(PostLog).where(
                    PostLog.created_at >= start, PostLog.created_at < end
                )
            )
        ).scalar_one()
        new_sellers = (
            await session.execute(
                select(func.count()).select_from(Seller).where(
                    Seller.created_at >= start, Seller.created_at < end
                )
            )
        ).scalar_one()
        violations = (
            await session.execute(
                select(func.count()).select_from(Violation).where(
                    Violation.created_at >= start, Violation.created_at < end
                )
            )
        ).scalar_one()
        amount = (
            await session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.decided_at >= start, Payment.decided_at < end
                )
            )
        ).scalar_one()
        deleted = (
            await session.execute(
                select(func.coalesce(func.sum(CleanupLog.deleted_count), 0)).where(
                    CleanupLog.created_at >= start, CleanupLog.created_at < end
                )
            )
        ).scalar_one()
        active_ads = (
            await session.execute(
                select(func.count()).select_from(Ad).where(Ad.status == AdStatus.ACTIVE)
            )
        ).scalar_one()

        row = await session.get(StatsDaily, {"day": yesterday, "group_id": 0})
        if row is None:
            row = StatsDaily(day=yesterday, group_id=0)
            session.add(row)

        row.posts = int(posts)
        row.new_sellers = int(new_sellers)
        row.violations = int(violations)
        row.payments_amount = amount or 0
        row.deleted_msgs = int(deleted or 0)
        row.active_ads = int(active_ads)

    logger.info("Kunlik statistika saqlandi: {} (postlar: {})", yesterday, posts)


async def expire_subscriptions_job(bot: Bot) -> None:
    """Muddati tugagan obunalarni yopish va e'lonlarni pauzaga olish (Phase 2 uchun tayyor)."""
    now = utcnow()
    async with session_scope() as session:
        expired = (
            await session.execute(
                select(Subscription).where(
                    Subscription.status == "active", Subscription.expires_at <= now
                )
            )
        ).scalars().all()

        for sub in expired:
            sub.status = "expired"
            await session.execute(
                update(Ad)
                .where(Ad.seller_id == sub.seller_id, Ad.status == AdStatus.ACTIVE)
                .values(status=AdStatus.EXPIRED)
            )

    if expired:
        logger.info("Muddati tugagan obunalar: {} ta", len(expired))
    _ = bot


__all__ = [
    "daily_stats_job",
    "expire_subscriptions_job",
    "heartbeat_job",
    "posting_tick_job",
    "retention_job",
    "rights_check_job",
]
