"""Chat turi filtrlari.

Diqqat: `F.chat.type` magic-filtri `CallbackQuery` uchun ISHLAMAYDI
(unda `.chat` xossasi yo'q, chat faqat `message.chat` ichida).
Shu sababli chat turini tekshirish har doim shu filtrlar orqali qilinadi.
"""

from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject


def _chat_type(event: TelegramObject) -> str | None:
    """Xabar yoki tugma bosilishidan chat turini olish."""
    chat: Any = getattr(event, "chat", None)
    if chat is None:
        message: Any = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
    return getattr(chat, "type", None)


class PrivateChat(BaseFilter):
    """Faqat shaxsiy chat (bot bilan yakkama-yakka) yangilanishlari."""

    async def __call__(self, event: TelegramObject) -> bool:
        return _chat_type(event) == "private"


class GroupChat(BaseFilter):
    """Faqat guruh/superguruh yangilanishlari."""

    async def __call__(self, event: TelegramObject) -> bool:
        return _chat_type(event) in ("group", "supergroup")


__all__ = ["GroupChat", "PrivateChat"]
