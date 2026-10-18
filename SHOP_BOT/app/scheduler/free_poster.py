"""Bepul suratli e'lonlar: har user+guruh taymeri, umumiy texnik limit.

Claim tranzaksiyasi COMMIT → Telegram → natija COMMIT. Uzilgan `sending`
hech qachon takrorlanmaydi: guruh xato pauzasiga tushadi va admin tekshiradi.
Eski pullik navbatning 30 daqiqalik soati bepul taymerga ta'sir qilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import (
    ErrorLog,
    FreeAd,
    FreePostLog,
    Group,
    GroupRotation,
    PostLog,
)
from app.services import free_ad_service as free_ads
from app.services.group_service import pause_group
from app.services.notify import notify_admins
from app.services.posting_limiter import posting_limiter
from app.services.posting_service import local_day, timezone_for
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow

LEASE = timedelta(minutes=5)


@dataclass(frozen=True)
class FreeClaim:
    ad_id: int
    group_id: int
    chat_id: int
    user_id: int
    log_id: int
    revision: int
    lease_until: datetime


async def _group_tz(session: AsyncSession, group: Group) -> ZoneInfo:
    assert group.settings is not None
    name = group.settings.timezone or str(await settings_service.get(
        "timezone", "Asia/Tashkent", session))
    return timezone_for(name)


async def claim_one(session: AsyncSession, ad_id: int, now: datetime) -> FreeClaim | None:
    """Guruh qatorini qulflash: paid/free va ikki free worker bir-birini kutadi."""
    gid = (await session.execute(select(FreeAd.group_id).where(
        FreeAd.id == ad_id, FreeAd.desired_running.is_(True),
        FreeAd.review_status == "approved", FreeAd.admin_paused.is_(False),
        FreeAd.next_post_at <= now,
    ))).scalar_one_or_none()
    if gid is None:
        return None
    rotation = (await session.execute(select(GroupRotation).where(
        GroupRotation.group_id == gid,
    ).with_for_update(skip_locked=True))).scalar_one_or_none()
    if rotation is None:
        return None
    ad = (await session.execute(select(FreeAd).where(FreeAd.id == ad_id)
                                .with_for_update(skip_locked=True))).scalar_one_or_none()
    if (ad is None or not ad.desired_running or ad.admin_paused
            or ad.review_status != "approved"
            or not ad.approved_photo_id or not ad.approved_caption or ad.next_post_at is None
            or ensure_aware(ad.next_post_at) > now):
        return None
    group = await free_ads.group_for(session, gid)
    if (group is None or not free_ads.ready_group(group)
            or not await settings_service.get("free_plan_enabled", True, session)):
        return None
    access = await free_ads.entitlement(session, ad.user_id, gid)
    if access is None or ensure_aware(access.expires_at) <= now:
        ad.next_post_at = None
        return None
    if (await session.execute(select(PostLog.id).where(
            PostLog.group_id == gid, PostLog.status == "sending",
    ).limit(1))).scalar_one_or_none() is not None:
        return None
    if (await session.execute(select(FreePostLog.id).where(
            FreePostLog.group_id == gid, FreePostLog.status == "sending",
    ).limit(1))).scalar_one_or_none() is not None:
        return None
    old = ad.next_post_at
    lease_until = now + LEASE
    # SQLite testda FOR UPDATE yo'q; shartli UPDATE ikkinchi claim'ni bloklaydi.
    row = await session.execute(update(FreeAd).where(
        FreeAd.id == ad.id, FreeAd.next_post_at == old,
        FreeAd.desired_running.is_(True), FreeAd.admin_paused.is_(False),
        FreeAd.review_status == "approved",
    ).values(next_post_at=lease_until).execution_options(synchronize_session=False))
    if row.rowcount != 1:
        return None
    log = FreePostLog(free_ad_id=ad.id, group_id=gid, user_id=ad.user_id, status="sending")
    session.add(log)
    await session.flush()
    return FreeClaim(ad.id, gid, group.tg_chat_id, ad.user_id, log.id,
                     ad.revision, lease_until)


async def _preflight(bot: Bot, claim: FreeClaim, now: datetime) -> tuple[str, str, bool] | None:
    if (not await settings_service.is_feature_enabled_fresh("posting")
            or not await settings_service.get("free_plan_enabled", True)):
        return None
    async with session_scope() as session:
        ad = await session.get(FreeAd, claim.ad_id)
        log = await session.get(FreePostLog, claim.log_id)
        group = await free_ads.group_for(session, claim.group_id)
        access = await free_ads.entitlement(session, claim.user_id, claim.group_id)
        if (log is None or log.status != "sending" or ad is None
                or not ad.desired_running or ad.admin_paused or ad.review_status != "approved"
                or ad.revision != claim.revision
                or not ad.approved_photo_id or not ad.approved_caption
                or ensure_aware(ad.next_post_at) != claim.lease_until
                or group is None or not free_ads.ready_group(group)
                or access is None or ensure_aware(access.expires_at) <= now
                or await free_ads.is_blocked(session, claim.user_id)):
            return None
        assert group.settings is not None
        photo, caption, protect = ad.approved_photo_id, ad.approved_caption, group.settings.protect_content
    return (photo, caption, protect) if await free_ads.is_member(bot, claim.chat_id, claim.user_id) else None


async def _finish(session: AsyncSession, claim: FreeClaim, now: datetime,
                  *, message_id: int | None = None, error: str | None = None,
                  status: str = "sent", retry_after: int | None = None) -> None:
    log = await session.get(FreePostLog, claim.log_id)
    ad = await session.get(FreeAd, claim.ad_id)
    group = await session.get(Group, claim.group_id)
    if log is None or log.status != "sending":
        # Telegram xabari bor, lekin jurnal yozilmagan: xato haqida yozamiz,
        # avtomatik postni qayta boshlamaymiz.
        if group and group.is_active:
            await pause_group(session, group, reason="error")
        session.add(ErrorLog(source="free_poster", group_id=claim.group_id,
                             user_id=claim.user_id, is_critical=True,
                             message=f"Free log o'zgargan: #{claim.log_id}, telegram={message_id}"))
        return
    log.status = status
    log.error = error[:2000] if error else None
    if status == "sent" and message_id is not None:
        log.message_id = message_id
        log.sent_at = now
        if ad is not None:
            ad.post_count += 1
            ad.last_post_at = now
        if group is None or group.rotation is None or group.settings is None:
            log.status = "uncertain"
            log.error = "Telegram yubordi, lekin guruh sozlamalari o'zgargan: qo'lda tekshiring"
            session.add(ErrorLog(source="free_poster", group_id=claim.group_id,
                                 user_id=claim.user_id, is_critical=True, message=log.error))
        else:
            rotation = (await session.execute(select(GroupRotation).where(
                GroupRotation.group_id == group.id,
            ).with_for_update())).scalar_one_or_none()
            if rotation is not None:
                today = local_day(now, await _group_tz(session, group))
                rotation.today_count = (rotation.today_count if rotation.today_date == today else 0) + 1
                rotation.today_date = today
                rotation.last_post_at = now
    if ad is not None and ensure_aware(ad.next_post_at) == claim.lease_until:
        access = await free_ads.entitlement(session, ad.user_id, ad.group_id)
        if (status == "sent" and ad.desired_running and not ad.admin_paused
                and ad.review_status == "approved"
                and access and ensure_aware(access.expires_at) > now and group
                and free_ads.ready_group(group)):
            ad.next_post_at = now + await free_ads.interval(session)
        elif status == "retry" and retry_after is not None:
            ad.next_post_at = now + timedelta(seconds=max(60, retry_after))
        elif status == "skipped" and group and free_ads.ready_group(group) and not ad.admin_paused:
            ad.next_post_at = now + await free_ads.interval(session)
        else:
            ad.next_post_at = None
    if status in {"error", "uncertain"}:
        if ad is not None:
            ad.desired_running = False
            ad.next_post_at = None
        if group is not None and group.is_active and status == "uncertain":
            await pause_group(session, group, reason="error")
            group.last_error = (error or "Bepul post natijasi noma'lum")[:500]
        session.add(ErrorLog(source="free_poster", group_id=claim.group_id,
                             user_id=claim.user_id, message=(error or "Yuborishda xato")[:4000],
                             is_critical=status == "uncertain"))


async def post_one(bot: Bot, ad_id: int) -> None:
    """Bir reklamachi due bo'lsa yuborish; network DB tranzaksiyasidan tashqarida."""
    async with session_scope() as session:
        claim = await claim_one(session, ad_id, utcnow())
    if claim is None:
        return
    # Telegram limiting kutish bilan user Stop/admin pauza orasidagi poyga:
    # yuborish oldidan qayta tekshirish, ammo in-flight Telegram xabarini
    # qaytarish imkoni yo'q. Stop keyingi postni albatta to'xtatadi.
    await posting_limiter.acquire(claim.chat_id)
    now = utcnow()
    payload = await _preflight(bot, claim, now)
    if payload is None:
        async with session_scope() as session:
            await _finish(session, claim, now, status="skipped", error="Shart yoki switch o'zgardi")
        return
    photo, caption, protect = payload
    try:
        msg = await bot.send_photo(claim.chat_id, photo, caption=caption,
                                   parse_mode=None, protect_content=protect)
    except TelegramRetryAfter as exc:
        async with session_scope() as session:
            await _finish(session, claim, utcnow(), status="retry",
                          error=f"FloodWait {exc.retry_after}s", retry_after=exc.retry_after)
        return
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        # API ma'lum rad etdi — yuborilmadi, lekin qayta-qayta urinish yo'q.
        async with session_scope() as session:
            await _finish(session, claim, utcnow(), status="error", error=str(exc))
            if isinstance(exc, TelegramForbiddenError):
                group = await session.get(Group, claim.group_id)
                if group and group.is_active:
                    await pause_group(session, group, reason="no_rights")
        await notify_admins(bot, f"⚠️ Bepul e'lon #{claim.ad_id}: Telegram rad etdi; guruh #{claim.group_id}. {str(exc)[:150]}")
        return
    except Exception as exc:
        # Timeout/tarmoq: server postni olgan bo'lishi mumkin. Takrorlamaymiz.
        async with session_scope() as session:
            await _finish(session, claim, utcnow(), status="uncertain",
                          error=f"Telegram natijasi noma'lum: {type(exc).__name__}: {exc}")
        logger.exception("Bepul post natijasi noma'lum, ad={}: {}", claim.ad_id, exc)
        await notify_admins(bot, f"🚨 Bepul e'lon #{claim.ad_id} yuborilgan bo'lishi mumkin; "
                                 f"guruh #{claim.group_id} pauzada. Qo'lda tekshiring.")
        return
    async with session_scope() as session:
        await _finish(session, claim, utcnow(), message_id=msg.message_id)


