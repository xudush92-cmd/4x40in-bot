"""Bot va Dispatcher'ni yaratish, middleware'larni ulash, xato ushlagich."""

from __future__ import annotations

import time
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent, Update
from loguru import logger

from app.config import Settings
from app.handlers import build_root_router
from app.middlewares import (
    DbSessionMiddleware,
    MaintenanceMiddleware,
    ThrottlingMiddleware,
    UserContextMiddleware,
)
from app.services.notify import notify_admins, save_error

# Xato xabarlarini adminga juda tez-tez yubormaslik uchun
_ERROR_NOTIFY_INTERVAL = 60.0
_last_error_notify: float = 0.0


def create_bot(settings: Settings) -> Bot:
    """Bot obyektini yaratish (HTML parse mode bilan)."""
    session = AiohttpSession(timeout=30)
    return Bot(
        token=settings.token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_dispatcher(settings: Settings, storage: Any) -> Dispatcher:
    """Dispatcher: storage, outer middleware'lar, router'lar, xato ushlagich."""
    dp = Dispatcher(storage=storage)

    # Har update uchun DB sessiyasi va foydalanuvchi konteksti (filtrlarga ham kerak)
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserContextMiddleware())

    # Anti-flood (inner)
    throttling = ThrottlingMiddleware(rate_limit=20, window=10.0)
    dp.message.middleware(throttling)
    dp.callback_query.middleware(throttling)

    # Texnik rejim / kill switch (inner, private chatlar uchun)
    maintenance = MaintenanceMiddleware()
    dp.message.middleware(maintenance)
    dp.callback_query.middleware(maintenance)

    # Router'lar
    dp.include_router(build_root_router())

    # Xato ushlagich
    @dp.errors()
    async def on_error(event: ErrorEvent, bot: Bot) -> bool:
        return await handle_error(event, bot)

    return dp


async def handle_error(event: ErrorEvent, bot: Bot) -> bool:
    """Kutilmagan xatolarni jurnalga yozish va adminlarga xabar berish.

    True qaytaradi — aiogram xatoni "yutdi" deb hisoblaydi va bot ishlashda davom etadi.
    """
    global _last_error_notify

    exc = event.exception
    update = event.update
    context: dict[str, Any] = {
        "update_id": getattr(update, "update_id", None),
        "update_type": update.event_type if isinstance(update, Update) else None,
    }
    try:
        logger.opt(exception=exc).error("Handler xatosi: {}", exc)
    except Exception:  # pragma: no cover
        logger.error("Handler xatosi: {}", exc)

    error_id = await save_error(
        None,
        "handler",
        f"{type(exc).__name__}: {exc}",
        exc=exc,
        context=context,
    )

    now = time.monotonic()
    if now - _last_error_notify >= _ERROR_NOTIFY_INTERVAL:
        _last_error_notify = now
        try:
            await notify_admins(
                bot,
                "⚠️ <b>Xatolik yuz berdi</b>\n"
                f"Manba: handler\nTafsilot: <code>{type(exc).__name__}: {str(exc)[:200]}</code>\n"
                f"Jurnal ID: <b>{error_id}</b>",
                disable_notification=True,
            )
        except Exception:  # pragma: no cover
            logger.debug("Xato haqida adminlarga xabar yuborilmadi")

    return True


async def setup_bot_commands(bot: Bot) -> None:
    """Buyruqlar ro'yxatini o'rnatish (chapdagi menyu)."""
    commands = [
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="id", description="Telegram ID'ni ko'rish"),
        BotCommand(command="ping", description="Bot holatini tekshirish"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as exc:  # pragma: no cover — tarmoq muammosi botni to'xtatmasin
        logger.warning("Buyruqlarni o'rnatib bo'lmadi: {}", exc)


async def log_bot_info(bot: Bot) -> None:
    """Bot ma'lumotlarini logga yozish (ishga tushishda tekshiruv)."""
    try:
        me = await bot.get_me()
        logger.info("Bot ishga tayyor: @{} (id={})", me.username, me.id)
    except Exception as exc:
        logger.error("Bot ma'lumotlarini olib bo'lmadi: {}", exc)
        raise
