"""
services/scheduler.py — PER-POSTER aylanish (rotation) servisi.

V1 MODELI (foydalanuvchi qatʼiy talabi):
─────────────────────────────────────────
- Har POSTER oʻz intervalini belgilaydi (min 10 daq)
- Posterning eʼlonlari KETMA-KET (queue_order bo'yicha) chiqadi
- Cheksiz aylanadi — POSTER STOP bosmaguncha
- Birinchi marta START bosganda — birinchi e'lon DARHOL chiqadi
- Boshqa posterlardan MUSTAQIL ishlaydi (bittasi crash → boshqalar davom etadi)

ALGORITM (har 60 soniya):
─────────────────────────
1. rotation_active=1 bo'lgan barcha posterlarni olish
2. Har poster uchun:
   a. last_rotated_at + interval_min > now → kutib turamiz (vaqt yetmagan)
   b. tenant_settings ekranlash (bot_active va tenant min cheklovi)
   c. queue (queue_order ASC) olamiz, current_post_index'ga qarab
   d. Sikldagi keyingi e'lonni olib publisher.publish_post(...) chaqiramiz
   e. current_post_index'ni keyingiga (oxiridan keyin 0'ga)
   f. last_rotated_at = now
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from config import DEFAULT_TZ_OFFSET, Rotation
from core import database as db
from core.error_handler import safe_loop
from utils import logger as log_mod

logger = log_mod.get_logger("services.scheduler")


# ─────────────────────────────────────────────────────────────────────
# Asosiy loop
# ─────────────────────────────────────────────────────────────────────
async def scheduler_run_once() -> None:
    """Cheksiz scheduler loop — har 60 soniyada bir marta tekshiradi."""
    while True:
        try:
            await _process_rotations()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"scheduler tick error: {type(e).__name__}: {e}")

        await asyncio.sleep(60)


async def start_scheduler() -> None:
    """Scheduler servisini ishga tushirish (main.py'da chaqiriladi)."""
    await safe_loop("scheduler", scheduler_run_once, restart_delay=10)


# ─────────────────────────────────────────────────────────────────────
# Bitta tick mantiqi
# ─────────────────────────────────────────────────────────────────────
async def _process_rotations() -> None:
    """Auto-post yoqilgan barcha posterlarni tekshirish."""
    posters = await db.get_posters_with_active_rotation(limit=10000)
    if not posters:
        return

    now = datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
    rotated = 0

    for poster in posters:
        try:
            if await _process_poster(poster, now):
                rotated += 1
        except Exception as e:
            logger.error(
                f"poster {poster.get('user_id')} rotation error: "
                f"{type(e).__name__}: {e}"
            )
            # Bitta poster crash bo'lsa — boshqalari davom etadi (izolyatsiya)

    if rotated > 0:
        logger.info(f"scheduler: {rotated}/{len(posters)} poster aylantirildi")


async def _process_poster(poster: dict, now: datetime) -> bool:
    """
    Bitta posterning navbatdagi eʼlonini chiqarish.

    Returns: True = eʼlon chiqarildi, False = vaqt yetmagan / chiqarilmadi
    """
    tenant_id = int(poster["tenant_id"])
    user_id = int(poster["user_id"])
    interval_min = int(poster.get("rotation_interval_min", Rotation.DEFAULT_INTERVAL_MIN))

    # Tenant cheklovini hurmat qilamiz (tenant min'ni override qila olmaydi)
    tenant_settings = await db.get_settings(tenant_id)
    if not tenant_settings.get("bot_active"):
        # Tenant botni o'chirgan — rotation yo'q
        return False

    tenant_min = int(tenant_settings.get("rotation_interval_min", Rotation.MIN_INTERVAL_MIN))
    effective_interval = max(interval_min, tenant_min, Rotation.MIN_INTERVAL_MIN)

    # Vaqt yetdimi?
    last_rotated = poster.get("last_rotated_at")
    if last_rotated:
        try:
            last_dt = datetime.fromisoformat(last_rotated)
        except ValueError:
            last_dt = None
    else:
        last_dt = None

    if last_dt is not None:
        elapsed = (now - last_dt).total_seconds() / 60
        if elapsed < effective_interval:
            return False

    # Posterning gala ro'yxati
    queue = await db.get_user_post_queue(tenant_id, user_id)
    if not queue:
        # Eʼlon yo'q — rotation o'chiramiz
        await db.set_poster_rotation(tenant_id, user_id, active=False)
        logger.info(f"poster {user_id}: queue bo'sh — rotation auto-OFF")
        return False

    # Sikldagi keyingi indeks
    current_idx = int(poster.get("current_post_index", 0))
    if current_idx >= len(queue):
        current_idx = 0  # cycle restart

    candidate = queue[current_idx]
    post_id = int(candidate["id"])

    # Publisher orqali chiqaramiz (publisher set_bot allaqachon main.py'da chaqirilgan)
    from services.publisher import publish_post
    # is_first: post hali kanalga chiqmagan bo'lsa (message_id YO'Q)
    is_first = not candidate.get("message_id")
    success = await publish_post(post_id, tenant_id, is_new=is_first)

    if not success:
        logger.warning(f"poster {user_id} post #{post_id} publish failed")
        # Failure — keyingi tickda qayta urinib ko'ramiz, indeks o'zgarmaydi
        return False

    # Indeksni keyingiga
    next_idx = (current_idx + 1) % len(queue)
    await db.advance_user_rotation(tenant_id, user_id, new_index=next_idx)

    logger.info(
        f"rotated: poster={user_id} post=#{post_id} "
        f"({current_idx+1}/{len(queue)}) interval={effective_interval}m"
    )
    return True
