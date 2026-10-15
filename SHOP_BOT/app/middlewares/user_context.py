"""Foydalanuvchi konteksti: `users` yozuvini yangilash, admin/rol aniqlash.

Handler ichida quyidagilar mavjud bo'ladi:
  data["user"]      — User modeli
  data["is_admin"]  — bool
  data["admin"]     — Admin modeli yoki None
  data["role"]      — "super" | "admin" | "moderator" | None
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Admin, User
from app.utils.time import ensure_aware, utcnow

# Admin holatini tez-tez DB'dan o'qimaslik uchun oddiy kesh
_ADMIN_CACHE: dict[int, tuple[float, bool, str | None]] = {}
_ADMIN_CACHE_TTL = 60.0

# last_seen_at ni har update'da yozmaslik uchun
_LAST_SEEN_WRITE_INTERVAL = 3600.0


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        tg_user: TgUser | None = data.get("event_from_user")

        if session is not None and tg_user is not None and not tg_user.is_bot:
            user, is_new = await self._ensure_user(session, tg_user)
            data["user"] = user
            data["user_is_new"] = is_new

            is_admin, role, admin_row = await self._resolve_admin(session, tg_user.id)
            data["is_admin"] = is_admin
            data["role"] = role
            data["admin"] = admin_row

        return await handler(event, data)

    # ── Ichki ─────────────────────────────────────────────────
    @staticmethod
    async def _ensure_user(session: AsyncSession, tg_user: TgUser) -> tuple[User, bool]:
        user = await session.get(User, tg_user.id)
        now = utcnow()

        if user is None:
            user = User(
                user_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                last_seen_at=now,
            )
            session.add(user)
            await session.flush()
            return user, True

        # Profil ma'lumotlari o'zgargan bo'lsa — yangilash
        changed = (
            user.username != tg_user.username
            or user.first_name != tg_user.first_name
            or user.last_name != tg_user.last_name
        )
        if changed:
            user.username = tg_user.username
            user.first_name = tg_user.first_name
            user.last_name = tg_user.last_name

        # last_seen_at ni tez-tez yozmaslik (DB yuklamasini kamaytirish)
        last = ensure_aware(user.last_seen_at)
        if changed or last is None or (now - last).total_seconds() > _LAST_SEEN_WRITE_INTERVAL:
            user.last_seen_at = now

        return user, False

    @staticmethod
    async def _resolve_admin(
        session: AsyncSession, user_id: int
    ) -> tuple[bool, str | None, Admin | None]:
        cached = _ADMIN_CACHE.get(user_id)
        now = time.monotonic()
        if cached and now - cached[0] < _ADMIN_CACHE_TTL:
            _, is_admin, role = cached
            if not is_admin:
                return False, None, None

        admin = (
            await session.execute(
                select(Admin).where(Admin.user_id == user_id, Admin.is_active.is_(True))
            )
        ).scalar_one_or_none()

        is_admin = admin is not None
        role = admin.role if admin else None
        _ADMIN_CACHE[user_id] = (now, is_admin, role)

        admin_seen = ensure_aware(admin.last_seen_at) if admin is not None else None
        if admin is not None and (
            admin_seen is None
            or (utcnow() - admin_seen).total_seconds() > _LAST_SEEN_WRITE_INTERVAL
        ):
            admin.last_seen_at = utcnow()

        return is_admin, role, admin


def invalidate_admin_cache(user_id: int | None = None) -> None:
    """Admin qo'shilganda/o'chirilganda keshni tozalash."""
    if user_id is None:
        _ADMIN_CACHE.clear()
    else:
        _ADMIN_CACHE.pop(user_id, None)
