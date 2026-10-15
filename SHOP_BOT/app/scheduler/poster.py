"""Telegram'ga e'lon yuborish (Phase 4).

DB claim commit -> Bot API -> DB natija commit. Qayta yoqilganda yakunlanmagan
`sending` loglar avtomatik TAKRORLANMAYDI, admin tekshirishi uchun pauza qilinadi.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from loguru import logger

from app.constants import MAX_CAPTION_LEN, AdStatus
from app.db.base import session_scope
from app.db.models import Ad, Category, Group
from app.services import posting_service
from app.services.notify import notify_admins
from app.services.posting_limiter import posting_limiter
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.utils.text import escape_html, fmt_amount
from app.utils.time import utcnow


async def _enabled() -> bool:
    return bool(await settings_service.is_feature_enabled("posting")) and not bool(
        await settings_service.get("maintenance_mode", False)
    )


def _clip_html(value: str | None, limit: int) -> str:
    """HTML entity/tag o'rtasidan bo'lmaydi (caption 1024 chegarasi)."""
    result: list[str] = []
    used = 0
    for char in value or "":
        escaped = escape_html(char)
        if used + len(escaped) > limit:
            break
        result.append(escaped)
        used += len(escaped)
    return "".join(result) + ("…" if len(result) < len(value or "") and used < limit else "")


def format_caption(ad: Ad) -> str:
    """Faqat post uchun xavfsiz HTML (modeldagi legacy caption'ni o'zgartirmaydi)."""
    title = _clip_html(ad.title or "E'lon", 380)
    lines = [f"<b>{title}</b>"]
    if ad.price is not None:
        lines.append(f"💰 Narx: <b>{escape_html(fmt_amount(ad.price, ad.currency or 'UZS'))}</b>")
    if ad.contact_type == "phone" and ad.contact_value:
        lines.append("📞 " + _clip_html(ad.contact_value, 48))
    if ad.category and ad.category.name:
        lines.append("#" + _clip_html(ad.category.name.replace(" ", "_"), 170))
    base = "\n".join(lines)
    if ad.description:
        budget = max(0, MAX_CAPTION_LEN - len(base) - 2)
        if budget:
            lines.insert(2 if len(lines) > 1 else 1, "\n" + _clip_html(ad.description, budget))
    return "\n".join(lines)


def contact_markup(ad: Ad) -> InlineKeyboardMarkup | None:
    """Telegram albomda inline tugma qabul qilmaydi; keyingi reply'da chiqadi."""
    value = (ad.contact_value or "").strip()
    if not value:
        return None
    if ad.contact_type == "phone":
        button = InlineKeyboardButton(text="📞 Raqamni nusxalash", copy_text=CopyTextButton(text=value))
    else:
        if value.startswith("@"):
            username = value[1:]
            url = f"https://t.me/{username}" if re.fullmatch(r"[\w]{5,32}", username, re.ASCII) else ""
        else:
            try:
                parsed = urlsplit(value)
                url = value if parsed.scheme in ("https", "http") and parsed.hostname else ""
            except ValueError:
                url = ""
        if not url:
            return None
        button = InlineKeyboardButton(text="👤 Sotuvchi bilan bog'lanish", url=url)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def _load_ad(claim: posting_service.PostingClaim, now: datetime) -> tuple[Ad, bool] | None:
    """Telegram'dan oldin pauza/obuna/o'chirish holatini yana bir marta tekshirish."""
    if not await _enabled():
        return None
    async with session_scope() as session:
        group = await session.get(Group, claim.group_id)
        category = await session.get(Category, claim.category_id)
        ad = await session.get(Ad, claim.ad_id)
        if (group is None or group.settings is None or not group.is_active
                or not group.settings.posting_enabled or not group.bot_is_admin
                or category is None or category.group_id != claim.group_id or not category.is_active
                or ad is None or ad.status != AdStatus.ACTIVE or ad.category_id != category.id):
            return None
        chosen, _ = await posting_service.eligible_ad(session, category, now, force_ad_id=ad.id)
        if chosen is None:
            return None
        return ad, group.settings.protect_content


async def _send_ad(bot: Bot, claim: posting_service.PostingClaim, ad: Ad, protect: bool, ids: list[int]) -> None:
    """Albom (2..10) yoki 1 rasm + reply tugma; har ID saqlanadi."""
    caption = format_caption(ad)
    photos = [photo.file_id for photo in ad.photos]
    first_id: int | None = None
    for start in range(0, len(photos), 10):
        batch = photos[start:start + 10]
        await posting_limiter.acquire(claim.chat_id, len(batch))
        if not await _enabled():
            raise _PostingPaused("Global pauza yoqildi")
        if len(batch) == 1:
            result = await bot.send_photo(
                claim.chat_id, batch[0], caption=caption if start == 0 else None,
                protect_content=protect,
            )
            sent = [result]
        else:
            media = [InputMediaPhoto(media=batch[0], caption=caption if start == 0 else None)]
            media.extend(InputMediaPhoto(media=file_id) for file_id in batch[1:])
            sent = await bot.send_media_group(claim.chat_id, media, protect_content=protect)
        ids.extend(message.message_id for message in sent)
        if first_id is None:
            first_id = sent[0].message_id
    if not photos:
        await posting_limiter.acquire(claim.chat_id)
        if not await _enabled():
            raise _PostingPaused("Global pauza yoqildi")
        sent = await bot.send_message(claim.chat_id, caption, protect_content=protect)
        first_id = sent.message_id
        ids.append(first_id)

    # sendMediaGroup'ga reply_markup berib bo'lmaydi. Aloqa reply xabarda.
    if photos:
        await posting_limiter.acquire(claim.chat_id)
        if not await _enabled():
            raise _PostingPaused("Global pauza yoqildi")
        contact = escape_html(ad.contact_value or "Aloqa ma'lumoti ko'rsatilmagan")
        message = await bot.send_message(
            claim.chat_id,
            f"👤 Sotuvchi bilan bog'lanish: {contact}",
            reply_to_message_id=first_id,
            reply_markup=contact_markup(ad),
            protect_content=protect,
        )
        ids.append(message.message_id)


