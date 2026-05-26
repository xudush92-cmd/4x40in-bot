"""
core/middleware.py — global xato boshqaruv middleware'lari.

MAQSAD:
───────
Har bir handler ichida try/except yozish o'rniga — global middleware
har xato'ni ushlaydi va foydalanuvchiga moslash javob beradi.

USHLANADI:
──────────
- PermissionDenied      → user'ga "ruxsat yo'q" xabari
- ValidationError       → user'ga validation xato matni
- TelegramAPIError      → silent log (ko'pchilik holatda transient)
- Boshqa Exception'lar  → user'ga umumiy xato + audit log

USAGE:
──────
    from core.middleware import register_middlewares

    register_middlewares(dp)
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from core.error_handler import capture_error, format_user_error
from core.permissions import PermissionDenied

logger = logging.getLogger("enginebot.middleware")


class ErrorMiddleware(BaseMiddleware):
    """
    Global xato boshqaruv middleware.

    Har handler oldidan ishlaydi va exception ushlanganda:
    1. Audit log'ga yozadi
    2. Foydalanuvchiga moslash javob beradi
    3. Xato'ni yutib yuboradi (handler crash bo'lmasin)
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)

        except PermissionDenied as e:
            # Ruxsat yo'q xato'si — foydalanuvchiga aniq xabar
            await self._reply(event, getattr(e, "user_message", str(e)))
            user_id = self._extract_user_id(event)
            logger.info(f"permission_denied: user={user_id} msg={e}")

        except TelegramAPIError as e:
            # Telegram API xato'lari (bot blocked, chat not found, va h.k.)
            # Ko'pchilik holatda foydalanuvchi uchun sezilmaydi
            user_id = self._extract_user_id(event)
            logger.warning(f"telegram_api_error: user={user_id} {type(e).__name__}: {e}")

        except Exception as e:
            # Boshqa har qanday xato — audit + umumiy xabar
            user_id = self._extract_user_id(event)
            logger.exception(
                f"handler_error: user={user_id} {type(e).__name__}: {e}"
            )
            with contextlib.suppress(Exception):
                await capture_error(
                    "middleware",
                    e,
                    actor_id=user_id,
                )
            with contextlib.suppress(Exception):
                await self._reply(event, format_user_error(e))

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        """Event'dan user_id ajratib olish."""
        if isinstance(event, (Message, CallbackQuery)):
            if event.from_user:
                return event.from_user.id
        return None

    @staticmethod
    async def _reply(event: TelegramObject, text: str) -> None:
        """Event turi'ga qarab javob yuborish (xavfsiz)."""
        with contextlib.suppress(Exception):
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                # Callback uchun avval popup, keyin agar message bo'lsa — chat'ga
                await event.answer(text[:200], show_alert=True)


def register_middlewares(dp) -> None:
    """
    Dispatcher'ga barcha middleware'larni ulash.

    main.py'da `_register_routers` dan oldin chaqiriladi.
    """
    err_mw = ErrorMiddleware()
    dp.message.middleware(err_mw)
    dp.callback_query.middleware(err_mw)
    logger.info("✅ Middleware registered: ErrorMiddleware")