async def recover_stale(bot: Bot, *, now: datetime | None = None) -> int:
    """Restartda 5 minutdan eski sending — natija noma'lum; retry YO'Q."""
    now = now or utcnow()
    async with session_scope() as session:
        ids = list((await session.execute(select(FreePostLog.id).where(
            FreePostLog.status == "sending", FreePostLog.created_at <= now - LEASE,
        ).order_by(FreePostLog.id).limit(100))).scalars())
    alerts = []
    for log_id in ids:
        async with session_scope() as session:
            log = (await session.execute(select(FreePostLog).where(
                FreePostLog.id == log_id, FreePostLog.status == "sending",
            ).with_for_update(skip_locked=True))).scalar_one_or_none()
            if log is None:
                continue
            log.status = "uncertain"
            log.error = "Poster uzildi: Telegram qabul qilgan-qilmagani noma'lum; qayta yuborilmadi"
            ad = await session.get(FreeAd, log.free_ad_id) if log.free_ad_id else None
            if ad:
                ad.desired_running = False
                ad.next_post_at = None
            group = await session.get(Group, log.group_id) if log.group_id else None
            if group and group.is_active:
                await pause_group(session, group, reason="error")
                group.last_error = log.error
            session.add(ErrorLog(source="free_poster", group_id=log.group_id,
                                 user_id=log.user_id, message=log.error,
                                 is_critical=True))
            alerts.append((log.id, log.group_id))
    for log_id, gid in alerts:
        await notify_admins(bot, f"🚨 Bepul post #{log_id}: guruh #{gid} pauzada. "
                                 "Natija noma'lum, avtomatik takror yo'q; qo'lda tekshiring.")
    return len(alerts)


async def rebase_paused(now: datetime, *, limit: int = 200) -> None:
    """Global pauza vaqtida eskirgan due qarzga aylanmasin (muddat uzaymaydi)."""
    async with session_scope() as session:
        ids = await free_ads.due_ids(session, now, limit=limit)
        for ad_id in ids:
            ad = await session.get(FreeAd, ad_id)
            group = await session.get(Group, ad.group_id) if ad else None
            access = await free_ads.entitlement(session, ad.user_id, ad.group_id) if ad else None
            if ad and ad.next_post_at and ensure_aware(ad.next_post_at) <= now:
                ad.next_post_at = (now + await free_ads.interval(session) if group and group.settings
                                   and access and ensure_aware(access.expires_at) > now else None)
