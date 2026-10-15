"""Rejalashtirilgan vazifalar (APScheduler job'lari).

  * heartbeat, rights_check, retention, daily_stats
  * posting_tick   — har 10 sekundda Phase 4 joylash dvigateli
  * reminders      — tarif eslatmalari (Phase 2)
  * referral/bonus — keyingi bosqich (Phase 8)
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from aiogram import Bot
from loguru import logger
from sqlalchemy import delete, func, select, update

from app.constants import AdStatus, RedisKey, SubscriptionStatus
from app.db.base import session_scope
from app.db.models import (
    Ad,
    CleanupLog,
    ErrorLog,
    Group,
    GroupSettings,
    Payment,
    PostLog,
    Seller,
    StatsDaily,
    Violation,
)
from app.redis_client import redis_manager
from app.scheduler.poster import post_group
from app.services import posting_service, seller_service, subscription_service
from app.services.group_service import apply_rights_check, check_group_rights
from app.services.notify import notify_admins, save_error
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.utils.time import fmt_date, utcnow


async def heartbeat_job() -> None:
    """Har daqiqada: qaysi process ishlayotganini Redis'ga yozamiz."""
    key = RedisKey.HEARTBEAT.format(name="bot")
    payload = utcnow().isoformat()
    await redis_manager.set(key, payload, ttl=180)
    logger.debug("Heartbeat: {}", payload)


async def posting_tick_job(bot: Bot) -> None:
    """Har 10 sekundda tayyor guruhlar; bitta xato qolganlarini to'xtatmaydi."""
    now = utcnow()
    if not await settings_service.is_feature_enabled("posting") or await settings_service.get("maintenance_mode", False):
        # Pauza davomida eski due vaqtlar qarzga aylanmasin.
        async with session_scope() as session:
            await posting_service.rebase_paused(session, now, limit=1000)
        return

    async with session_scope() as session:
        due = await posting_service.due_group_ids(session, now)
    limiter = asyncio.Semaphore(10)  # 1000 guruhda Bot API kutishlari parallel, DB claim alohida

    async def _one(group_id: int) -> None:
        async with limiter:
            try:
                await post_group(bot, group_id)
            except Exception as exc:
                logger.exception("Poster job xatosi (guruh={}): {}", group_id, exc)
                await save_error(None, "poster", f"{type(exc).__name__}: {exc}", exc=exc, group_id=group_id)
                try:
                    await notify_admins(bot, f"⚠️ Poster xatosi (guruh #{group_id}): {type(exc).__name__}")
                except Exception:
                    pass

    await asyncio.gather(*(_one(group_id) for group_id in due))


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
                    PostLog.status == "ok", PostLog.created_at >= start, PostLog.created_at < end
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
    """Muddati o'tgan obunalarni yopish (REJA.md 4.3, 8.2).

    `subscription_grace_days = 0` → darhol `expired`; aks holda avval `grace`.
    Muddati tugagan obunaning e'lonlari `expired` holatiga o'tadi
    (e'lon joylash Phase 4 da shu holatga qarab to'xtaydi).
    """
    async with session_scope() as session:
        grace_days = int(await settings_service.get("subscription_grace_days", 0, session) or 0)
        changed = await subscription_service.expire_due(session, grace_days=grace_days)
        expiring_ids = [sub.id for sub in changed if sub.status == SubscriptionStatus.EXPIRED]

        for seller_id in {sub.seller_id for sub in changed}:
            await session.execute(
                update(Ad)
                .where(Ad.seller_id == seller_id, Ad.status == AdStatus.ACTIVE)
                .values(status=AdStatus.EXPIRED)
            )

    if changed:
        logger.info(
            "Obunalar yangilandi: {} ta (to'liq yopilgan: {})", len(changed), len(expiring_ids)
        )
    _ = bot


async def subscription_reminders_job(bot: Bot) -> None:
    """Tarif tugashi haqida eslatma + muddati o'tgani haqida xabar (Phase 2).

    Eslatma bir marta yuboriladi (`reminder_sent_at`), muddati o'tgani haqidagi
    xabar ham bir marta (`expired_notified_at`).
    """

    sent_reminders = 0
    sent_expired = 0

    async with session_scope() as session:
        days = int(await settings_service.get("subscription_reminder_days", 3, session) or 3)
        support = await settings_service.get("support_contact", "@admin", session)

        # 1) Muddati yaqinlashgan obunalar
        for subscription in await subscription_service.reminders_due(session, days=days):
            seller = await seller_service.get_seller_by_id(session, subscription.seller_id)
            if seller is None:
                subscription_service.mark_reminded(subscription)
                continue

            text = await text_service.get(
                "seller.subscription_reminder",
                kun=max(0, subscription_service.days_left(subscription)),
                sana=fmt_date(subscription.expires_at),
                qoldi=subscription.ads_left,
                yordam=str(support),
            )
            if await _send_to_seller(bot, seller.user_id, text):
                subscription_service.mark_reminded(subscription)
                sent_reminders += 1

        # 2) Muddati o'tgan, ammo xabar berilmagan obunalar
        for subscription in await subscription_service.expired_without_notice(session):
            seller = await seller_service.get_seller_by_id(session, subscription.seller_id)
            if seller is None:
                subscription_service.mark_expired_notified(subscription)
                continue

            text = await text_service.get("seller.subscription_expired", yordam=str(support))
            if await _send_to_seller(bot, seller.user_id, text):
                subscription_service.mark_expired_notified(subscription)
                sent_expired += 1

        await session.flush()

    if sent_reminders or sent_expired:
        logger.info(
            "Obuna xabarlari: eslatma {} ta, muddati o'tgani {} ta", sent_reminders, sent_expired
        )


async def _send_to_seller(bot: Bot, user_id: int, text: str) -> bool:
    """Sotuvchiga xabar; bot bloklangan bo'lsa False (qayta urinmaslik uchun belgilanadi)."""
    from aiogram.exceptions import TelegramAPIError

    try:
        await bot.send_message(user_id, text, disable_web_page_preview=True)
        return True
    except TelegramAPIError as exc:
        logger.debug("Sotuvchi {} ga xabar yuborilmadi: {}", user_id, exc)
        return True  # bloklangan bo'lsa ham qayta urinmaymiz
    except Exception as exc:  # pragma: no cover — kutilmagan xato
        logger.warning("Xabar yuborishda xato ({}): {}", user_id, exc)
        return False


__all__ = [
    "daily_stats_job",
    "expire_subscriptions_job",
    "heartbeat_job",
    "posting_tick_job",
    "retention_job",
    "rights_check_job",
    "subscription_reminders_job",
]
