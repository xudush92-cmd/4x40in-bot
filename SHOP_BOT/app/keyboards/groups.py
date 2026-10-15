"""Guruhlar bo'limi klaviaturalari (Phase 1)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import FEATURE_LABELS, FEATURE_SHORT
from app.db.models import Group
from app.keyboards.callbacks import AdminCB, FeatureCB, GroupCB, PostingCB
from app.keyboards.common import confirm_row, nav_row
from app.utils.text import human_int, truncate

MENU_BUTTON = InlineKeyboardButton(
    text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack()
)

# Matritsada ko'rsatiladigan funksiyalar
MATRIX_FEATURES = ("posting", "counter", "guard", "cleaner")


def group_button(group: Group) -> InlineKeyboardButton:
    """Ro'yxatdagi bitta guruh tugmasi."""
    status = "🟢" if group.is_active else "⏸"
    admin_mark = "" if group.bot_is_admin else " ⚠️"
    members = f" · 👤 {human_int(group.member_count)}" if group.member_count else ""
    label = f"{status} {truncate(group.display, 24)}{admin_mark}{members}"
    return InlineKeyboardButton(
        text=label, callback_data=GroupCB(action="card", group_id=group.id).pack()
    )


def groups_list_kb(groups: list[Group], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[group_button(group)] for group in groups]

    rows.append(
        nav_row(
            prev_data=GroupCB(action="list", value=str(page - 1)).pack() if page > 0 else None,
            next_data=GroupCB(action="list", value=str(page + 1)).pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
            refresh_data=GroupCB(action="list", value=str(page)).pack(),
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Guruh qo'shish", callback_data=GroupCB(action="add").pack()
            ),
            InlineKeyboardButton(
                text="🎛 Matritsa", callback_data=GroupCB(action="matrix", value="0").pack()
            ),
        ]
    )
    rows.append([MENU_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def add_group_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ro'yxatni yangilash", callback_data=GroupCB(action="list", value="0").pack())],
            [MENU_BUTTON],
        ]
    )


def group_card_kb(group: Group) -> InlineKeyboardMarkup:
    """Guruh kartasi: holat va asosiy amallar."""
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(
                text="⏸ To'xtatish" if group.is_active else "▶️ Yoqish",
                callback_data=GroupCB(action="pause", group_id=group.id).pack(),
            ),
            InlineKeyboardButton(
                text="🧩 Funksiyalar",
                callback_data=GroupCB(action="feats", group_id=group.id).pack(),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="⚙️ Sozlamalar",
                callback_data=GroupCB(action="settings", group_id=group.id).pack(),
            ),
            InlineKeyboardButton(
                text="🗂 Toifalar",
                callback_data=GroupCB(action="cats", group_id=group.id, value="0").pack(),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="📋 E'lonlar navbati",
                callback_data=PostingCB(action="group", target_id=group.id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔍 Huquqlarni tekshirish",
                callback_data=GroupCB(action="refresh", group_id=group.id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Guruhni o'chirish",
                callback_data=GroupCB(action="delete", group_id=group.id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Guruhlar",
                callback_data=GroupCB(action="list", value="0").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_features_kb(group: Group) -> InlineKeyboardMarkup:
    """Funksiya tumbleri ekrani."""
    settings = group.settings
    rows: list[list[InlineKeyboardButton]] = []

    for feature, label in FEATURE_LABELS.items():
        enabled = bool(getattr(settings, f"{feature}_enabled", False)) if settings else False
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if enabled else '🔴'} {label}",
                    callback_data=FeatureCB(
                        group_id=group.id,
                        feature=str(feature),
                        enabled=not enabled,
                        origin="feats",
                    ).pack(),
                )
            ]
        )

    if settings is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if settings.protect_content else '🔴'} 🖼 Kontentni himoya qilish",
                    callback_data=GroupCB(action="toggle", group_id=group.id, value="protect").pack(),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Guruh kartasi",
                callback_data=GroupCB(action="card", group_id=group.id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_settings_kb(group: Group, *, old_ads_enabled: bool = False) -> InlineKeyboardMarkup:
    """Interval, jitter, kunlik limit, tinch soatlar."""
    settings = group.settings
    quiet_on = bool(settings and settings.quiet_start and settings.quiet_end)

    rows = [
        [
            InlineKeyboardButton(
                text="⏱ Joylash intervali",
                callback_data=GroupCB(action="interval", group_id=group.id).pack(),
            ),
            InlineKeyboardButton(
                text="🔀 Jitter (±%)",
                callback_data=GroupCB(action="jitter", group_id=group.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="📆 Kunlik limit",
                callback_data=GroupCB(action="limit", group_id=group.id).pack(),
            ),
            InlineKeyboardButton(
                text=f"{'🌙' if quiet_on else '☀️'} Tinch soatlar",
                callback_data=GroupCB(action="quiet", group_id=group.id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'🟢' if (settings and settings.welcome_enabled) else '🔴'} 👋 Salomlashuv",
                callback_data=FeatureCB(
                    group_id=group.id,
                    feature="welcome",
                    enabled=not (settings and settings.welcome_enabled),
                    origin="settings",
                ).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'🟢' if old_ads_enabled else '🔴'} 🧹 Eski e'lon nusxalarini o'chirish",
                callback_data=GroupCB(action="old_ads", group_id=group.id).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="◀️ Guruh kartasi",
                callback_data=GroupCB(action="card", group_id=group.id).pack(),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def matrix_kb(groups: list[Group], page: int, total_pages: int) -> InlineKeyboardMarkup:
    """🎛 Matritsa: guruhlar × funksiyalar (bir tugma bilan yoqish/o'chirish)."""
    rows: list[list[InlineKeyboardButton]] = []

    for group in groups:
        settings = group.settings
        rows.append([group_button(group)])

        feature_row: list[InlineKeyboardButton] = []
        for feature in MATRIX_FEATURES:
            enabled = bool(getattr(settings, f"{feature}_enabled", False)) if settings else False
            feature_row.append(
                InlineKeyboardButton(
                    text=f"{FEATURE_SHORT.get(feature, '')}{'✅' if enabled else '⬜️'}",
                    callback_data=FeatureCB(
                        group_id=group.id,
                        feature=feature,
                        enabled=not enabled,
                        origin="matrix",
                        page=page,
                    ).pack(),
                )
            )
        rows.append(feature_row)

    rows.append(
        nav_row(
            prev_data=GroupCB(action="matrix", value=str(page - 1)).pack() if page > 0 else None,
            next_data=GroupCB(action="matrix", value=str(page + 1)).pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
            refresh_data=GroupCB(action="matrix", value=str(page)).pack(),
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Guruhlar", callback_data=GroupCB(action="list", value="0").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def delete_confirm_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            confirm_row(
                confirm_data=GroupCB(action="delete_confirm", group_id=group_id).pack(),
                cancel_data=GroupCB(action="card", group_id=group_id).pack(),
                confirm_text="🗑 Ha, o'chirish",
            )
        ]
    )


def cancel_kb(group_id: int, *, back_action: str = "card") -> InlineKeyboardMarkup:
    """FSM kiritish jarayonidan chiqish."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=GroupCB(action=back_action, group_id=group_id).pack(),
                )
            ]
        ]
    )
