"""Oddiy anti-flood: bitta foydalanuvchidan keladigan update'lar sonini cheklash.

Bu **guruh uchun** emas (u yerda posbon ishlaydi), balki botning o'zini
himoya qilish uchun: kimdir tugmalarni ketma-ket bosib yuborsa.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.text_service import text_service


class ThrottlingMiddleware(BaseMiddleware):
    """Sliding-window limiter: `rate_limit` marta / `window` sekund."""

    def __init__(self, rate_limit: int = 20, window: float = 10.0) -> None:
        self.rate_limit = rate_limit
        self.window = window
        self._events: dict[int, deque[float]] = {}
        self._warned: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = getattr(data.get("event_from_user"), "id", None)
        if user_id is None:
            return await handler(event, data)

        # Adminlar cheklanmaydi
        if data.get("is_admin"):
            return await handler(event, data)

        now = time.monotonic()
        bucket = self._events.setdefault(user_id, deque())
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()

        if len(bucket) >= self.rate_limit:
            # Faqat 60 sekundda bir marta ogohlantiramiz
            if now - self._warned.get(user_id, 0) > 60:
                self._warned[user_id] = now
                logger.warning("Anti-flood: user {} cheklendi", user_id)
                await self._answer(event, data)
            return None  # event to'xtatiladi

        bucket.append(now)

        # Xotira o'sib ketmasligi uchun vaqti-vaqti bilan tozalash
        if len(self._events) > 5000:
            self._cleanup(now)

        return await handler(event, data)

    def _cleanup(self, now: float) -> None:
        stale = [uid for uid, bucket in self._events.items() if not bucket or now - bucket[-1] > self.window * 6]
        for uid in stale:
            self._events.pop(uid, None)

    @staticmethod
    async def _answer(event: TelegramObject, data: dict[str, Any]) -> None:
        session: AsyncSession | None = data.get("session")
        text = await text_service.get("common.error")
        warning = "🐢 Iltimos, sekinroq. Birozdan so'ng qayta urinib ko'ring."
        try:
            if isinstance(event, CallbackQuery) and event.message is not None:
                await event.message.answer(warning)
            elif hasattr(event, "answer"):
                await event.answer(warning)  # type: ignore[call-arg]
        except Exception:  # pragma: no cover — ogohlantirish yuborilmasa ham davom etamiz
            logger.debug("Anti-flood ogohlantirishini yuborib bo'lmadi")
        _ = (session, text)
