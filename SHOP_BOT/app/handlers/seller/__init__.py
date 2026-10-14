"""Sotuvchi paneli router'i.

Phase 0 da faqat skelet: tugmalar javob beradi va qaysi bosqichda
to'liq ishlashini aytadi. To'liq mantiq Phase 2 (tarif/obuna) va
Phase 3 (e'lon qo'shish) da qo'shiladi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.filters import IsSeller

seller_router = Router(name="seller")
seller_router.callback_query.filter(F.data.startswith("sm:"))

STUBS: dict[str, tuple[str, int]] = {
    "sm:tariff": ("💳 Tarif va to'lov", 5),
    "sm:ads": ("📢 Mening e'lonlarim", 3),
    "sm:my_tariff": ("📅 Mening tarifim", 2),
    "sm:referral": ("🎁 Referal", 8),
}


@seller_router.callback_query(F.data.in_(set(STUBS)))
async def seller_stub(callback: CallbackQuery) -> None:
    title, phase = STUBS.get(callback.data or "", ("Bu bo'lim", 9))
    await callback.answer(f"{title} — Phase {phase} da qo'shiladi.", show_alert=True)


__all__ = ["seller_router"]
_ = IsSeller
