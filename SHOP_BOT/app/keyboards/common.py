"""Umumiy klaviatura yordamchilari: sahifalash, tasdiqlash, bekor qilish."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

PER_PAGE_GROUPS = 6
PER_PAGE_CATEGORIES = 8
PER_PAGE_MATRIX = 5
PER_PAGE_SELLERS = 6
PER_PAGE_TARIFFS = 8


def nav_row(
    *,
    prev_data: str | None = None,
    next_data: str | None = None,
    page: int = 0,
    total_pages: int = 1,
    refresh_data: str | None = None,
) -> list[InlineKeyboardButton]:
    """Sahifalash qatori: ⬅️ <sahifa> ➡️  (kerak bo'lsa 🔄)."""
    row: list[InlineKeyboardButton] = []

    if total_pages > 1:
        if prev_data:
            row.append(InlineKeyboardButton(text="⬅️", callback_data=prev_data))
        row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data=refresh_data or prev_data or next_data or "noop",
            )
        )
        if next_data:
            row.append(InlineKeyboardButton(text="➡️", callback_data=next_data))

    if refresh_data:
        row.append(InlineKeyboardButton(text="🔄", callback_data=refresh_data))
    return row


def confirm_row(
    confirm_data: str,
    cancel_data: str,
    *,
    confirm_text: str = "✅ Ha, tasdiqlayman",
    cancel_text: str = "❌ Bekor qilish",
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text=confirm_text, callback_data=confirm_data),
        InlineKeyboardButton(text=cancel_text, callback_data=cancel_data),
    ]


def back_button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)
