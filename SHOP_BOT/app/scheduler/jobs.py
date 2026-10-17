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
from sqlalchemy import delete, select, update

from app.constants import AdStatus, RedisKey, SubscriptionStatus
from app.db.base import session_scope
from app.db.models import (
    Ad,
    CleanupLog,
    CounterJoinRequest,
    CounterMessageCheck,
    ErrorLog,
    FreePostLog,
    Group,
    GroupMessageAction,
    GroupSettings,
    PostLog,
    Restriction,
    Violation,
)
from app.handlers.group.counter import process_due, process_restrictions
from app.handlers.group.policy import process_due_cleanup
from app.redis_client import redis_manager
from app.scheduler import free_poster
from app.scheduler.poster import post_group
from app.services import (
    broadcast_service,
    posting_service,
    referral_service,
    report_service,
    seller_service,
    subscription_service,
)
from app.services.counter_notice_service import process_due_notices
from app.services.group_service import apply_rights_check, check_group_rights
from app.services.notify import notify_admins, save_error
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.utils.text import escape_html
from app.utils.time import ensure_aware, fmt_date, utcnow


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


_free_wait_cursor = 0


async def free_posting_tick_job(bot: Bot) -> None:
    """Bepul huquq/taymer va texnik navbat: bir guruhda 10s tick'ga bir post.

    Har reklama beruvchining next_post_at'i alohida; pullik 30 daqiqalik
    group_rotation.next_post_at uning o'rniga ishlatilmaydi. Guruhlar parallel.
    """
    global _free_wait_cursor
    now = utcnow()
    await free_poster.recover_stale(bot, now=now)
    if not await settings_service.is_feature_enabled_fresh("posting"):
        await free_poster.rebase_paused(now)
        return

    from app.db.models import FreeAd
    from app.services import free_ad_service as free_ads

    async with session_scope() as session:
        waiting = await free_ads.waiting_ids(session, now, after_id=_free_wait_cursor)
    _free_wait_cursor = waiting[-1] if len(waiting) == 100 else 0
    allow_new = await settings_service.is_feature_enabled_fresh("counter")
    for ad_id in waiting:
        try:
            async with session_scope() as session:
                ad = await session.get(FreeAd, ad_id)
                group = await session.get(Group, ad.group_id) if ad else None
                access = await free_ads.entitlement(session, ad.user_id, ad.group_id) if ad else None
                active = bool(access and ensure_aware(access.expires_at) > now)
                policy = await free_ads.terms(session, group) if allow_new and group else None
                enough = bool(policy and ad and await free_ads.unspent_count(
                    session, ad.group_id, ad.user_id) >= policy.required_n)
                if ad and not active and not enough:
                    ad.next_post_at = None
                candidate = (group.tg_chat_id, ad.user_id) if group and (active or enough) else None
            if candidate is not None and await free_ads.is_member(bot, *candidate):
                async with session_scope() as session:
                    ad = (await session.execute(select(FreeAd).where(FreeAd.id == ad_id)
                                                .with_for_update(skip_locked=True))).scalar_one_or_none()
                    if ad:
                        await free_ads.maybe_activate(session, ad, utcnow(),
                                                      member_ok=True, allow_new=allow_new)
        except Exception as exc:
            logger.exception("Bepul huquqni tekshirish #{}: {}", ad_id, exc)
            await save_error(None, "free_poster", f"Huquq #{ad_id}: {type(exc).__name__}: {exc}", exc=exc)

    async with session_scope() as session:
        due = await free_ads.due_one_per_group(session, utcnow())
    limiter = asyncio.Semaphore(10)

    async def _one(ad_id: int) -> None:
        async with limiter:
            try:
                await free_poster.post_one(bot, ad_id)
            except Exception as exc:
                logger.exception("Bepul poster xatosi (e'lon={}): {}", ad_id, exc)
                await save_error(None, "free_poster", f"Post #{ad_id}: {type(exc).__name__}: {exc}", exc=exc)
                # Agar claim allaqachon commit bo'lgan bo'lsa, sending log
                # stale recovery orqali noma'lum holatga o'tadi; retry yo'q.
    await asyncio.gather(*(_one(ad_id) for ad_id in due))


async def group_cleanup_job(bot: Bot) -> None:
    """Har 5 sekundda kechiktirilgan tozalash; kelajakdagi postlarni ushlamaydi."""
    await process_due_cleanup(bot)


