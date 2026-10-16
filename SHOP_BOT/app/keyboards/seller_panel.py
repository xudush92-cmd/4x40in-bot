"""Sotuvchi paneli klaviaturalari (tarif, e'lon va to'lov).

Sotuvchi o'z panelini faqat shaxsiy chatda ko'radi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Tariff
from app.keyboards.callbacks import GuideCB, SellerPanelCB
from app.utils.text import truncate


def seller_menu_kb(*, has_subscription: bool = False, ads_count: int = 0) -> InlineKeyboardMarkup:
    """Asosiy sotuvchi menyusi."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📅 Mening tarifim", callback_data=SellerPanelCB(action="tariff").pack()
            )
        ]
    ]

    if has_subscription:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📢 Mening e'lonlarim ({ads_count})",
                    callback_data=SellerPanelCB(action="ads").pack(),
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Yangi e'lon", callback_data=SellerPanelCB(action="new_ad").pack()
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="💳 Tariflarni ko'rish / olish", callback_data=SellerPanelCB(action="tariffs").pack()
            ),
            InlineKeyboardButton(
                text="🧾 To'lovlarim", callback_data=SellerPanelCB(action="payments").pack()
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🎁 Referal", callback_data=SellerPanelCB(action="referral").pack()
            ),
            InlineKeyboardButton(
                text="☎️ Yordam", callback_data=SellerPanelCB(action="support").pack()
            ),
        ]
    )
    rows.append([InlineKeyboardButton(
        text="📖 Foydalanish yo'riqnomasi", callback_data=GuideCB().pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariff_screen_kb(*, has_subscription: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="💳 Barcha tariflar", callback_data=SellerPanelCB(action="tariffs").pack()
            )
        ]
    ]
    if has_subscription:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Holatni yangilash", callback_data=SellerPanelCB(action="tariff").pack()
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Orqaga", callback_data=SellerPanelCB(action="menu").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariffs_catalog_kb(tariffs: list[Tariff] | None = None) -> InlineKeyboardMarkup:
    """Har faol pullik tarif uchun alohida «To'lash» tugmasi."""
    rows = [
        [InlineKeyboardButton(
            text=f"💳 {truncate(tariff.name, 29)} — To'lash",
            callback_data=SellerPanelCB(action="pay", value=str(tariff.id)).pack(),
        )]
        for tariff in (tariffs or []) if tariff.price > 0
    ]
    rows.extend([
        [InlineKeyboardButton(
            text="☎️ Tarif olish uchun yordam", callback_data=SellerPanelCB(action="support").pack(),
        )],
        [InlineKeyboardButton(
            text="◀️ Orqaga", callback_data=SellerPanelCB(action="menu").pack(),
        )],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data=SellerPanelCB(action="menu").pack())]
        ]
    )


__all__ = ["back_to_menu_kb", "seller_menu_kb", "tariff_screen_kb", "tariffs_catalog_kb"]
