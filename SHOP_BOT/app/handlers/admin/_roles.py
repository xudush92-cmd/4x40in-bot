"""Eski panel callback'larida ham moderatorning yozish huquqini cheklash.

Router tashqi IsAdmin filtri moderatordan faqat kirishni talab qiladi. Ichki
middleware esa filter callback_data'ni parse qilgach, eski xabar tugmalarini
ham server tomonida tekshiradi (faqat klaviaturani yashirish yetarli emas).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from app.constants import AdminRole


class ReadOnlyForModerator(BaseMiddleware):
    """Moderatsiyadan tashqari guruh/toifa panelida faqat ko'rishga ruxsat."""

    def __init__(self, readonly: set[str]) -> None:
        self.readonly = readonly

    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery) and data.get("role") == AdminRole.MODERATOR:
            parsed = data.get("callback_data")
            if getattr(parsed, "action", None) not in self.readonly:
                await event.answer("⛔️ Bu amalni faqat admin bajaradi.", show_alert=True)
                return None
        return await handler(event, data)
