"""
services/scheduler.py — aylanish (rotation) servisi.

VAZIFASI:
─────────
Vaqti-vaqti bilan aktiv tenantlarni tekshirib, rotation yoqilgan
bo'lsa va interval o'tgan bo'lsa — aktiv e'lonlarni yangilab qayta yozish.

ALGORITM:
─────────
Har 60 soniyada:
  1. rotation_active=1 bo'lgan tenantlarni olish
  2. Har tenant uchun:
     - aktiv vaqt oralig'idamiz?
     - oxirgi rotation'dan beri interval o'tdimi?
  3. Vaqti yetgan tenant'da:
     - aktiv e'lonlardan eng eski yangilanganini olib
     - publisher.publish_post(...) chaqirish
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from config import DEFAULT_TZ_OFFSET, PostStatus, Rotation, TenantStatus
from core import database as db
from core.error_handler import safe_loop
from utils import logger as log_mod

logger = log_mod.get_logger("services.scheduler")


# ─────────────────────────────────────────────────────────────────────
# Asosiy loop
# ─────────────────────────────────────────────────────────────────────
async def scheduler_run_once() -> None:
    """
    Cheksiz scheduler loop — har 60 soniyada bir marta tekshiradi.
    """
    while True:
        try:
            await _process_rotations()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"scheduler tick error: {type(e).__name__}: {e}")

        await asyncio.sleep(60)


async def start_scheduler() -> None:
    """
    Scheduler servisini ishga tushirish (main.py'da chaqiriladi).
    safe_loop bilan o'ralgan — crash bo'lsa qayta ishga tushadi.
    """
    await safe_loop("scheduler", scheduler_run_once, restart_delay=10)


# ─────────────────────────────────────────────────────────────────────
# Bitta tick mantiqi
# ─────────────────────────────────────────────────────────────────────
async def _process_rotations() -> None:
    """Aktiv tenantlarni tekshirib, kerak bo'lsa rotation bajarish."""
    tenants = await db.list_tenants(status=TenantStatus.ACTIVE, limit=10000)
    now = datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))

    for tenant in tenants:
        try:
            await _process_tenant_rotation(tenant, now)
        except Exception as e:
            logger.error(
                f"tenant {tenant['tenant_id']} rotation error: {type(e).__name__}: {e}"
            )
            # Bittasi crash bo'lsa boshqalari davom etadi


async def _process_tenant_rotation(tenant: dict, now: datetime) -> None:
    """Bitta tenant uchun rotation tekshirish va bajarish."""
    tenant_id = int(tenant["tenant_id"])
    settings = await db.get_settings(tenant_id)

    if not settings.get("rotation_active") or not settings.get("bot_active"):
        return

    # Aktiv vaqt oralig'idamiz?
    if not _within_active_window(
        now, settings.get("active_from", "06:00"), settings.get("active_to", "23:00")
    ):
        return

    interval_min = int(settings.get("rotation_interval_min", Rotation.DEFAULT_INTERVAL_MIN))
    if interval_min < Rotation.MIN_INTERVAL_MIN:
        # Defensive — DB'da xato qiymat bo'lsa rotation qilmaymiz
        return

    # Aktiv e'lonlar (eng eski yangilanganini birinchi)
    posts = await db.list_active_announcements(tenant_id=tenant_id)
    if not posts:
        return

    # Birinchi candidate'ni ko'ramiz
    candidate = posts[0]
    last_rotated_str = candidate.get("last_rotated_at")
    if last_rotated_str:
        try:
            last_rotated = datetime.fromisoformat(last_rotated_str)
        except ValueError:
            last_rotated = None
    else:
        last_rotated = None

    if last_rotated:
        elapsed = (now - last_rotated).total_seconds() / 60
        if elapsed < interval_min:
            return  # vaqt hali yetmagan

    # Rotation vaqti yetgan — publisher orqali qayta yozamiz
    from services.publisher import publish_post
    success = await publish_post(int(candidate["id"]), tenant_id, is_new=False)
    if success:
        logger.info(
            f"rotated post #{candidate['id']} for tenant #{tenant_id} "
            f"(interval={interval_min}m)"
        )


# ─────────────────────────────────────────────────────────────────────
# Yordamchi: aktiv vaqt oralig'i
# ─────────────────────────────────────────────────────────────────────
def _within_active_window(now: datetime, start_str: str, end_str: str) -> bool:
    """
    HH:MM formatdagi start va end orasida ekanligini tekshiradi.
    end < start bo'lsa (kechagi davom etadi: 22:00-06:00) — qo'llanadi.
    """
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except (ValueError, AttributeError):
        return True  # parse error — har doim aktiv

    cur = now.hour * 60 + now.minute
    start = sh * 60 + sm
    end = eh * 60 + em

    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end
