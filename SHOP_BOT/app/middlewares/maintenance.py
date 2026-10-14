"""Texnik rejim / kill switch va bloklangan foydalanuvchilarni to'sish.

  * `kill_switch`    — 🛑 HAMMASINI TO'XTATISH (REJA.md 1.2/#14)
  * `maintenance_mode` — botdan faqat adminlar foydalanadi
  * `is_blocked`     — bloklangan foydalanuvchi (ban) hech narsa qila olmaydi
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject

from app.services.settings_service import settings_service


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Guruh ichidagi xabarlarni to'smaymiz — ularni posbon/tozalovchi ko'radi
        chat: Chat | None = data.get("event_chat")
        is_private = chat is not None and chat.type == "private"

        if not is_private:
            return await handler(event, data)

        is_admin = bool(data.get("is_admin"))
        user = data.get("user")

        # Bloklangan foydalanuvchi
        if not is_admin and user is not None and getattr(user, "is_blocked", False):
            await self._reply(event, "🚫 Sizga botdan foydalanish taqiqlangan.")
            return None

        if not is_admin:
            if await settings_service.is_kill_switch_on():
                await self._reply(event, "🛑 Bot vaqtincha to'xtatilgan (texnik ishlar).")
                return None
            if await settings_service.get("maintenance_mode", False):
                await self._reply(event, "🔧 Texnik xizmat rejimi. Birozdan so'ng urinib ko'ring.")
                return None

        return await handler(event, data)

    @staticmethod
    async def _reply(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # pragma: no cover
            pass
