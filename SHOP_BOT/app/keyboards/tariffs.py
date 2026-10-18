"""Tariflar bo'limi klaviaturalari (Phase 2)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Tariff
from app.keyboards.callbacks import AdminCB, TariffCB
from app.keyboards.common import confirm_row, nav_row
from app.services.tariff_service import format_interval, format_price, tariffs_label

MENU_BUTTON = InlineKeyboardButton(
    text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack()
)


def tariff_button(tariff: Tariff) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=f"{tariffs_label(tariff)} · {format_price(tariff)}",
        callback_data=TariffCB(action="card", tariff_id=tariff.id).pack(),
    )


def tariffs_list_kb(tariffs: list[Tariff], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[tariff_button(t)] for t in tariffs]

    rows.append(
        nav_row(
            prev_data=TariffCB(action="list", value=str(page - 1)).pack() if page > 0 else None,
            next_data=TariffCB(action="list", value=str(page + 1)).pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
            refresh_data=TariffCB(action="list", value=str(page)).pack(),
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi tarif", callback_data=TariffCB(action="create").pack()
            )
        ]
    )
    rows.append([MENU_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariff_card_kb(tariff: Tariff, *, subs: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"💰 {format_price(tariff)}",
                callback_data=TariffCB(action="price", tariff_id=tariff.id).pack(),
            ),
            InlineKeyboardButton(
                text=f"📅 {tariff.duration_days} kun",
                callback_data=TariffCB(action="days", tariff_id=tariff.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📢 {tariff.max_ads} e'lon",
                callback_data=TariffCB(action="ads", tariff_id=tariff.id).pack(),
            ),
            InlineKeyboardButton(
                text=f"🖼 {tariff.max_photos} rasm",
                callback_data=TariffCB(action="photos", tariff_id=tariff.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"⏱ {format_interval(tariff.interval_sec)} — o'zgartirish",
                callback_data=TariffCB(action="interval", tariff_id=tariff.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="✏️ Nom", callback_data=TariffCB(action="rename", tariff_id=tariff.id).pack()
            ),
            InlineKeyboardButton(
                text="📝 Tavsif", callback_data=TariffCB(action="desc", tariff_id=tariff.id).pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="🗂 Toifalar cheklovi",
                callback_data=TariffCB(action="restr", tariff_id=tariff.id, value="c|0").pack(),
            ),
            InlineKeyboardButton(
                text="👥 Guruhlar cheklovi",
                callback_data=TariffCB(action="restr", tariff_id=tariff.id, value="g|0").pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="⏸ To'xtatish" if tariff.is_active else "▶️ Yoqish",
                callback_data=TariffCB(action="active", tariff_id=tariff.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬆️", callback_data=TariffCB(action="up", tariff_id=tariff.id).pack()
            ),
            InlineKeyboardButton(
                text="⬇️", callback_data=TariffCB(action="down", tariff_id=tariff.id).pack()
            ),
            InlineKeyboardButton(
                text="🗑 O'chirish", callback_data=TariffCB(action="delete", tariff_id=tariff.id).pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Ro'yxat", callback_data=TariffCB(action="list", value="0").pack()
            ),
            InlineKeyboardButton(
                text="🔄", callback_data=TariffCB(action="card", tariff_id=tariff.id).pack()
            ),
        ],
        [MENU_BUTTON],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_kb(tariff: Tariff, *, subs: int, payments: int) -> InlineKeyboardMarkup:
    warning = "🗑 Ha, o'chirish" if not (subs or payments) else "⏸ Ha, to'xtatish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            confirm_row(
                TariffCB(action="delete_confirm", tariff_id=tariff.id).pack(),
                TariffCB(action="card", tariff_id=tariff.id).pack(),
                confirm_text=warning,
            )
        ]
    )


def cancel_kb(tariff_id: int = 0) -> InlineKeyboardMarkup:
    back = (
        TariffCB(action="card", tariff_id=tariff_id).pack()
        if tariff_id
        else TariffCB(action="list", value="0").pack()
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data=back)]]
    )


__all__ = [
    "MENU_BUTTON",
    "cancel_kb",
    "delete_confirm_kb",
    "tariff_button",
    "tariff_card_kb",
    "tariffs_list_kb",
]