async def counter_notice_cleanup_job(bot: Bot) -> None:
    """Har sekundda sanoqchining 15 soniyalik guruh izohlarini o'chir."""
    await process_due_notices(bot)


async def counter_job(bot: Bot) -> None:
    """Tasdiqlangan yangi a'zoni muddatidan keyin bir marta hisoblash."""
    await process_due(bot)
    await process_restrictions(bot)


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
                    | (GroupSettings.cleaner_enabled.is_(True))
                    | (GroupSettings.counter_enabled.is_(True)),
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
        r1 = await session.execute(delete(ErrorLog).where(
            ErrorLog.created_at < log_cutoff, ErrorLog.resolved_at.is_not(None),
        ))
        r2 = await session.execute(delete(PostLog).where(PostLog.created_at < post_cutoff))
        # Bepul post jurnali pulliknikidek cheklangan; noma'lum/sending
        # natijalarni admin tekshiruvigacha hech qachon avtomatik o'chirmaymiz.
        r_free = await session.execute(delete(FreePostLog).where(
            FreePostLog.created_at < post_cutoff,
            FreePostLog.status.in_({"sent", "skipped", "retry", "error"}),
        ))
        r3 = await session.execute(delete(CleanupLog).where(CleanupLog.created_at < cleanup_cutoff))
        r4 = await session.execute(delete(GroupMessageAction).where(
            GroupMessageAction.created_at < log_cutoff,
            GroupMessageAction.status.in_({"done", "failed", "skipped", "sending"}),
        ))
        r5 = await session.execute(delete(Violation).where(Violation.created_at < log_cutoff))
        r6 = await session.execute(delete(CounterMessageCheck).where(
            CounterMessageCheck.created_at < log_cutoff,
            CounterMessageCheck.status.in_({"dry_run", "deleted", "failed", "skipped"}),
        ))
        r7 = await session.execute(delete(CounterJoinRequest).where(
            CounterJoinRequest.expires_at < now,
        ))
        await session.execute(update(Restriction).where(
            Restriction.kind == "mute", Restriction.is_active.is_(True),
            Restriction.until_at <= now,
        ).values(is_active=False, lifted_at=now))

    logger.info(
        "Retention: error_log -{}, post_log -{}, bepul_post_log -{}, cleanup_log -{}, "
        "xabar amallari -{}, qoidabuzarliklar -{}, sanoqchi xabarlari -{}, join request -{}",
        r1.rowcount, r2.rowcount, r_free.rowcount, r3.rowcount, r4.rowcount,
        r5.rowcount, r6.rowcount, r7.rowcount,
    )


async def daily_stats_job() -> None:
    """Lokal kechagi kun: umumiy + har bir guruh, faqat tasdiqlangan cheklar."""
    async with session_scope() as session:
        tz = await report_service.report_timezone(session)
        yesterday = utcnow().astimezone(tz).date() - timedelta(days=1)
        count = await report_service.rollup_day(session, yesterday, tz)
    logger.info("Kunlik statistika: {} ({:d} qator)", yesterday, count)


async def broadcast_tick_job(bot: Bot) -> None:
    """Yuborishdan oldin manzil holati va global switch qayta tekshiriladi."""
    try:
        delivered = await broadcast_service.deliver_tick(bot)
        if delivered:
            logger.debug("Broadcast tick: {} ta manzil ishlangan", delivered)
    except Exception as exc:
        logger.exception("Broadcast job xatosi: {}", exc)
        await save_error(None, "broadcast", f"{type(exc).__name__}: {exc}", exc=exc)


async def referral_bonus_job() -> None:
    """Shart bajarilgan, lekin hali faol obunasi bo'lmagan referallarni yakunlash."""
    async with session_scope() as session:
        credited = await referral_service.process_pending(session)
    if credited:
        logger.info("Referal bonusi berildi: {}", credited)


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
                yordam=escape_html(str(support)),
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

            text = await text_service.get("seller.subscription_expired", yordam=escape_html(str(support)))
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
    "counter_job",
    "counter_notice_cleanup_job",
    "daily_stats_job",
    "expire_subscriptions_job",
    "heartbeat_job",
    "posting_tick_job",
    "retention_job",
    "rights_check_job",
    "subscription_reminders_job",
]
