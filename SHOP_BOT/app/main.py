"""SHOP-BOT — kirish nuqtasi.

Ishga tushirish rejimlari (RUN_MODE):
  * `bot`    — handler'lar, admin panel, sotuvchi paneli (+ /health, webhook)
  * `poster` — rejalashtiruvchi worker (joylash, eslatmalar, tozalash)
  * `all`    — ikkisi bitta processda (dev uchun qulay)

Docker Compose'da `bot` va `poster` alohida konteyner sifatida ishlaydi:
poster sekin ishlaydigan vazifalar bilan botning javob tezligini
buzmasligi uchun (REJA.md 10.3).
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from aiogram import Dispatcher
from loguru import logger

from app.bot import create_bot, create_dispatcher, log_bot_info, setup_bot_commands
from app.config import Settings, get_settings
from app.db.base import dispose_engine, session_scope
from app.logging_setup import setup_logging
from app.redis_client import make_fsm_storage, redis_manager
from app.scheduler.runner import build_scheduler, start_scheduler, stop_scheduler
from app.services.notify import ensure_super_admins
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.web.server import start_web_server


async def bootstrap(settings: Settings) -> None:
    """Ishga tushishdan oldingi tayyorgarlik: adminlar, sozlamalar keshi, matnlar."""
    async with session_scope() as session:
        await ensure_super_admins(session)

    await settings_service.get_all()
    await text_service.load()

    if await settings_service.is_kill_switch_on():
        logger.warning("🛑 Kill switch YOQILGAN — bot faqat adminlarga javob beradi")
    logger.info("Bootstrap tugadi (sozlamalar va matnlar yuklandi)")


async def _prepare_webhook(dispatcher: Dispatcher, bot, settings: Settings) -> None:
    """Webhook rejimida Telegram'ga webhook manzilini o'rnatish."""
    url = settings.webhook_url
    await bot.set_webhook(
        url=url,
        secret_token=settings.webhook_secret_value,
        allowed_updates=dispatcher.resolve_used_update_types(),
        drop_pending_updates=False,
        max_connections=40,
    )
    info = await bot.get_webhook_info()
    logger.info("Webhook o'rnatildi: {} (pending: {})", info.url, info.pending_update_count)


async def _prepare_polling(dispatcher: Dispatcher, bot, settings: Settings) -> asyncio.Task:
    """Polling rejimida eski webhook'ni o'chirib, polling'ni boshlash."""
    try:
        info = await bot.get_webhook_info()
        if info.url:
            logger.warning("Eski webhook topildi ({}), o'chirilmoqda", info.url)
            await bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:  # pragma: no cover
        logger.debug("Webhook holatini tekshirib bo'lmadi: {}", exc)

    return asyncio.create_task(
        dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            handle_signals=False,
            close_bot_session=False,
        ),
        name="polling",
    )


async def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)

    logger.info(
        "🚀 SHOP-BOT {} ishga tushmoqda (mode={}, webhook={})",
        "v0.1.0",
        settings.run_mode,
        settings.use_webhook,
    )

    # Majburiy sozlamalar
    try:
        settings.validate_for_bot()
    except RuntimeError as exc:
        logger.error("❌ {}", exc)
        logger.error("`.env` faylini to'ldiring (.env.example dan nusxa oling).")
        return 2

    # Redis (ixtiyoriy — bo'lmasa xotira rejimi)
    await redis_manager.connect()

    # Baza va kesh
    try:
        await bootstrap(settings)
    except Exception as exc:
        logger.exception("Bootstrap xatosi: {}", exc)
        logger.error("Baza ishlayaptimi? Migratsiyalar bajarilganmi? (`alembic upgrade head`)")
        return 3

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # pragma: no cover — Windows
            loop.add_signal_handler(sig, stop_event.set)

    bot = create_bot(settings)
    try:
        await log_bot_info(bot)
    except Exception:
        logger.error(
            "❌ Telegram'ga ulanib bo'lmadi. BOT_TOKEN to'g'rimi va internet "
            "mavjudmi? (@BotFather dan olingan tokenni tekshiring)"
        )
        await bot.session.close()
        await dispose_engine()
        await redis_manager.close()
        return 4
    await setup_bot_commands(bot)

    dispatcher: Dispatcher | None = None
    storage = await make_fsm_storage()
    if settings.run_mode in ("bot", "all"):
        dispatcher = create_dispatcher(settings, storage)

    # HTTP server (health + webhook) — har ikkala rejimda ham ishlaydi
    web_runner = await start_web_server(settings, bot, dispatcher)

    # Rejalashtiruvchi
    scheduler = None
    if settings.run_mode in ("poster", "all"):
        scheduler = build_scheduler(settings, bot)
        await start_scheduler(scheduler)

    # Botni ishga tushirish
    poll_task: asyncio.Task | None = None
    if dispatcher is not None:
        if settings.use_webhook:
            await _prepare_webhook(dispatcher, bot, settings)
        else:
            poll_task = await _prepare_polling(dispatcher, bot, settings)
            logger.info("Polling boshlandi (allowed_updates={})", dispatcher.resolve_used_update_types())

    logger.info("✅ Tizim ishga tushdi. To'xtatish uchun Ctrl+C yoki SIGTERM.")

    # ── Asosiy kutish ─────────────────────────────────────────
    try:
        await stop_event.wait()
    finally:
        logger.info("⏹ To'xtatilmoqda (graceful shutdown)...")

        if poll_task is not None:
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task

        if scheduler is not None:
            await stop_scheduler(scheduler)

        await web_runner.cleanup()
        with suppress(Exception):
            await storage.close()
        with suppress(Exception):
            await bot.session.close()
        await dispose_engine()
        await redis_manager.close()
        logger.info("👋 To'xtatildi. Xayr!")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
