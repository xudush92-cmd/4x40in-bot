"""
services/cleaner.py — eskirgan e'lonlarni tozalash servisi.

VAZIFASI:
─────────
Har 5 daqiqada DB'ni tekshirib, expires_at o'tib ketgan aktiv e'lonlarni:
  1. Status='expired' qiladi
  2. Kanaldan o'chiradi (publisher orqali)
  3. User'ga notification yuboradi
"""

from __future__ import annotations

import asyncio
import contextlib

from config import PostStatus
from core import audit_log, database as db, notifier
from core.error_handler import safe_loop
from utils import logger as log_mod

logger = log_mod.get_logger("services.cleaner")


# ─────────────────────────────────────────────────────────────────────
# Asosiy loop
# ─────────────────────────────────────────────────────────────────────
async def cleaner_run_once() -> None:
    """Cheksiz cleaner loop — har 5 daqiqada."""
    while True:
        try:
            await _cleanup_expired()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"cleaner tick error: {type(e).__name__}: {e}")

        await asyncio.sleep(300)  # 5 daqiqa


async def start_cleaner() -> None:
    """Cleaner servisini ishga tushirish."""
    await safe_loop("cleaner", cleaner_run_once, restart_delay=30)


# ─────────────────────────────────────────────────────────────────────
# Tozalash mantiqi
# ─────────────────────────────────────────────────────────────────────
async def _cleanup_expired() -> None:
    """Vaqti tugagan e'lonlarni topib, tozalash."""
    expired = await db.list_expired_announcements()
    if not expired:
        return

    logger.info(f"cleaner: {len(expired)} expired post topildi")

    for post in expired:
        try:
            await _expire_one(post)
        except Exception as e:
            logger.error(
                f"cleaner: post #{post.get('id')} expire xato: {type(e).__name__}: {e}"
            )


async def _expire_one(post: dict) -> None:
    """Bitta e'lonni expire qilish."""
    post_id = int(post["id"])
    tenant_id = int(post["tenant_id"])
    user_id = int(post["user_id"])

    # Status'ni expired qilamiz
    await db.update_announcement(post_id, tenant_id, status=PostStatus.EXPIRED)

    # Kanaldan o'chirishga harakat (publisher orqali)
    with contextlib.suppress(Exception):
        from services.publisher import remove_post_from_channel
        await remove_post_from_channel(post_id, tenant_id)

    # User'ga xabar
    with contextlib.suppress(Exception):
        await notifier.notify_post_expired(
            user_id=user_id, tenant_id=tenant_id, post_id=post_id
        )

    await audit_log.log_system_event(
        action="post_expired",
        tenant_id=tenant_id,
        target_type="announcement",
        target_id=post_id,
    )

    logger.info(f"expired post #{post_id} (tenant={tenant_id}, user={user_id})")
