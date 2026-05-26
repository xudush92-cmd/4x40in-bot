"""
main.py — ENGINEBOT entry point.

ISHGA TUSHIRISH:
────────────────
    python main.py

Yoki Docker/systemd orqali production'da.

ORCHESTRATION:
──────────────
1. Logger sozlanadi
2. DB tayyorlanadi (init_db)
3. Bot va Dispatcher yaratilad
4. Routers ulanadi (start, panellar, plugin handlerlari)
5. Background servislar parallel ishga tushiriladi:
   - scheduler  (rotation)
   - cleaner    (eskirgan e'lonlar)
   - billing    (to'lov muddati)
6. Bot polling boshlanadi (long-polling)
7. SIGTERM/SIGINT'da graceful shutdown

GLOBAL bot OBYEKTI:
───────────────────
Tashqi modullar `from main import bot` orqali bot'ga kirishadi
(notification yuborish uchun). Lekin to'g'ri usul — services/publisher
orqali, chunki u throttling va xato boshqarish bilan keladi.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

# ENV o'qish va konfiguratsiya — birinchi
from config import BOT_TOKEN, BRAND_NAME, BRAND_VERSION

# aiogram
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from utils import logger as log_mod

# Logger sozlash — birinchi qadam
log_mod.setup_logging()
logger = log_mod.get_logger("main")

# DB
from core import database as core_db

# Servislar (lazy import — main() ichida ishlatamiz)
# from services import publisher, scheduler, cleaner, billing_checker

# Routers (lazy import)
# from panels import start as start_panel
# from panels.user import handlers as user_handlers
# ...


# ─────────────────────────────────────────────────────────────────────
# Global bot (panel handlerlari foydalanadi)
# ─────────────────────────────────────────────────────────────────────
bot: Bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp: Dispatcher = Dispatcher()


# ─────────────────────────────────────────────────────────────────────
# Routers'ni ulash
# ─────────────────────────────────────────────────────────────────────
def _register_routers() -> None:
    """Barcha router'larni dispatcher'ga ulash."""
    # Avval — start (eng yuqori prioritet)
    from panels.start import router as start_router
    dp.include_router(start_router)

    # Super admin (yuqori prioritet, faqat siz)
    from panels.super_admin.handlers import router as super_router
    dp.include_router(super_router)

    # Tenant (guruh egasi) — o'z profile va settings'ini boshqaradi
    from panels.tenant.handlers import router as tenant_router
    dp.include_router(tenant_router)

    # Moderator (v1.5+ uchun, hozircha bo'sh handlerlar)
    from panels.moderator.handlers import router as mod_router
    dp.include_router(mod_router)

    # Common handlers (USER uchun MY_PROFILE, LOGOUT)
    # MUHIM: poster/customer'dan OLDIN — duplicate handler'lar
    # bilan to'qnashmasligi uchun
    from panels.common_handlers import router as common_router
    dp.include_router(common_router)

    # POSTER (e'lon beruvchi)
    from panels.poster.handlers import router as poster_router
    dp.include_router(poster_router)

    # CUSTOMER (mijoz)
    from panels.customer.handlers import router as customer_router
    dp.include_router(customer_router)

    # User legacy stub (bo'sh, eski importlar buzilmasin uchun)
    from panels.user.handlers import router as user_router
    dp.include_router(user_router)

    logger.info(
        "📡 8 ta router ulandi: start, super, tenant, mod, common, "
        "poster, customer, user-legacy"
    )


# ─────────────────────────────────────────────────────────────────────
# Background servislarni ishga tushirish
# ─────────────────────────────────────────────────────────────────────
async def _start_services(stop_event: asyncio.Event) -> list[asyncio.Task]:
    """Background tasklarni ishga tushirish."""
    from services import publisher, scheduler, cleaner, billing_checker, notifier_service
    from utils.session_state import session

    publisher.set_bot(bot)
    session.start_janitor()

    tasks: list[asyncio.Task] = []
    tasks.append(asyncio.create_task(scheduler.start_scheduler(), name="scheduler"))
    tasks.append(asyncio.create_task(cleaner.start_cleaner(), name="cleaner"))
    tasks.append(
        asyncio.create_task(billing_checker.start_billing_checker(), name="billing")
    )
    tasks.append(
        asyncio.create_task(
            notifier_service.start_notifier_service(), name="notifier"
        )
    )

    logger.info(f"🛠 {len(tasks)} ta background servis ishga tushdi")
    return tasks


async def _stop_services(tasks: list[asyncio.Task]) -> None:
    """Background tasklarni graceful to'xtatish."""
    from utils.session_state import session

    logger.info("🛑 Background servislarni to'xtataman...")
    for t in tasks:
        t.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    await session.stop_janitor()
    logger.info("✅ Servislar to'xtadi")


# ─────────────────────────────────────────────────────────────────────
# Asosiy main
# ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    logger.info(
        f"⚙️  {BRAND_NAME} v{BRAND_VERSION} ishga tushmoqda..."
    )

    # 1. DB tayyorlash
    await core_db.init_db()
    logger.info("🗄 DB tayyor")

    # 2. Middleware (error handler — har handler oldidan ishlaydi)
    from core.middleware import register_middlewares
    register_middlewares(dp)

    # 3. Routers
    _register_routers()

    # 4. Background services
    stop_event = asyncio.Event()
    services = await _start_services(stop_event)

    # 5. Signal handling (SIGTERM/SIGINT)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(_handle_shutdown(s, stop_event)),
            )
        except (NotImplementedError, RuntimeError):
            # Windows yoki cheklangan loop
            pass

    # 6. Bot start_polling (asyncio'da blokirovka qiluvchi)
    logger.info(f"🤖 Bot polling boshlandi @{(await bot.me()).username}")
    try:
        await dp.start_polling(
            bot,
            handle_signals=False,  # o'zimiz boshqaramiz
            close_bot_session=False,
        )
    finally:
        # Shutdown
        logger.info("🛑 Bot to'xtatildi, servislarni yopaman...")
        await _stop_services(services)
        with contextlib.suppress(Exception):
            await bot.session.close()
        logger.info(f"👋 {BRAND_NAME} to'xtadi")


async def _handle_shutdown(sig: signal.Signals, stop_event: asyncio.Event) -> None:
    logger.info(f"📡 Signal qabul qilindi: {sig.name}")
    stop_event.set()
    # Dispatcher'ning polling'ini to'xtatish
    await dp.stop_polling()


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Ctrl+C — to'xtatildi")
        sys.exit(0)