class _PostingPaused(Exception):
    pass


async def _delete_partial(bot: Bot, claim: posting_service.PostingClaim, ids: list[int]) -> bool:
    """Qisman yuborilgan xabarlarni orqaga qaytarish. Qaytmasa — uncertain."""
    all_deleted = True
    for message_id in ids:
        try:
            await posting_limiter.acquire(claim.chat_id)
            await bot.delete_message(claim.chat_id, message_id)
        except TelegramBadRequest as exc:
            if "message to delete not found" not in str(exc).lower():
                all_deleted = False
        except Exception as exc:
            logger.warning("Yarim postni o'chirib bo'lmadi ({}:{}): {}", claim.chat_id, message_id, exc)
            all_deleted = False
    return all_deleted


async def _notify_problem(bot: Bot, group_id: int, detail: str) -> None:
    async with session_scope() as session:
        group = await session.get(Group, group_id)
        title = group.display if group else str(group_id)
    text = await text_service.get(
        "notify.group_paused", guruh=escape_html(title), sabab=escape_html(detail[:300])
    )
    try:
        await notify_admins(bot, text)
    except Exception as exc:
        logger.warning("Joylash muammosi haqida adminlarga xabar ketmadi: {}", exc)


async def _clean_previous(bot: Bot, claim: posting_service.PostingClaim) -> None:
    async with session_scope() as session:
        posts = await posting_service.old_posts_for_cleanup(session, claim)
        old = [(post.id, list(post.message_ids or [])) for post in posts]
    for post_id, message_ids in old:
        failure: str | None = None
        for message_id in message_ids:
            try:
                await posting_limiter.acquire(claim.chat_id)
                await bot.delete_message(claim.chat_id, message_id)
            except TelegramBadRequest as exc:
                if "message to delete not found" not in str(exc).lower():
                    failure = str(exc)
            except Exception as exc:
                failure = str(exc)
        async with session_scope() as session:
            await posting_service.record_cleanup(session, post_id, deleted=failure is None, error=failure)


async def post_group(
    bot: Bot, group_id: int, *, force_ad_id: int | None = None, now: datetime | None = None
) -> posting_service.PostingResult:
    """Scheduler yoki admin tugmasi uchun bitta guruh/bitta e'lon amali."""
    current = now or utcnow()
    def clock() -> datetime:
        return now or utcnow()  # now faqat deterministik test/simulyatsiya uchun

    if not await _enabled():
        return posting_service.PostingResult("unavailable", "Global pauza yoki texnik rejim yoqilgan.")
    async with session_scope() as session:
        claim, result = await posting_service.claim_post(session, group_id, current, force_ad_id=force_ad_id)
    if claim is None:
        if result.notify:
            await _notify_problem(bot, group_id, result.detail)
        return result

    ids: list[int] = []
    try:
        loaded = await _load_ad(claim, clock())
        if loaded is None:
            async with session_scope() as session:
                await posting_service.abandon_post(session, claim, clock())
            return posting_service.PostingResult("unavailable", "E'lon/guruh holati o'zgargan.", claim.ad_id)
        ad, protect = loaded
        await _send_ad(bot, claim, ad, protect, ids)
        async with session_scope() as session:
            result = await posting_service.finish_post(session, claim, ids, clock())
        if result.status != "sent":
            # DB o'zgargan, lekin Telegram allaqachon yuborgan — qayta urinmaymiz.
            if result.notify:
                await _notify_problem(bot, group_id, result.detail)
            return result
        try:
            await _clean_previous(bot, claim)
        except Exception as exc:  # tozalash xatosi yangi postni buzmasin
            logger.warning("Eski e'lonni tozalash xatosi: {}", exc)
        logger.info("E'lon joylandi: guruh={} ad={} xabarlar={}", group_id, claim.ad_id, ids)
        return result
    except Exception as exc:
        partial_ok = await _delete_partial(bot, claim, ids) if ids else True
        if isinstance(exc, _PostingPaused) and partial_ok:
            async with session_scope() as session:
                await posting_service.abandon_post(session, claim, clock())
            return posting_service.PostingResult("unavailable", str(exc), claim.ad_id)
        # Noma'lum tarmoq/API xatosida Telegram qabul qilgan bo'lishi mumkin,
        # hatto ID qaytmagan bo'lsa ham. Avtomatik retry dublikatga olib keladi.
        known_rejected = isinstance(exc, (TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest))
        uncertain = not partial_ok or (not known_rejected and not isinstance(exc, _PostingPaused))
        retry_after = exc.retry_after if isinstance(exc, TelegramRetryAfter) and not uncertain else None
        forbidden = isinstance(exc, (TelegramForbiddenError, TelegramBadRequest))
        reason = f"{type(exc).__name__}: {exc}"
        async with session_scope() as session:
            result = await posting_service.fail_post(
                session, claim, reason, clock(), retry_after=retry_after,
                forbidden=forbidden, uncertain=uncertain, message_ids=ids if uncertain else None,
            )
        if result.notify:
            await _notify_problem(bot, group_id, result.detail)
        logger.warning("Post xatosi: guruh={} ad={} {}", group_id, claim.ad_id, reason)
        return result
