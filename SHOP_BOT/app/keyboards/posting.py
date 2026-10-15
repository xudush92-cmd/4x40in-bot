"""Phase 4: toifa bo'yicha navbatni ko'rish va tartibni o'zgartirish."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import AdStatus
from app.db.models import Ad, Category
from app.keyboards.callbacks import GroupCB, ModCB, PostingCB
from app.keyboards.common import nav_row
from app.utils.text import truncate


def group_queue_kb(group_id: int, categories: list[Category]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{category.emoji or '🗂'} {truncate(category.name, 30)}",
        callback_data=PostingCB(action="queue", target_id=category.id).pack(),
    )] for category in categories]
    rows.append([InlineKeyboardButton(
        text="◀️ Guruh kartasi", callback_data=GroupCB(action="card", group_id=group_id).pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_queue_kb(category: Category, ads: list[Ad], *, page: int, pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ad in ads:
        rows.append([InlineKeyboardButton(
            text=f"{'🟢' if ad.status == AdStatus.ACTIVE else '⏸'} #{ad.id} {truncate(ad.title, 25)}",
            callback_data=ModCB(action="ads_card", ad_id=ad.id, value="0|all").pack(),
        )])
        buttons = []
        for direction, label in (("up", "⬆️"), ("down", "⬇️")):
            buttons.append(InlineKeyboardButton(
                text=label,
                callback_data=PostingCB(
                    action=direction, target_id=ad.id, value=f"{category.id}|{page}"
                ).pack(),
            ))
        if ad.status == AdStatus.ACTIVE:
            buttons.append(InlineKeyboardButton(
                text="🚀 Hoziroq", callback_data=PostingCB(action="send", target_id=ad.id).pack(),
            ))
        rows.append(buttons)
    nav = nav_row(
        prev_data=PostingCB(action="queue", target_id=category.id, value=str(page - 1)).pack() if page else None,
        next_data=PostingCB(action="queue", target_id=category.id, value=str(page + 1)).pack() if page + 1 < pages else None,
        page=page, total_pages=pages,
        refresh_data=PostingCB(action="queue", target_id=category.id, value=str(page)).pack(),
    )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(
        text="◀️ Guruh navbati",
        callback_data=PostingCB(action="group", target_id=category.group_id or 0).pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
