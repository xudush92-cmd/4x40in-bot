"""Tasdiqlanadigan broadcast: manzillar snapshot'i, audit va xavfsiz yetkazish.

Telegram tarmoq xatosidan keyin xabar borgan-bormagani noma'lum bo'lishi mumkin:
`running` yozuvi restartdan keyin `uncertain`ga o'tadi, avtomatik takrorlanmaydi.
Faqat botga shaxsiy /start bosgan, bloklanmagan va voz kechmagan odamlar olinadi.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import ActionLog, Admin, Broadcast, BroadcastTarget, Seller, User
from app.redis_client import redis_manager
from app.services.posting_limiter import posting_limiter
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow

_TARGETS = {"all", "sellers", "admins"}
_RATE_LUA = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local next_at = tonumber(redis.call('GET', KEYS[1]) or 0)
if next_at > now then return next_at - now end
redis.call('SET', KEYS[1], now + tonumber(ARGV[1]), 'PX', 60000)
return 0
"""


class BroadcastError(ValueError):
    """Tugma/so'rovni qayta ko'rsatish mumkin bo'lgan xato."""


class _BroadcastLimiter:
    """Redis bo'lsa barcha poster processlar bo'ylab bir xil <=25 msg/s.

    Xotira fallback'i faqat dev/test rejimida. Prod'da Redis yo'qolsa,
    tarqatish to'xtaydi — yakka process limiti ko'p processda ishlamaydi.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self, rate: int) -> None:
        gap_ms = (1000 + rate - 1) // rate
        while True:
            client = redis_manager.client if redis_manager.available else None
            if client is not None:
                try:
                    wait = int(await client.eval(_RATE_LUA, 1, "shopbot:broadcast:rate", gap_ms)) / 1000
                except Exception as exc:
                    if not get_settings().dev_mode:
                        raise BroadcastError("Redis limiter ishlamayapti: broadcast pauzada") from exc
                    logger.warning("Broadcast limiter Redis xatosi; dev lokal rejim: {}", exc)
                    wait = await self._local_wait(gap_ms / 1000)
            elif get_settings().dev_mode:
                wait = await self._local_wait(gap_ms / 1000)
            else:
                raise BroadcastError("Redis ishlamayapti: broadcast xavfsizlik uchun pauzada")
            if wait <= 0:
                return
            await asyncio.sleep(wait)

    async def _local_wait(self, gap: float) -> float:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                return self._next - now
            self._next = now + gap
            return 0.0


broadcast_limiter = _BroadcastLimiter()


def _eligible_stmt(target: str):
    if target not in _TARGETS:
        raise BroadcastError("Manzil guruhi noma'lum.")
    stmt = select(User.user_id).where(
        User.private_started_at.is_not(None), User.is_blocked.is_(False),
        User.broadcast_opt_out.is_(False),
    )
    if target == "sellers":
        stmt = stmt.join(Seller, Seller.user_id == User.user_id).where(Seller.status != "blocked")
    elif target == "admins":
        stmt = stmt.join(Admin, Admin.user_id == User.user_id).where(Admin.is_active.is_(True))
    return stmt.distinct().order_by(User.user_id)


async def eligible_count(session: AsyncSession, target: str) -> int:
    query = _eligible_stmt(target).order_by(None).subquery()
    return int((await session.execute(select(func.count()).select_from(query))).scalar_one())


async def create_draft(session: AsyncSession, actor_id: int, target: str,
                       text: str | None, photo_file_id: str | None = None) -> Broadcast:
    if target not in _TARGETS:
        raise BroadcastError("Manzil guruhi noma'lum.")
    raw = (text or "").strip()
    if not raw and not photo_file_id:
        raise BroadcastError("Matn yoki rasm yuboring.")
    # Bot HTML rejimida. Matn doim literal: admin tasodifan buzilgan HTML
    # yuborsa butun navbat yiqilmaydi, ixtiyoriy teglarga ruxsat yo'q.
    safe = escape(raw, quote=False)
    limit = 1024 if photo_file_id else 4096
    if len(safe) > limit:
        raise BroadcastError(f"Matn {limit} belgidan oshmasin (HTML belgilari hisobga olinadi).")
    if photo_file_id and len(photo_file_id) > 255:
        raise BroadcastError("Rasmning Telegram file ID qiymati juda uzun.")
    draft = Broadcast(admin_id=actor_id, target=target, text=safe or None,
                      photo_file_id=photo_file_id, status="draft")
    session.add(draft)
    await session.flush()
    return draft


async def confirm(session: AsyncSession, broadcast_id: int, actor_id: int) -> Broadcast:
    """Previewdan keyin bitta atomar amal: manzillarni muzlatish va navbatlash."""
    row = (await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id)
                                 .with_for_update())).scalar_one_or_none()
    if row is None or row.admin_id != actor_id or row.status != "draft":
        raise BroadcastError("Bu qoralama allaqachon tasdiqlangan yoki sizga tegishli emas.")
    # Manzillar faqat birinchi shaxsiy /start qilganlarga yuboriladi. Katta
    # auditoriyada ORM xotirasini shishirmaslik uchun har sahifada flush qilamiz.
    count, after = 0, 0
    while True:
        ids = (await session.execute(_eligible_stmt(row.target).where(User.user_id > after)
                                     .limit(500))).scalars().all()
        if not ids:
            break
        for user_id in ids:
            session.add(BroadcastTarget(broadcast_id=row.id, user_id=user_id, status="pending"))
        await session.flush()
        count += len(ids)
        after = ids[-1]
    if not count:
        raise BroadcastError("Hozircha /start bosgan mos qabul qiluvchi yo'q.")
    row.total = count
    row.status = "queued"
    session.add(ActionLog(actor_id=actor_id, action="broadcast_confirm", entity="broadcast",
                          entity_id=row.id, after={"target": row.target, "total": count}))
    await session.flush()
    return row


async def change_status(session: AsyncSession, broadcast_id: int, actor_id: int,
                        action: str) -> Broadcast:
    row = (await session.execute(select(Broadcast).where(Broadcast.id == broadcast_id)
                                 .with_for_update())).scalar_one_or_none()
    if row is None:
        raise BroadcastError("Xabar topilmadi.")
    if action == "pause" and row.status in {"queued", "sending"}:
        row.status = "paused"
    elif action == "resume" and row.status == "paused":
        row.status = "queued"
    elif action == "cancel" and row.status in {"queued", "sending", "paused"}:
        row.status = "cancelled"
        row.finished_at = utcnow()
    elif action == "resolve" and row.status == "needs_review":
        # Xabarning yetib borgani noma'lum — admin tekshirganidan keyin
        # faqat yopish mumkin, avtomatik resend YO'Q.
        uncertain = (await session.execute(select(BroadcastTarget).where(
            BroadcastTarget.broadcast_id == row.id, BroadcastTarget.status == "uncertain",
        ))).scalars().all()
        for target in uncertain:
            target.status = "failed"
            target.error = "Admin tekshirib, noma'lum natijani yopdi; qayta yuborilmadi."
        row.failed += len(uncertain)
        row.status = "finished"
        row.finished_at = utcnow()
    else:
        raise BroadcastError("Holat o'zgargan; amalni qayta tekshiring.")
    session.add(ActionLog(actor_id=actor_id, action=f"broadcast_{action}", entity="broadcast",
                          entity_id=row.id, after={"status": row.status}))
    await session.flush()
    return row


async def claim_next(session: AsyncSession) -> tuple[int, int, str | None, str | None] | None:
    now = utcnow()
    # Row lock skip_locked: ikkita worker bir foydalanuvchiga xabar yubormaydi.
    stmt = (select(BroadcastTarget, Broadcast)
            .join(Broadcast, Broadcast.id == BroadcastTarget.broadcast_id)
            .where(BroadcastTarget.status == "pending", Broadcast.status.in_(("queued", "sending")),
                   (Broadcast.next_attempt_at.is_(None)) | (Broadcast.next_attempt_at <= now))
            .order_by(Broadcast.id, BroadcastTarget.id).limit(1)
            .with_for_update(of=(BroadcastTarget, Broadcast), skip_locked=True))
    result = (await session.execute(stmt)).first()
    if result is None:
        return None
    target, broadcast = result
    # SQLite FOR UPDATE'ni e'tiborsiz qoldiradi; CAS ko'p processda ham himoya.
    claimed = await session.execute(update(BroadcastTarget).where(
        BroadcastTarget.id == target.id, BroadcastTarget.status == "pending"
    ).values(status="running", claimed_at=now, attempts=BroadcastTarget.attempts + 1))
    if not claimed.rowcount:
        return None
    if broadcast.status == "queued":
        changed = await session.execute(update(Broadcast).where(
            Broadcast.id == broadcast.id, Broadcast.status == "queued",
        ).values(status="sending", started_at=func.coalesce(Broadcast.started_at, now)))
        if not changed.rowcount:  # pauza aynan shu onda bosilgan bo'lishi mumkin
            target.status = "pending"
            await session.flush()
            return None
    await session.flush()
    return target.id, target.user_id, broadcast.text, broadcast.photo_file_id


async def _finish_if_done(session: AsyncSession, row: Broadcast) -> None:
    if row.status in {"cancelled", "paused", "finished"}:
        return
    remaining = (await session.execute(select(func.count()).select_from(BroadcastTarget).where(
        BroadcastTarget.broadcast_id == row.id,
        BroadcastTarget.status.in_(("pending", "running")),
    ))).scalar_one()
    if remaining:
        return
    uncertain = (await session.execute(select(func.count()).select_from(BroadcastTarget).where(
        BroadcastTarget.broadcast_id == row.id, BroadcastTarget.status == "uncertain",
    ))).scalar_one()
    row.status = "needs_review" if uncertain else "finished"
    row.finished_at = None if uncertain else utcnow()


async def record_result(session: AsyncSession, target_id: int, status: str,
                        *, error: str | None = None, message_id: int | None = None,
                        retry_after: int = 0) -> None:
    target = (await session.execute(select(BroadcastTarget).where(
        BroadcastTarget.id == target_id).with_for_update())).scalar_one_or_none()
    if target is None or target.status != "running":
        return  # ishlangan target boshqa joydan takror hisoblanmaydi
    row = await session.get(Broadcast, target.broadcast_id)
    if status == "pending":
        target.status = "pending"
        if retry_after:
            row.next_attempt_at = utcnow() + timedelta(seconds=max(1, retry_after) + 1)
            row.status = "queued" if row.status == "sending" else row.status
    elif status in {"sent", "failed", "uncertain"}:
        target.status = status
        if status == "sent":
            target.sent_at = utcnow()
            target.telegram_message_id = message_id
            await session.execute(update(Broadcast).where(Broadcast.id == row.id)
                                  .values(sent=Broadcast.sent + 1))
        elif status == "failed":
            await session.execute(update(Broadcast).where(Broadcast.id == row.id)
                                  .values(failed=Broadcast.failed + 1))
        target.error = (error or "")[:255] or None
        await session.flush()
        await _finish_if_done(session, row)
    else:
        raise BroadcastError("Yetkazish holati noto'g'ri.")
    await session.flush()


async def reconcile_stale(session: AsyncSession) -> int:
    """Restartdan keyin yuborish natijasi noma'lum: avtomatik resend YO'Q."""
    cutoff = utcnow() - timedelta(minutes=5)
    stale = (await session.execute(select(BroadcastTarget).where(
        BroadcastTarget.status == "running", BroadcastTarget.claimed_at < cutoff,
    ).limit(100))).scalars().all()
    for row in stale:
        row.status = "uncertain"
        row.error = "Worker uzildi: Telegramga yetib borgan-bormagani noma'lum."
    await session.flush()
    for bid in {row.broadcast_id for row in stale}:
        broadcast = await session.get(Broadcast, bid)
        await _finish_if_done(session, broadcast)
    return len(stale)


async def deliver_tick(bot: Bot, *, max_targets: int = 25) -> int:
    """Soatiga emas, sekundiga chaqiriladi; har yuborish oldidan global pauza.

    API xatosida faqat aniq rad (403/400) `failed` bo'ladi; tarmoq/5xx
    `uncertain` — takror xabar yubormaslik uchun qo'lda tekshiriladi.
    """
    async with session_scope() as session:
        await reconcile_stale(session)
    if not await settings_service.is_feature_enabled_fresh("broadcast"):
        return 0
    async with session_scope() as session:
        rate = int(await settings_service.get("broadcast_rate_per_sec", 25, session) or 25)
    rate = max(1, min(25, rate))
    processed = 0
    for _ in range(min(max_targets, rate)):
        if not await settings_service.is_feature_enabled_fresh("broadcast"):
            break
        async with session_scope() as session:
            claim = await claim_next(session)
        if claim is None:
            break
        target_id, user_id, text, photo = claim
        try:
            await broadcast_limiter.acquire(rate)
            await posting_limiter.acquire(user_id)  # poster bilan BIR global 25/s token bucket
            async with session_scope() as session:
                target = await session.get(BroadcastTarget, target_id)
                row = await session.get(Broadcast, target.broadcast_id)
                user = await session.get(User, user_id)
                may_send = row.status in {"queued", "sending"} and bool(
                    not row.next_attempt_at or ensure_aware(row.next_attempt_at) <= utcnow()
                )
                declined = user is None or user.is_blocked or user.broadcast_opt_out
            if not may_send or not await settings_service.is_feature_enabled_fresh("broadcast"):
                async with session_scope() as session:
                    await record_result(session, target_id, "pending")
                break
            if declined:
                async with session_scope() as session:
                    await record_result(session, target_id, "failed", error="Foydalanuvchi bloklangan yoki xabardan chiqqan")
                processed += 1
                continue
            if photo:
                sent = await bot.send_photo(user_id, photo, caption=text, parse_mode="HTML")
            else:
                sent = await bot.send_message(user_id, text or "", parse_mode="HTML")
        except TelegramRetryAfter as exc:
            async with session_scope() as session:
                await record_result(session, target_id, "pending", retry_after=exc.retry_after)
            break
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            async with session_scope() as session:
                await record_result(session, target_id, "failed", error=f"{type(exc).__name__}: {exc}")
        except BroadcastError as exc:
            logger.warning("Broadcast pauza: {}", exc)
            async with session_scope() as session:
                await record_result(session, target_id, "pending")
            break
        except TelegramAPIError as exc:
            async with session_scope() as session:
                await record_result(session, target_id, "uncertain", error=f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            logger.exception("Broadcast tarmoq/ish jarayoni noma'lum xatosi (user={}): {}", user_id, exc)
            async with session_scope() as session:
                await record_result(session, target_id, "uncertain", error=f"{type(exc).__name__}: {exc}")
        else:
            async with session_scope() as session:
                await record_result(session, target_id, "sent", message_id=sent.message_id)
        processed += 1
    return processed


async def opt_out(session: AsyncSession, user: User, *, enabled: bool) -> None:
    user.broadcast_opt_out = enabled
    session.add(ActionLog(actor_id=user.user_id, action="broadcast_opt_out", entity="user",
                          entity_id=user.user_id, after={"disabled": enabled}))
    await session.flush()
