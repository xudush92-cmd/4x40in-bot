"""Sotuvchi bilan ishlash servisi (Phase 2 da to'liq to'ldiriladi)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import SellerStatus
from app.db.models import Seller


async def get_seller(session: AsyncSession, user_id: int) -> Seller | None:
    """Foydalanuvchining sotuvchi yozuvini olish (bo'lmasa None)."""
    return (
        await session.execute(select(Seller).where(Seller.user_id == user_id))
    ).scalar_one_or_none()


async def is_active_seller(session: AsyncSession, user_id: int) -> bool:
    """Faol (bloklanmagan) sotuvchimi."""
    seller = await get_seller(session, user_id)
    return seller is not None and seller.status != SellerStatus.BLOCKED


async def get_seller_by_referral_code(session: AsyncSession, code: str) -> Seller | None:
    """Referal kodi bo'yicha sotuvchini topish (Phase 8)."""
    return (
        await session.execute(select(Seller).where(Seller.referral_code == code))
    ).scalar_one_or_none()
