"""
core/error_handler.py — crash isolation va xato boshqaruv.

MAQSAD:
───────
Bittasi crash boʻlsa boshqasi davom etsin. ENGINEBOT'ning eng muhim
xavfsizlik printsipi: izolyatsiya.

KOMPONENTLAR:
─────────────
1. safe_loop()      — background task uchun crash-safe wrapper
2. capture_error()  — xatolarni audit log'ga yozish
3. handle_pd()      — PermissionDenied'ni foydalanuvchiga koʻrsatish
4. ErrorBoundary    — context manager ("with" bloki uchun)

Misol:
    # Background service
    asyncio.create_task(
        safe_loop("scheduler", scheduler_loop, restart_delay=5)
    )

    # Handler ichida
    async with ErrorBoundary("post_create", actor=ctx):
        await create_post(...)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
from typing import Any, Awaitable, Callable

logger = logging.getLogger("enginebot.error")


# ─────────────────────────────────────────────────────────────────────
# Background loop wrapper
# ─────────────────────────────────────────────────────────────────────
async def safe_loop(
    name: str,
    coro_factory: Callable[[], Awaitable[None]],
    *,
    restart_delay: float = 5.0,
    max_consecutive_failures: int = 10,
    on_error: Callable[[Exception], Awaitable[None]] | None = None,
) -> None:
    """
    Cheksiz background task — crash boʻlsa qayta urinadi.

    Args:
        name             : task nomi (log uchun)
        coro_factory     : har safar yangi coroutine qaytaradi (lambda)
        restart_delay    : crash dan keyin qancha kutish (sekund)
        max_consecutive_failures : ketma-ket shuncha crash boʻlsa toʻxtaydi
        on_error         : ixtiyoriy callback (har crashda chaqiriladi)

    Misol:
        await safe_loop(
            "scheduler",
            scheduler_run_once,  # bu func aslida cheksiz loop emas — service ichida.
            restart_delay=10,
        )

    Eslatma: agar coro_factory'ning oʻzi cheksiz loop boʻlsa
    (while True), bu wrapper faqat crash holatida qayta ishga tushiradi.
    Agar normal return boʻlsa — qaytadan boshlaydi.
    """
    consecutive_failures = 0

    while True:
        try:
            logger.info(f"🟢 service start: {name}")
            await coro_factory()
            # Normal return — qayta ishga tushiramiz
            consecutive_failures = 0
            logger.info(f"🔄 service {name} finished normally — restarting")

        except asyncio.CancelledError:
            logger.info(f"🛑 service stopped: {name}")
            raise

        except Exception as e:
            consecutive_failures += 1
            tb = traceback.format_exc()
            logger.error(
                f"💥 service crash: {name} #{consecutive_failures} "
                f"{type(e).__name__}: {e}\n{tb}"
            )

            if on_error is not None:
                with contextlib.suppress(Exception):
                    await on_error(e)

            if consecutive_failures >= max_consecutive_failures:
                logger.critical(
                    f"⛔ service {name} stopped: {consecutive_failures} consecutive failures"
                )
                # Audit log'ga yozish
                with contextlib.suppress(Exception):
                    from core import audit_log
                    await audit_log.log_system_event(
                        action="service_crashed",
                        details={
                            "service": name,
                            "failures": consecutive_failures,
                            "last_error": str(e),
                        },
                        level="critical",
                    )
                return

            await asyncio.sleep(restart_delay)


# ─────────────────────────────────────────────────────────────────────
# Audit'ga xato yozish
# ─────────────────────────────────────────────────────────────────────
async def capture_error(
    where: str,
    error: BaseException,
    *,
    actor_id: int | None = None,
    tenant_id: int | None = None,
    extra: dict | None = None,
) -> None:
    """
    Xatoni audit log'ga yozish.

    Handler crash boʻlganida diagnostika uchun ishlatiladi.
    """
    payload = {
        "where": where,
        "error_type": type(error).__name__,
        "error_msg": str(error),
        **(extra or {}),
    }
    logger.error(f"capture_error [{where}]: {type(error).__name__}: {error}")

    with contextlib.suppress(Exception):
        from core import audit_log
        await audit_log.log_action(
            actor_role="system" if actor_id is None else "user",
            actor_id=actor_id or 0,
            tenant_id=tenant_id,
            action="error_captured",
            target_type="error",
            details=payload,
            level="error",
        )


# ─────────────────────────────────────────────────────────────────────
# Handler ichidagi xato boundary
# ─────────────────────────────────────────────────────────────────────
class ErrorBoundary:
    """
    Context manager: handler ichidagi blokni xato'lardan himoyalaydi.

    Foydalanish:
        async with ErrorBoundary("create_post", actor_id=uid, tenant_id=tid):
            await some_risky_operation()

    Xato boʻlsa:
      • Audit log'ga yoziladi
      • Logger'ga yoziladi
      • Suppress=True boʻlsa — exception yutib yuboriladi
      • Aks holda — exception qayta raise qilinadi
    """

    def __init__(
        self,
        where: str,
        *,
        actor_id: int | None = None,
        tenant_id: int | None = None,
        suppress: bool = False,
        extra: dict | None = None,
    ) -> None:
        self.where = where
        self.actor_id = actor_id
        self.tenant_id = tenant_id
        self.suppress = suppress
        self.extra = extra or {}

    async def __aenter__(self) -> "ErrorBoundary":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            return False
        if isinstance(exc, asyncio.CancelledError):
            return False  # cancel — qayta raise

        await capture_error(
            self.where,
            exc,
            actor_id=self.actor_id,
            tenant_id=self.tenant_id,
            extra=self.extra,
        )
        return self.suppress


# ─────────────────────────────────────────────────────────────────────
# Foydalanuvchiga koʻrsatish (bot xato xabari)
# ─────────────────────────────────────────────────────────────────────
USER_ERROR_MESSAGE = (
    "❌ Texnik xato yuz berdi.\n\n"
    "Qaytadan urinib koʻring. Muammo davom etsa kanal egasi yoki\n"
    "yordam xizmati bilan bogʻlaning."
)


def format_user_error(error: BaseException) -> str:
    """
    Foydalanuvchiga koʻrsatiladigan xato xabarini tayyorlash.

    Ichki tafsilotlarni ochmaslik uchun umumiy xabar.
    """
    # Maʼlum xato turlari uchun aniqroq xabar
    name = type(error).__name__
    if name == "PermissionDenied":
        return getattr(error, "user_message", str(error))
    if "FloodWait" in name:
        return "⏳ Telegram juda koʻp soʻrov sezdi. Bir oz kuting."
    if "Timeout" in name or "TimeoutError" in name:
        return "⏱ Server javob bermadi. Qaytadan urinib koʻring."
    return USER_ERROR_MESSAGE
