"""DB sessiya middleware: har update uchun bitta sessiya.

Muvaffaqiyatda commit, xatoda rollback. Handler ichida `data["session"]`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from loguru import logger

from app.db.base import session_scope


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with session_scope() as session:
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception:
                # Rollback session_scope ichida bo'ladi
                logger.exception("Handler ichida xatolik (update {}={})", type(event).__name__, getattr(event, "update_id", "?"))
                raise
