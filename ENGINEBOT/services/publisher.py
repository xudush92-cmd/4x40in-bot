"""
services/publisher.py — kanalga e'lon yuborish servisi (V1).

V1 yangiliklar:
- Erkin matn (raw_text) + ixtiyoriy rasmlar (photos JSON list)
- 1 rasm: send_photo + caption
- 2-3 rasm: send_media_group (album)
- POST_CREATED event listener (yangi e'lon → darhol kanalga)
- Per-poster rotation publisher orqali ishlaydi (scheduler chaqiradi)

QULAY XUSUSIYATLARI:
────────────────────
- Yangi e'lon → darhol kanalga (FIRST_POST_IMMEDIATE bo'lsa)
- Telegram FloodWait — kutib qaytadan urinish (max 3 retry)
- Kanal yo'q yoki bot admin emas → user va tenantga xabar
- message_id DB'ga saqlanadi (rotation va o'chirish uchun)
- refresh_post_in_channel — e'lon tahrirlanganda kanaldagi xabarni yangilash
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)

from config import DEFAULT_TZ_OFFSET, PostStatus, Rotation
from core import audit_log, database as db, notifier
from core.categories import get_category_label
from core.event_bus import Events, bus
from utils import formatters as fmt
from utils import logger as log_mod
from utils.formatters import wrap_announcement

logger = log_mod.get_logger("services.publisher")

if TYPE_CHECKING:
    from aiogram import Bot


# ─────────────────────────────────────────────────────────────────────
# TZ cache (har chaqiruvda yangi obj yaratilmasligi uchun)
# ─────────────────────────────────────────────────────────────────────
_UZ_TZ = timezone(timedelta(hours=DEFAULT_TZ_OFFSET))

# FloodWait retry limit — cheksiz retry qilmaslik uchun
_MAX_FLOOD_RETRIES = 3


# ─────────────────────────────────────────────────────────────────────
# Bot referensi (main.py'da set_bot orqali oʻrnatiladi)
# ─────────────────────────────────────────────────────────────────────
_bot: "Bot | None" = None


def set_bot(bot: "Bot") -> None:
    """main.py'dan bot instance'ni shu modulga uzatish."""
    global _bot
    _bot = bot


def _ensure_bot() -> "Bot":
    if _bot is None:
        raise RuntimeError("publisher: bot referensi sozlanmagan (set_bot chaqiring).")
    return _bot


# ─────────────────────────────────────────────────────────────────────
# Event listener: yangi post yaratildi
# ─────────────────────────────────────────────────────────────────────
@bus.on(Events.POST_CREATED)
async def on_post_created(data: dict) -> None:
    """Yangi post — agar FIRST_POST_IMMEDIATE bo'lsa darhol kanalga.

    EventBus o'zi alohida task'da chaqiradi (fire-and-forget),
    shuning uchun bu yerda yana create_task qilish shart emas.
    """
    if not Rotation.FIRST_POST_IMMEDIATE:
        return  # scheduler chiqaradi
    post_id = data.get("post_id")
    tenant_id = data.get("tenant_id")
    if not post_id or not tenant_id:
        return

    # To'g'ridan-to'g'ri await — event_bus o'zi background'da ishlaydi
    await publish_post(post_id, tenant_id, is_new=True)


# ─────────────────────────────────────────────────────────────────────
# Asosiy publish funksiyasi
# ─────────────────────────────────────────────────────────────────────
async def publish_post(
    post_id: int,
    tenant_id: int,
    *,
    is_new: bool = False,
    is_edit: bool = False,
    _retry_count: int = 0,
) -> bool:
    """
    Eʼlonni kanalga yuborish (yoki yangilash — rotation).

    Args:
        post_id      : DB'dagi e'lon ID
        tenant_id    : tenant ID (izolyatsiya filtri uchun)
        is_new       : True — yangi e'lon (FIRST_POST_IMMEDIATE)
        is_edit      : True — tahrir natijasi (rotation_count yangilanmaydi,
                       "Aylandi" badge ko'rsatilmaydi)
        _retry_count : ichki ishlatuvchi (FloodWait recursion limiti)

    Returns: True — muvaffaqiyatli, False — xato.
    """
    bot = _ensure_bot()

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        logger.warning(f"publish: post #{post_id} topilmadi")
        return False

    if post.get("status") in (PostStatus.DELETED, PostStatus.EXPIRED):
        return False

    channel_id = int(post["channel_id"])
    raw_text = post.get("raw_text") or ""
    photos = post.get("photos") or []
    if isinstance(photos, str):
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            photos = json.loads(photos)
    if not isinstance(photos, list):
        photos = []

    rotation_count = int(post.get("rotation_count", 0))
    cat_code = post.get("category_code") or ""

    # E'lonning to'liq matni: kategoriya + raw_text + karkas
    body_lines = []
    if cat_code:
        body_lines.append(f"<b>{get_category_label(cat_code)}</b>")
        body_lines.append("")
    body_lines.append(fmt.esc(raw_text))

    # Poster ma'lumoti (ism + telefon)
    poster = await db.get_user(tenant_id, post["user_id"])
    if poster:
        if poster.get("full_name"):
            body_lines.append("")
            body_lines.append(f"👤 {fmt.esc(poster['full_name'])}")
        if poster.get("phone"):
            body_lines.append(f"📞 <code>{fmt.esc(poster['phone'])}</code>")

    body = "\n".join(body_lines)
    full_text = wrap_announcement(
        body,
        is_new=is_new,
        is_rotated=(not is_new) and (not is_edit),
        rotation_count=rotation_count,
    )

    try:
        old_message_id = post.get("message_id")

        if photos:
            # Rasm bilan
            new_message_id = await _send_with_photos(
                bot, channel_id, full_text, photos
            )
        else:
            sent = await bot.send_message(
                chat_id=channel_id,
                text=full_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            new_message_id = sent.message_id

        # Eski message'ni o'chirish (rotation bo'lsa)
        if old_message_id and not is_new:
            with contextlib.suppress(TelegramAPIError):
                await bot.delete_message(channel_id, int(old_message_id))

        # DB yangilash
        now_iso = datetime.now(_UZ_TZ).isoformat()

        await db.update_announcement(
            post_id, tenant_id,
            message_id=new_message_id,
            last_rotated_at=now_iso,
            status=PostStatus.ACTIVE,
        )

        if not is_new and not is_edit:
            await db.increment_announcement_counter(
                post_id, tenant_id, "rotation_count"
            )

        await audit_log.log_system_event(
            action="post_edited_in_channel" if is_edit else "post_published",
            tenant_id=tenant_id,
            target_type="announcement",
            target_id=post_id,
            channel_id=channel_id,
            is_new=is_new,
            is_edit=is_edit,
            message_id=new_message_id,
        )

        if is_new:
            await notifier.notify_post_published(
                user_id=int(post["user_id"]), tenant_id=tenant_id, post_id=post_id
            )
            await bus.emit(
                Events.POST_PUBLISHED,
                {
                    "post_id": post_id,
                    "tenant_id": tenant_id,
                    "message_id": new_message_id,
                },
            )

        logger.info(
            f"published #{post_id} → channel {channel_id} mid={new_message_id} "
            f"(new={is_new}, edit={is_edit}, rot={rotation_count}, photos={len(photos)})"
        )
        return True

    except Exception as e:
        return await _handle_publish_error(
            e, post_id, tenant_id, channel_id, is_new, is_edit, _retry_count
        )


async def _send_with_photos(
    bot: "Bot", channel_id: int, caption: str, photos: list[str]
) -> int:
    """
    Rasm(lar) bilan e'lon yuborish.

    1 ta rasm — send_photo + caption
    2-10 ta rasm — send_media_group (album), caption faqat birinchisida
    """
    from aiogram.types import InputMediaPhoto

    if len(photos) == 1:
        sent = await bot.send_photo(
            chat_id=channel_id,
            photo=photos[0],
            caption=caption,
            parse_mode="HTML",
        )
        return sent.message_id

    media = []
    for i, photo in enumerate(photos):
        if i == 0:
            media.append(InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"))
        else:
            media.append(InputMediaPhoto(media=photo))

    sent_messages = await bot.send_media_group(chat_id=channel_id, media=media)
    if sent_messages:
        return sent_messages[0].message_id
    raise RuntimeError("send_media_group bo'sh javob qaytardi")


async def _handle_publish_error(
    e: Exception,
    post_id: int,
    tenant_id: int,
    channel_id: int,
    is_new: bool,
    is_edit: bool = False,
    retry_count: int = 0,
) -> bool:
    """Publish xato'larini boshqarish (FloodWait, Forbidden, va h.k.).

    FloodWait holatida max _MAX_FLOOD_RETRIES marta urinib ko'radi —
    cheksiz recursion oldini olish uchun.
    """
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
    )

    if isinstance(e, TelegramRetryAfter):
        if retry_count >= _MAX_FLOOD_RETRIES:
            logger.error(
                f"FloodWait max retries ({_MAX_FLOOD_RETRIES}) reached for post #{post_id}"
            )
            await audit_log.log_system_event(
                action="post_publish_failed",
                tenant_id=tenant_id, target_id=post_id, level="error",
                reason="flood_wait_max_retries",
            )
            return False

        wait = int(getattr(e, "retry_after", 30)) + 1
        logger.warning(
            f"FloodWait {wait}s for post #{post_id}, "
            f"retry {retry_count + 1}/{_MAX_FLOOD_RETRIES}..."
        )
        await asyncio.sleep(wait)
        return await publish_post(
            post_id, tenant_id, is_new=is_new, is_edit=is_edit, _retry_count=retry_count + 1
        )

    if isinstance(e, TelegramForbiddenError):
        logger.error(f"forbidden #{post_id}: {e}")
        await db.update_announcement(post_id, tenant_id, status=PostStatus.PAUSED)
        await audit_log.log_system_event(
            action="post_publish_failed",
            tenant_id=tenant_id, target_id=post_id, level="error",
            reason="forbidden", channel_id=channel_id,
        )
        await notifier.notify_warning(
            user_id=tenant_id, tenant_id=tenant_id,
            title="Botning kanaldagi huquqi yo'q",
            message=(
                f"⚠️ Bot kanal <code>{channel_id}</code> ga yoza olmadi.\n"
                "Iltimos, botni admin sifatida qoʻshing."
            ),
        )
        return False

    if isinstance(e, TelegramBadRequest):
        logger.error(f"bad request #{post_id}: {e}")
        await audit_log.log_system_event(
            action="post_publish_failed",
            tenant_id=tenant_id, target_id=post_id, level="error",
            reason=str(e),
        )
        return False

    # Boshqa xato
    logger.error(f"publish error #{post_id}: {type(e).__name__}: {e}")
    await audit_log.log_system_event(
        action="post_publish_failed",
        tenant_id=tenant_id, target_id=post_id, level="error",
        reason=f"{type(e).__name__}: {e}",
    )
    return False


# ─────────────────────────────────────────────────────────────────────
# E'lonni kanaldan o'chirish
# ─────────────────────────────────────────────────────────────────────
async def remove_post_from_channel(post_id: int, tenant_id: int) -> bool:
    """E'lonni kanaldan va DB'dan o'chirish."""
    bot = _ensure_bot()
    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        return False

    channel_id = int(post["channel_id"])
    message_id = post.get("message_id")

    if message_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(channel_id, int(message_id))

    await db.update_announcement(
        post_id, tenant_id, status=PostStatus.DELETED, message_id=None
    )
    return True


# ─────────────────────────────────────────────────────────────────────
# E'lonni kanaldagi xabarni yangilash (post tahrirlanganda)
# ─────────────────────────────────────────────────────────────────────
async def refresh_post_in_channel(post_id: int, tenant_id: int) -> bool:
    """
    Tahrirlangan e'lonni kanalda yangilash.

    Strategiya:
    1. Eski xabar bor bo'lsa — uni o'chirib, yangisini yuborish
       (Telegram media_group'da edit_message_caption ishlamaydi —
       shuning uchun delete + send eng ishonchli yo'l).
    2. Status ACTIVE bo'lmagan post — yangilanmaydi.
    3. Yangi message_id DB'ga saqlanadi.

    Returns: True — yangilandi, False — xato yoki status mos emas.
    """
    bot = _ensure_bot()
    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        return False

    # Faqat aktiv yoki paused post'larni yangilaymiz
    if post.get("status") not in (PostStatus.ACTIVE, PostStatus.PAUSED):
        return False

    channel_id = int(post["channel_id"])
    old_message_id = post.get("message_id")

    # Eski xabarni o'chirish
    if old_message_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(channel_id, int(old_message_id))

    # Yangisini yuborish (publish_post is_edit=True — tahrir, rotation EMAS)
    return await publish_post(post_id, tenant_id, is_new=False, is_edit=True)
