"""
services/publisher.py — kanalga e'lon yuborish servisi.

Yangi e'lon yaratilganda — uni Telegram kanalga yuboradi.
Event_bus orqali POST_CREATED eventini tinglaydi.

QULAY XUSUSIYATLARI:
────────────────────
- Yangi e'lon → darhol kanalga (delay yo'q)
- Telegram FloodWait — kutib qaytadan urinish
- Kanal yo'q yoki bot admin emas → user va tenantga xabar
- message_id DB'ga saqlanadi (rotation va o'chirish uchun)
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from config import PostStatus
from core import audit_log, database as db, notifier
from core.event_bus import Events, bus
from utils import logger as log_mod
from utils.formatters import wrap_announcement

logger = log_mod.get_logger("services.publisher")

if TYPE_CHECKING:
    from aiogram import Bot


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
    """Yangi post — darhol kanalga yuboramiz."""
    post_id = data.get("post_id")
    tenant_id = data.get("tenant_id")
    if not post_id or not tenant_id:
        return

    # Asosiy ish — alohida task'da, event listener tezroq qaytsin
    asyncio.create_task(publish_post(post_id, tenant_id, is_new=True))


# ─────────────────────────────────────────────────────────────────────
# Asosiy publish funksiyasi
# ─────────────────────────────────────────────────────────────────────
async def publish_post(post_id: int, tenant_id: int, *, is_new: bool = False) -> bool:
    """
    Eʼlonni kanalga yuborish (yoki yangilash).

    Returns: True — muvaffaqiyatli, False — xato.
    """
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
    )

    bot = _ensure_bot()

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        logger.warning(f"publish: post #{post_id} topilmadi")
        return False

    if post.get("status") == PostStatus.DELETED:
        return False

    channel_id = int(post["channel_id"])
    rendered = post.get("rendered_text") or ""
    rotation_count = int(post.get("rotation_count", 0))

    # Karkaslash
    full_text = wrap_announcement(
        rendered,
        is_new=is_new,
        is_rotated=not is_new,
        rotation_count=rotation_count,
    )

    try:
        sent = await bot.send_message(
            chat_id=channel_id,
            text=full_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        new_message_id = sent.message_id

        # Eski message_id bor bo'lsa o'chirish (rotation holatida)
        old_message_id = post.get("message_id")
        if old_message_id and not is_new:
            with contextlib.suppress(Exception):
                await bot.delete_message(channel_id, int(old_message_id))

        # DB'da yangilash
        from datetime import datetime, timedelta, timezone
        from config import DEFAULT_TZ_OFFSET
        now_iso = datetime.now(
            timezone(timedelta(hours=DEFAULT_TZ_OFFSET))
        ).isoformat()

        await db.update_announcement(
            post_id,
            tenant_id,
            message_id=new_message_id,
            last_rotated_at=now_iso,
        )

        if not is_new:
            await db.increment_announcement_counter(
                post_id, tenant_id, "rotation_count"
            )

        await audit_log.log_system_event(
            action="post_published",
            tenant_id=tenant_id,
            target_type="announcement",
            target_id=post_id,
            channel_id=channel_id,
            is_new=is_new,
            message_id=new_message_id,
        )

        if is_new:
            await notifier.notify_post_published(
                user_id=int(post["user_id"]), tenant_id=tenant_id, post_id=post_id
            )
            await bus.emit(
                Events.POST_PUBLISHED,
                {"post_id": post_id, "tenant_id": tenant_id, "message_id": new_message_id},
            )

        logger.info(
            f"published #{post_id} → channel {channel_id} mid={new_message_id} "
            f"(new={is_new}, rot={rotation_count})"
        )
        return True

    except TelegramRetryAfter as e:
        wait = int(getattr(e, "retry_after", 30)) + 1
        logger.warning(f"FloodWait {wait}s for post #{post_id}, retrying...")
        await asyncio.sleep(wait)
        return await publish_post(post_id, tenant_id, is_new=is_new)

    except TelegramForbiddenError as e:
        logger.error(f"forbidden #{post_id}: {e}")
        # Bot kanaldan chiqarib yuborilgan — kanalni nofaol qilamiz
        await db.update_announcement(post_id, tenant_id, status=PostStatus.PAUSED)
        await audit_log.log_system_event(
            action="post_publish_failed",
            tenant_id=tenant_id,
            target_id=post_id,
            level="error",
            reason="forbidden",
            channel_id=channel_id,
        )
        # Tenant'ga xabar
        await notifier.notify_warning(
            user_id=tenant_id,
            tenant_id=tenant_id,
            title="Botning kanaldagi huquqi yoʻq",
            message=(
                f"⚠️ Bot kanal <code>{channel_id}</code> ga yoza olmadi.\n"
                "Iltimos, botni admin sifatida qoʻshing yoki kanal sozlamalarini tekshiring."
            ),
        )
        return False

    except TelegramBadRequest as e:
        logger.error(f"bad request #{post_id}: {e}")
        await audit_log.log_system_event(
            action="post_publish_failed",
            tenant_id=tenant_id,
            target_id=post_id,
            level="error",
            reason=str(e),
        )
        return False

    except Exception as e:
        logger.error(f"publish error #{post_id}: {type(e).__name__}: {e}")
        await audit_log.log_system_event(
            action="post_publish_failed",
            tenant_id=tenant_id,
            target_id=post_id,
            level="error",
            reason=f"{type(e).__name__}: {e}",
        )
        return False


# ─────────────────────────────────────────────────────────────────────
# E'lonni o'chirish (kanaldan)
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
        with contextlib.suppress(Exception):
            await bot.delete_message(channel_id, int(message_id))

    await db.update_announcement(
        post_id, tenant_id, status=PostStatus.DELETED, message_id=None
    )
    return True
