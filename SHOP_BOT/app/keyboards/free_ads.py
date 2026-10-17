"""Shaxsiy guruh tanlash/bepul e'lon va moderator qarorlari."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import FreeAd, Group
from app.keyboards.callbacks import FreeCB, FreeModCB
from app.utils.text import truncate


def group_list_kb(groups: list[Group]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=truncate(group.display, 55), callback_data=FreeCB(action="group", group_id=group.id).pack(),
    )] for group in groups]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choice_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Bepul e'lon", callback_data=FreeCB(
            action="card", group_id=group_id,
        ).pack())],
        [InlineKeyboardButton(text="💳 Pullik imkoniyat", callback_data=FreeCB(
            action="paid", group_id=group_id,
        ).pack())],
        [InlineKeyboardButton(text="◀️ Guruhlar", callback_data=FreeCB(action="list").pack())],
    ])


def free_card_kb(group_id: int, ad: FreeAd | None, *, can_submit: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_submit:
        rows.append([InlineKeyboardButton(
            text="📷 E'lonni yuborish / almashtirish" if ad else "📷 E'lonni yuborish",
            callback_data=FreeCB(action="photo", group_id=group_id).pack(),
        )])
    if ad:
        rows.append([InlineKeyboardButton(
            text="⏹ To'xtatish" if ad.desired_running else "▶️ Boshlash",
            callback_data=FreeCB(action="stop" if ad.desired_running else "start",
                                 group_id=group_id).pack(),
        )])
    rows.extend([
        [InlineKeyboardButton(text="🔄 Holatni tekshirish", callback_data=FreeCB(
            action="card", group_id=group_id,
        ).pack())],
        [InlineKeyboardButton(text="◀️ Shartlar", callback_data=FreeCB(
            action="group", group_id=group_id,
        ).pack())],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Adminga yuborish", callback_data=FreeCB(
            action="submit", group_id=group_id,
        ).pack())],
        [InlineKeyboardButton(text="↩️ Boshqa surat", callback_data=FreeCB(
            action="photo", group_id=group_id,
        ).pack())],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=FreeCB(
            action="cancel", group_id=group_id,
        ).pack())],
    ])


def free_pending_kb(ads: list[FreeAd], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{'🕓' if ad.review_status == 'pending' else '✅'} #{ad.id} · guruh #{ad.group_id}",
        callback_data=FreeModCB(action="card", ad_id=ad.id).pack(),
    )] for ad in ads]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=FreeModCB(
                action="list", page=page - 1,
            ).pack()))
        if page + 1 < pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=FreeModCB(
                action="list", page=page + 1,
            ).pack()))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data=FreeModCB(
        action="list", page=page,
    ).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def free_review_kb(ad: FreeAd) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=FreeModCB(
            action="approve", ad_id=ad.id, revision=ad.revision,
        ).pack()),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=FreeModCB(
             action="reject", ad_id=ad.id, revision=ad.revision,
         ).pack())],
        [InlineKeyboardButton(text="◀️ Navbat", callback_data=FreeModCB(
            action="list",
        ).pack())],
    ])


def free_revoke_kb(ad: FreeAd, *, confirm: bool = False) -> InlineKeyboardMarkup:
    action = "revoke" if confirm else "revoke_confirm"
    rows = [[InlineKeyboardButton(
        text="⚠️ HA, tasdiqni bekor qilish" if confirm else "🚫 Tasdiqni bekor qilish",
        callback_data=FreeModCB(action=action, ad_id=ad.id, revision=ad.revision).pack(),
    )]]
    rows.append([InlineKeyboardButton(
        text="◀️ E'lon kartasi" if confirm else "◀️ Ro'yxat",
        callback_data=FreeModCB(action="card" if confirm else "list", ad_id=ad.id).pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
