"""Sotuvchi paneli klaviaturalari (Phase 2 → 3).

Sotuvchi o'z panelini faqat shaxsiy chatda ko'radi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.keyboards.callbacks import SellerPanelCB


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
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💳 Tariflarni ko'rish", callback_data=SellerPanelCB(action="tariffs").pack()
                )
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


def tariffs_catalog_kb() -> InlineKeyboardMarkup:
    """Katalog: to'lov Phase 5 da, hozir admin bilan bog'lanish taklif qilinadi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="☎️ Tarif olish uchun yozish", callback_data=SellerPanelCB(action="support").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Orqaga", callback_data=SellerPanelCB(action="menu").pack()
                )
            ],
        ]
    )


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data=SellerPanelCB(action="menu").pack())]
        ]
    )


__all__ = ["back_to_menu_kb", "seller_menu_kb", "tariff_screen_kb", "tariffs_catalog_kb"]
