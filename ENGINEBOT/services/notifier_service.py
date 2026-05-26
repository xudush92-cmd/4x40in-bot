"""
services/notifier_service.py — DB'dagi bildirishnomalarni Telegram'ga yuboruvchi.

VAZIFASI:
─────────
core/notifier.py faqat DB'ga yozadi (notifications jadval, is_sent=0).
Bu service har 5 sekundda DB'dan o'qib, Telegram'ga yuboradi va is_sent=1 qiladi.

XAVFSIZLIK:
───────────
- FloodWait error — Telegram juda ko'p so'rov sezsa, kutib turamiz
- Bot blocked / chat not found — notification'ni "yuborilgan" deb belgilaymiz
  (qayta-qayta urinmaymiz, chunki foydalanuvchi blok qilgan)
- Throttling: ikki yuborish o'rtasida 50ms (anti-flood)

PRIORITET:
──────────
DB'dagi `is_sent=0 ORDER BY created_at` — eng eski birinchi.
critical/error type'lar boshqalarga nisbatan birinchi bo'ladi (DB sort qiladi).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from core import database as db
from core.error_handler import safe_loop
from core.notifier import render_notification

logger = logging.getLogger("enginebot.notifier_service")

# ─────────────────────────────────────────────────────────────────────
# Sozlamalar
# ─────────────────────────────────────────────────────────────────────
TICK_INTERVAL_S: float = 5.0          # har 5 sekundda DB tekshiruvi
BATCH_SIZE: int = 50                  # bir tickda max nechta yuborish
SEND_DELAY_S: float = 0.05            # 50ms anti-flood
MAX_RETRIES: int = 3                  # FloodWait uchun max retry


# ─────────────────────────────────────────────────────────────────────
# Asosiy loop
# ─────────────────────────────────────────────────────────────────────
async def notifier_run_once() -> None:
    """Cheksiz notifier loop — har 5 sekundda."""
    while True:
        try:
            await _send_pending_batch()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"notifier tick error: {type(e).__name__}: {e}")

        await asyncio.sleep(TICK_INTERVAL_S)


async def start_notifier_service() -> None:
    """Notifier servisini ishga tushirish."""
    await safe_loop("notifier_service", notifier_run_once, restart_delay=10)


# ─────────────────────────────────────────────────────────────────────
# Yuborish mantiqi
# ─────────────────────────────────────────────────────────────────────
async def _send_pending_batch() -> None:
    """Bir tickda max BATCH_SIZE ta notification yuborish."""
    pending = await db.list_pending_notifications(limit=BATCH_SIZE)
    if not pending:
        return

    logger.debug(f"notifier: {len(pending)} ta yuborish kutmoqda")
    sent = 0
    failed = 0

    for notif in pending:
        try:
            ok = await _send_one(notif)
            if ok:
                sent += 1
            else:
                failed += 1
            # Anti-flood
            await asyncio.sleep(SEND_DELAY_S)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failed += 1
            logger.error(
                f"notifier: notification #{notif.get('id')} xato: "
                f"{type(e).__name__}: {e}"
            )

    if sent > 0 or failed > 0:
        logger.info(f"notifier: yuborildi={sent}, xato={failed}")


async def _send_one(notif: dict) -> bool:
    """
    Bitta notification'ni Telegram'ga yuborish.

    Returns:
        True  — muvaffaqiyatli yuborildi (yoki user blok qilgan,
                lekin biz uchun "tugadi")
        False — vaqtinchalik xato (FloodWait), keyin qayta urinish kerak
    """
    notif_id = int(notif["id"])
    user_id = int(notif["user_id"])
    text = render_notification(notif)

    # main.py'dan bot olish (lazy import — circular oldini olish)
    try:
        from main import bot
    except ImportError:
        logger.error("notifier: main.bot import qilinmadi")
        return False

    # Aiogram exceptions (versiya 3.x)
    try:
        from aiogram.exceptions import (
            TelegramAPIError,
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramRetryAfter,
        )
    except ImportError:
        # Fallback agar exception class'lari topilmasa
        TelegramAPIError = Exception  # type: ignore
        TelegramBadRequest = Exception  # type: ignore
        TelegramForbiddenError = Exception  # type: ignore
        TelegramRetryAfter = Exception  # type: ignore

    # Yuborishga urinish (FloodWait bilan retry)
    for attempt in range(MAX_RETRIES):
        try:
            await bot.send_message(chat_id=user_id, text=text)
            await db.mark_notification_sent(notif_id)
            return True

        except TelegramRetryAfter as e:
            wait = float(getattr(e, "retry_after", 5))
            logger.warning(
                f"notifier: FloodWait notif #{notif_id} {wait}s "
                f"(attempt {attempt+1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(wait + 1)
            continue

        except TelegramForbiddenError:
            # User blocked the bot — notif'ni "tugadi" deb belgilaymiz
            logger.info(
                f"notifier: notif #{notif_id} user #{user_id} blocked bot — skip"
            )
            await db.mark_notification_sent(notif_id)
            return True

        except TelegramBadRequest as e:
            # Chat not found, parse error va h.k. — qayta urinish foydasiz
            logger.warning(
                f"notifier: notif #{notif_id} TelegramBadRequest: {e}"
            )
            await db.mark_notification_sent(notif_id)
            return True

        except TelegramAPIError as e:
            logger.error(
                f"notifier: notif #{notif_id} TelegramAPIError: {e}"
            )
            return False  # vaqtinchalik xato

        except Exception as e:
            # Boshqa exception (network, etc.)
            logger.error(
                f"notifier: notif #{notif_id} {type(e).__name__}: {e}"
            )
            return False

    # Max retry — qoldiramiz
    logger.error(
        f"notifier: notif #{notif_id} max retries ({MAX_RETRIES}) exceeded"
    )
    return False
