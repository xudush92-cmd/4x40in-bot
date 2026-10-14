"""Toifalar bo'limi klaviaturalari (Phase 1)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Category, Group
from app.keyboards.callbacks import AdminCB, CategoryCB, GroupCB
from app.keyboards.common import confirm_row, nav_row
from app.utils.text import truncate

MENU_BUTTON = InlineKeyboardButton(
    text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack()
)


def category_button(category: Category, group_title: str | None) -> InlineKeyboardButton:
    emoji, = (category.emoji or "🗂",)
    mark = "" if group_title else " ⚠️"
    status = "" if category.is_active else " ⏸"
    return InlineKeyboardButton(
        text=f"{emoji} {truncate(category.name, 20)}{status}{mark}",
        callback_data=CategoryCB(action="card", category_id=category.id).pack(),
    )


def categories_list_kb(
    categories: list[Category],
    titles: dict[int, str | None],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [category_button(category, titles.get(category.id))] for category in categories
    ]

    rows.append(
        nav_row(
            prev_data=CategoryCB(action="list", value=str(page - 1)).pack() if page > 0 else None,
            next_data=CategoryCB(action="list", value=str(page + 1)).pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
            refresh_data=CategoryCB(action="list", value=str(page)).pack(),
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi toifa", callback_data=CategoryCB(action="create").pack()
            ),
            InlineKeyboardButton(
                text="🔀 Tartib", callback_data=CategoryCB(action="order", value="0").pack()
            ),
        ]
    )
    rows.append([MENU_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def category_card_kb(category: Category) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="✏️ Nomini o'zgartirish",
                callback_data=CategoryCB(action="rename", category_id=category.id).pack(),
            ),
            InlineKeyboardButton(
                text="📎 Guruh",
                callback_data=CategoryCB(action="group", category_id=category.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'🟢 Faol' if category.is_active else '⏸ To‘xtatilgan'}",
                callback_data=CategoryCB(action="active", category_id=category.id).pack(),
            ),
            InlineKeyboardButton(
                text=f"{'✅' if category.moderation_required else '⚪️'} Moderatsiya",
                callback_data=CategoryCB(action="moderation", category_id=category.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="⏱ Alohida interval",
                callback_data=CategoryCB(action="interval", category_id=category.id).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="⬆️", callback_data=CategoryCB(action="up", category_id=category.id).pack()
            ),
            InlineKeyboardButton(
                text="⬇️", callback_data=CategoryCB(action="down", category_id=category.id).pack()
            ),
            InlineKeyboardButton(
                text="🗑", callback_data=CategoryCB(action="delete", category_id=category.id).pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="◀️ Toifalar", callback_data=CategoryCB(action="list", value="0").pack()
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_choice_kb(
    groups: list[Group],
    category_id: int = 0,
    *,
    allow_none: bool = True,
    page: int = 0,
    total_pages: int = 1,
    action: str = "setgroup",
) -> InlineKeyboardMarkup:
    """Guruh tanlash (toifa yaratishda yoki biriktirishda)."""
    rows: list[list[InlineKeyboardButton]] = []

    for group in groups:
        status = "🟢" if group.is_active else "⏸"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {truncate(group.display, 30)}",
                    callback_data=CategoryCB(
                        action=action, category_id=category_id, value=str(group.id)
                    ).pack(),
                )
            ]
        )

    rows.append(
        nav_row(
            prev_data=CategoryCB(action=action, category_id=category_id, value=f"page:{page - 1}").pack()
            if page > 0
            else None,
            next_data=CategoryCB(action=action, category_id=category_id, value=f"page:{page + 1}").pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
        )
    )

    if allow_none:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏭ Guruhsiz saqlash",
                    callback_data=CategoryCB(
                        action=action, category_id=category_id, value="none"
                    ).pack(),
                )
            ]
        )

    if category_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="◀️ Toifa",
                    callback_data=CategoryCB(action="card", category_id=category_id).pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="◀️ Toifalar", callback_data=CategoryCB(action="list", value="0").pack()
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def order_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    """Tartibni o'zgartirish ekrani: har toifa uchun ⬆️/⬇️."""
    rows: list[list[InlineKeyboardButton]] = []
    for index, category in enumerate(categories):
        emoji = category.emoji or "🗂"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{index + 1}. {emoji} {truncate(category.name, 18)}",
                    callback_data=CategoryCB(action="card", category_id=category.id).pack(),
                ),
                InlineKeyboardButton(
                    text="⬆️",
                    callback_data=CategoryCB(action="order_up", category_id=category.id).pack(),
                ),
                InlineKeyboardButton(
                    text="⬇️",
                    callback_data=CategoryCB(action="order_down", category_id=category.id).pack(),
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Tayyor", callback_data=CategoryCB(action="list", value="0").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_kb(category_id: int, *, ads: int = 0) -> InlineKeyboardMarkup:
    confirm_text = f"🗑 Ha, o'chirish ({ads} e'lon bilan)" if ads else "🗑 Ha, o'chirish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            confirm_row(
                confirm_data=CategoryCB(action="delete_confirm", category_id=category_id).pack(),
                cancel_data=CategoryCB(action="card", category_id=category_id).pack(),
                confirm_text=confirm_text,
            )
        ]
    )


def cancel_create_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data=CategoryCB(action="list", value="0").pack()
                )
            ]
        ]
    )


def cancel_edit_kb(category_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=CategoryCB(action="card", category_id=category_id).pack(),
                )
            ]
        ]
    )


def group_categories_kb(group_id: int, categories: list[Category]) -> InlineKeyboardMarkup:
    """Guruh kartasidan: shu guruhga biriktirilgan toifalar."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{category.emoji or '🗂'} {truncate(category.name, 26)}",
                callback_data=CategoryCB(action="card", category_id=category.id).pack(),
            )
        ]
        for category in categories
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Toifa qo'shish (guruhga biriktirilgan)",
                callback_data=CategoryCB(action="create", value=str(group_id)).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Guruh kartasi",
                callback_data=GroupCB(action="card", group_id=group_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
