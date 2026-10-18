"""📢 E'lon klaviaturalari: sotuvchi ro'yxati, kartochka, usta va tahrir.

Callback'lar juda qisqa (64 bayt chegarasi): `ad:<action>:<ad_id>:<value>`.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import AdStatus
from app.db.models import Ad, Category
from app.keyboards.callbacks import AdCB, SellerPanelCB
from app.keyboards.common import nav_row
from app.services.ad_service import filter_label
from app.utils.text import truncate

# Usta qadamlarida ko'rinadigan tugmalar
WIZARD_FILTERS: list[tuple[str, str]] = [
    ("all", "Hammasi"),
    ("active", "🟢 Faol"),
    ("pending", "🕓 Tekshiruvda"),
    ("draft", "✏️ Qoralama"),
    ("paused", "⏸ To'xtatilgan"),
    ("rejected", "❌ Rad etilgan"),
]


def filters_row(*, current: str = "all", ad_id: int = 0, per_row: int = 3) -> list[list[InlineKeyboardButton]]:
    """Holat filtri tugmalari (2 qator)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for key, label in WIZARD_FILTERS:
        mark = "· " if key == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{label}",
                callback_data=AdCB(action="filter", ad_id=ad_id, value=key).pack(),
            )
        )
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def ads_list_kb(
    ads: list[Ad],
    *,
    page: int,
    total_pages: int,
    status: str = "all",
    can_create_ad: bool = True,
) -> InlineKeyboardMarkup:
    """«Mening e'lonlarim» ro'yxati: ro'yxat tarifsiz ham ko'rinadi."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_create_ad:
        rows.append([InlineKeyboardButton(text="➕ Yangi e'lon",
                                         callback_data=AdCB(action="new").pack())])

    for ad in ads:
        badge = {
            AdStatus.DRAFT: "✏️",
            AdStatus.PENDING: "🕓",
            AdStatus.ACTIVE: "🟢",
            AdStatus.PAUSED: "⏸",
            AdStatus.REJECTED: "❌",
            AdStatus.EXPIRED: "⌛️",
        }.get(ad.status, "•")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{badge} {truncate(ad.title or '(nomsiz)', 34)}",
                    callback_data=AdCB(action="card", ad_id=ad.id, value=f"{page}|{status}").pack(),
                )
            ]
        )

    nav = nav_row(
        prev_data=AdCB(action="list", value=f"{page - 1}|{status}").pack() if page > 0 else None,
        next_data=(
            AdCB(action="list", value=f"{page + 1}|{status}").pack() if page + 1 < total_pages else None
        ),
        page=page,
        total_pages=total_pages,
        refresh_data=AdCB(action="list", value=f"{page}|{status}").pack(),
    )
    if nav:
        rows.append(nav)

    rows.extend(filters_row(current=status))
    rows.append([InlineKeyboardButton(text="◀️ Kabinetga",
                                      callback_data=SellerPanelCB(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ad_card_kb(ad: Ad, *, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    """E'lon kartochkasi (sotuvchi)."""
    back = AdCB(action="list", value=f"{page}|{status}").pack()
    rows: list[list[InlineKeyboardButton]] = []

    if ad.status == AdStatus.DRAFT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Tahrirlash",
                    callback_data=AdCB(action="edit", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
                InlineKeyboardButton(
                    text="✅ Yuborish",
                    callback_data=AdCB(action="send", ad_id=ad.id).pack(),
                ),
            ]
        )
    elif ad.status == AdStatus.REJECTED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Tahrirlab qayta yuborish",
                    callback_data=AdCB(action="edit", ad_id=ad.id, value=f"{page}|{status}").pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Tahrirlash",
                    callback_data=AdCB(action="edit", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
                InlineKeyboardButton(
                    text="🖼 Rasmlar",
                    callback_data=AdCB(action="photos", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
            ]
        )

    if ad.status == AdStatus.ACTIVE:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏸ Pauza",
                    callback_data=AdCB(action="pause", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
                InlineKeyboardButton(
                    text="📊 Statistika",
                    callback_data=AdCB(action="stats", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
            ]
        )
    elif ad.status == AdStatus.PAUSED and not ad.admin_paused:
        rows.append(
            [
                InlineKeyboardButton(
                    text="▶️ Boshlash",
                    callback_data=AdCB(action="resume", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
                InlineKeyboardButton(
                    text="📊 Statistika",
                    callback_data=AdCB(action="stats", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
            ]
        )

    elif ad.status == AdStatus.PAUSED:
        rows.append([InlineKeyboardButton(
            text="📊 Statistika",
            callback_data=AdCB(action="stats", ad_id=ad.id, value=f"{page}|{status}").pack(),
        )])

    if ad.status != AdStatus.DELETED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=AdCB(action="delete", ad_id=ad.id, value=f"{page}|{status}").pack(),
                )
            ]
        )

    rows.append([InlineKeyboardButton(text="◀️ Ro'yxatga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ad_delete_confirm_kb(ad: Ad, *, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o'chirish",
                    callback_data=AdCB(action="delete_confirm", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Bekor",
                    callback_data=AdCB(action="card", ad_id=ad.id, value=f"{page}|{status}").pack(),
                ),
            ]
        ]
    )


def categories_kb(categories: list[Category], *, ad_id: int | None = None) -> InlineKeyboardMarkup:
    """Usta 1-qadami: toifa tanlash (faqat guruhga biriktirilgan faol toifalar)."""
    rows: list[list[InlineKeyboardButton]] = []
    for category in categories:
        title = category.name if not category.emoji else f"{category.emoji} {category.name}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=truncate(title, 50),
                    callback_data=AdCB(action="wiz_cat", ad_id=ad_id or 0, value=str(category.id)).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=AdCB(action="wiz_cancel", ad_id=ad_id or 0).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wizard_step_kb(*, ad_id: int, back: str | None = None, skip: bool = False) -> InlineKeyboardMarkup:
    """Usta qadamlari uchun navigatsiya: ⬅️ Orqaga / ⏭ O'tkazib yuborish / ❌ Bekor."""
    rows: list[list[InlineKeyboardButton]] = []
    middle: list[InlineKeyboardButton] = []
    if back:
        middle.append(
            InlineKeyboardButton(
                text="⬅️ Orqaga", callback_data=AdCB(action="wiz_back", ad_id=ad_id, value=back).pack()
            )
        )
    if skip:
        middle.append(
            InlineKeyboardButton(
                text="⏭ O'tkazib yuborish", callback_data=AdCB(action="wiz_skip", ad_id=ad_id).pack()
            )
        )
    if middle:
        rows.append(middle)
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish", callback_data=AdCB(action="wiz_cancel", ad_id=ad_id).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photos_kb(*, ad_id: int, count: int, limit: int, from_edit: bool = False) -> InlineKeyboardMarkup:
    """Rasm qadami: ✅ Tayyor (+ tahrirda orqaga)."""
    rows: list[list[InlineKeyboardButton]] = []
    if count == 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data=AdCB(action="wiz_cancel", ad_id=ad_id).pack()
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    ready = f"✅ Tayyor ({count}/{limit})"
    button = InlineKeyboardButton(
        text=ready, callback_data=AdCB(action="wiz_done", ad_id=ad_id).pack()
    )
    if from_edit:
        rows.append(
            [
                button,
                InlineKeyboardButton(
                    text="🗑 Oxirgisini o'chirish",
                    callback_data=AdCB(action="photo_del", ad_id=ad_id, value=str(count - 1)).pack(),
                ),
            ]
        )
    else:
        rows.append([button])

    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish", callback_data=AdCB(action="wiz_cancel", ad_id=ad_id).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preview_kb(*, ad_id: int, from_edit: bool = False,
               can_submit: bool = True) -> InlineKeyboardMarkup:
    """Faqat qoralama yuboriladi; tasdiqlangan/tahrirdagi e'lon slotni takror sarflamaydi."""
    rows = [[InlineKeyboardButton(
        text="📤 Yuborish", callback_data=AdCB(action="wiz_send", ad_id=ad_id).pack(),
    )]] if can_submit else []
    if from_edit:
        rows.insert(
            0,
            [
                InlineKeyboardButton(
                    text="✏️ Tahrirlash", callback_data=AdCB(action="edit", ad_id=ad_id).pack()
                )
            ],
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish", callback_data=AdCB(action="wiz_cancel", ad_id=ad_id).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_kb(ad: Ad, *, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    """Tahrirlash menyusi: har maydon alohida."""
    back = f"{page}|{status}"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="✏️ Sarlavha",
                callback_data=AdCB(action="e_title", ad_id=ad.id, value=back).pack(),
            ),
            InlineKeyboardButton(
                text="💰 Narx",
                callback_data=AdCB(action="e_price", ad_id=ad.id, value=back).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="📝 Tavsif",
                callback_data=AdCB(action="e_desc", ad_id=ad.id, value=back).pack(),
            ),
            InlineKeyboardButton(
                text="☎️ Aloqa",
                callback_data=AdCB(action="e_contact", ad_id=ad.id, value=back).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="🗂 Toifani almashtirish",
                callback_data=AdCB(action="e_cat", ad_id=ad.id, value=back).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="🖼 Rasmlar",
                callback_data=AdCB(action="photos", ad_id=ad.id, value=back).pack(),
            )
        ],
    ]
    if ad.status == AdStatus.DRAFT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Yuborish",
                    callback_data=AdCB(action="send", ad_id=ad.id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="👀 Ko'rish", callback_data=AdCB(action="preview", ad_id=ad.id, value=back).pack()
            ),
            InlineKeyboardButton(
                text="◀️ Kartochka",
                callback_data=AdCB(action="card", ad_id=ad.id, value=back).pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_kb(*, ad_id: int) -> InlineKeyboardMarkup:
    """Aloqa qadami: turini tanlash yoki o'tkazib yuborish."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 @username", callback_data=AdCB(action="c_type", ad_id=ad_id, value="username").pack()
                ),
                InlineKeyboardButton(
                    text="📞 Telefon", callback_data=AdCB(action="c_type", ad_id=ad_id, value="phone").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Havola (URL)", callback_data=AdCB(action="c_type", ad_id=ad_id, value="url").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Profildagidan foydalanish",
                    callback_data=AdCB(action="wiz_skip", ad_id=ad_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data=AdCB(action="wiz_cancel", ad_id=ad_id).pack()
                )
            ],
        ]
    )


def back_to_ads_kb(*, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Mening e'lonlarim",
                    callback_data=AdCB(action="list", value=f"{page}|{status}").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛒 Sotuvchi paneli",
                    callback_data="sp:menu:-",
                )
            ],
        ]
    )


CONTACT_TYPE_LABELS = {"username": "👤 @username", "phone": "📞 Telefon", "url": "🔗 Havola"}


def contact_type_label(value: str | None) -> str:
    return CONTACT_TYPE_LABELS.get(value or "", "—")


def status_filter_title(status: str) -> str:
    return f"🔎 Filtr: <b>{filter_label(status)}</b>"


__all__ = [
    "CONTACT_TYPE_LABELS",
    "ad_card_kb",
    "ad_delete_confirm_kb",
    "ads_list_kb",
    "back_to_ads_kb",
    "categories_kb",
    "contact_kb",
    "contact_type_label",
    "edit_kb",
    "filters_row",
    "photos_kb",
    "preview_kb",
    "status_filter_title",
    "wizard_step_kb",
]
