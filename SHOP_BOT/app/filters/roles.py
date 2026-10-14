"""Rol filtrlari.

Muhim (aiogram 3): filtrlar `data` lug'atini alohida argument sifatida EMAS,
balki **kalit so'z argumentlari** sifatida oladi (`session=...`, `is_admin=...`).
Shu sababli imzo har doim `(self, event, **kwargs)` ko'rinishida bo'ladi —
aks holda `TypeError: missing 1 required positional argument: 'data'` chiqadi.
"""

from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from sqlalchemy import select

from app.constants import AdminRole, PermissionKind
from app.db.base import session_scope
from app.db.models import Permission
from app.services.seller_service import is_active_seller
from app.utils.time import utcnow


class IsAdmin(BaseFilter):
    """Admin (ixtiyoriy: faqat `role` yoki undan yuqori)."""

    def __init__(self, role: str | None = None) -> None:
        self.role = role
        self._order = {
            AdminRole.MODERATOR: 1,
            AdminRole.ADMIN: 2,
            AdminRole.SUPER: 3,
            None: 0,
        }

    async def __call__(self, event: TelegramObject, **kwargs: Any) -> bool:
        if not kwargs.get("is_admin"):
            return False
        if self.role is None:
            return True
        current = kwargs.get("role")
        return self._order.get(current, 0) >= self._order.get(self.role, 0)


class IsSuperAdmin(IsAdmin):
    def __init__(self) -> None:
        super().__init__(role=AdminRole.SUPER)


class IsSeller(BaseFilter):
    """Faol sotuvchi (bloklanmagan)."""

    async def __call__(self, event: TelegramObject, **kwargs: Any) -> bool:
        user = kwargs.get("user")
        if user is None:
            return False

        session = kwargs.get("session")
        if session is not None:
            return await is_active_seller(session, user.user_id)

        async with session_scope() as own_session:
            return await is_active_seller(own_session, user.user_id)


class HasPermission(BaseFilter):
    """Ruxsat tekshiruvi (REJA.md 1 — Ruxsatlar).

    `group_id=None` → barcha guruhlar uchun berilgan ruxsat ham hisobga olinadi.
    """

    def __init__(self, kind: str = PermissionKind.FULL_EXEMPT, group_id: int | None = None) -> None:
        self.kind = kind
        self.group_id = group_id

    async def __call__(self, event: TelegramObject, **kwargs: Any) -> bool:
        user = kwargs.get("user")
        if user is None:
            return False

        session = kwargs.get("session")
        if session is not None:
            return await self._check(session, user.user_id)

        async with session_scope() as own_session:
            return await self._check(own_session, user.user_id)

    async def _check(self, session: Any, user_id: int) -> bool:
        stmt = select(Permission.id).where(
            Permission.user_id == user_id,
            Permission.is_active.is_(True),
            Permission.kind == self.kind,
            (Permission.expires_at.is_(None)) | (Permission.expires_at > utcnow()),
        )
        if self.group_id is not None:
            stmt = stmt.where((Permission.group_id == self.group_id) | (Permission.group_id.is_(None)))
        else:
            stmt = stmt.where(Permission.group_id.is_(None))

        return (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None
