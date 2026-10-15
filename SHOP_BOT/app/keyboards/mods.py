"""✅ Moderatsiya va 📢 E'lonlar klaviaturalari (admin tomoni).

Callback: `mod:<action>:<ad_id>:<value>` — 64 bayt chegarasiga sig'adi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Ad, Seller
from app.keyboards.callbacks import ModCB
from app.keyboards.common import nav_row
from app.services import ad_service
from app.utils.text import truncate

# Admin e'lonlar ro'yxati filtri
ADMIN_FILTERS: list[tuple[str, str]] = [
    ("pending", "🕓 Tekshiruvda"),
    ("active", "🟢 Faol"),
    ("paused", "⏸ To'xtatilgan"),
    ("rejected", "❌ Rad etilgan"),
    ("archived", "🗑 Arxiv"),
    ("all", "Hammasi"),
]

REJECT_REASONS: list[tuple[str, str]] = [
    ("spam", "🚫 Reklama/spam"),
    ("rules", "📜 Guruh qoidalariga zid"),
    ("photo", "🖼 Rasm sifatsiz/nomaqbul"),
    ("price", "💰 Narx noto'g'ri ko'rsatilgan"),
    ("dup", "♻️ Takroriy e'lon"),
    ("other", "✍️ Boshqa (o'zim yozaman)"),
]


def pending_list_kb(ads: list[Ad], *, page: int, total_pages: int) -> InlineKeyboardMarkup:
    """🕓 Tekshiruv kutayotgan e'lonlar ro'yxati."""
    rows: list[list[InlineKeyboardButton]] = []
    for ad in ads:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🕓 #{ad.id} {truncate(ad.title or '(nomsiz)', 30)}",
                    callback_data=ModCB(action="card", ad_id=ad.id, value=f"{page}|pending").pack(),
                )
            ]
        )

    nav = nav_row(
        prev_data=ModCB(action="list", value=f"{page - 1}|pending").pack() if page > 0 else None,
        next_data=(
            ModCB(action="list", value=f"{page + 1}|pending").pack() if page + 1 < total_pages else None
        ),
        page=page,
        total_pages=total_pages,
        refresh_data=ModCB(action="list", value=f"{page}|pending").pack(),
    )
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(
                text="📢 Barcha e'lonlar", callback_data=ModCB(action="ads", value="0|all").pack()
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🛠 Boshqaruv paneli", callback_data="adm:menu:-"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_card_kb(ad: Ad, *, page: int = 0) -> InlineKeyboardMarkup:
    """Moderatsiya kartochkasi: tasdiqlash / rad etish."""
    back = f"{page}|pending"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash",
                    callback_data=ModCB(action="approve", ad_id=ad.id, value=back).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=ModCB(action="reject", ad_id=ad.id, value=back).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🕓 Ro'yxatga", callback_data=ModCB(action="list", value=back).pack()
                ),
                InlineKeyboardButton(
                    text="📊 E'lon kartochkasi",
                    callback_data=ModCB(action="ads_card", ad_id=ad.id, value=back).pack(),
                ),
            ],
        ]
    )


def reject_reasons_kb(ad: Ad, *, page: int = 0) -> InlineKeyboardMarkup:
    """Rad etish sabablari (tayyor + o'zim yozaman)."""
    rows: list[list[InlineKeyboardButton]] = []
    for key, label in REJECT_REASONS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=ModCB(action="reason", ad_id=ad.id, value=f"{key}|{page}").pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Bekor", callback_data=ModCB(action="card", ad_id=ad.id, value=f"{page}|pending").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb(ad_id: int = 0, *, action: str = "list", value: str = "0|pending") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data=ModCB(action=action, ad_id=ad_id, value=value).pack()
                )
            ]
        ]
    )


def admin_ads_list_kb(
    ads: list[Ad],
    *,
    page: int,
    total_pages: int,
    status: str = "all",
    current: str = "all",
) -> InlineKeyboardMarkup:
    """📢 Barcha e'lonlar (admin) — holat bo'yicha filtr bilan."""
    rows: list[list[InlineKeyboardButton]] = []
    for ad in ads:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{ad_service.status_badge(ad.status)} #{ad.id} "
                    f"{truncate(ad.title or '(nomsiz)', 28)}",
                    callback_data=ModCB(action="ads_card", ad_id=ad.id, value=f"{page}|{status}").pack(),
                )
            ]
        )

    nav = nav_row(
        prev_data=ModCB(action="ads", value=f"{page - 1}|{status}").pack() if page > 0 else None,
        next_data=(
            ModCB(action="ads", value=f"{page + 1}|{status}").pack() if page + 1 < total_pages else None
        ),
        page=page,
        total_pages=total_pages,
        refresh_data=ModCB(action="ads", value=f"{page}|{status}").pack(),
    )
    if nav:
        rows.append(nav)

    # Filtr tugmalari (2 qatorda)
    chunk: list[InlineKeyboardButton] = []
    for key, label in ADMIN_FILTERS:
        mark = "· " if key == current else ""
        chunk.append(
            InlineKeyboardButton(
                text=f"{mark}{label}",
                callback_data=ModCB(action="ads", value=f"0|{key}").pack(),
            )
        )
        if len(chunk) == 2:
            rows.append(chunk)
            chunk = []
    if chunk:
        rows.append(chunk)

    rows.append(
        [
            InlineKeyboardButton(text="✅ Moderatsiya", callback_data=ModCB(action="list", value="0|pending").pack()),
            InlineKeyboardButton(text="🛠 Panel", callback_data="adm:menu:-"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ad_card_kb(ad: Ad, *, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    """Admin e'lon kartochkasi: tasdiq/rad, pauza, o'chirish."""
    back = f"{page}|{status}"
    rows: list[list[InlineKeyboardButton]] = []

    if ad.status == "pending":
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=ModCB(action="approve", ad_id=ad.id, value=back).pack()
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=ModCB(action="reject", ad_id=ad.id, value=back).pack()
                ),
            ]
        )

    actions: list[InlineKeyboardButton] = []
    if ad.status == "active":
        actions.append(
            InlineKeyboardButton(
                text="⏸ To'xtatish", callback_data=ModCB(action="pause", ad_id=ad.id, value=back).pack()
            )
        )
    elif ad.status == "paused":
        actions.append(
            InlineKeyboardButton(
                text="▶️ Yoqish", callback_data=ModCB(action="resume", ad_id=ad.id, value=back).pack()
            )
        )
    if ad.status not in ("deleted",):
        actions.append(
            InlineKeyboardButton(
                text="🗑 O'chirish", callback_data=ModCB(action="delete", ad_id=ad.id, value=back).pack()
            )
        )
    if actions:
        rows.append(actions)

    rows.append(
        [
            InlineKeyboardButton(
                text="🕘 Moderatsiya tarixi",
                callback_data=ModCB(action="history", ad_id=ad.id, value=back).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="◀️ Ro'yxatga", callback_data=ModCB(action="ads", value=back).pack()),
            InlineKeyboardButton(text="✅ Moderatsiya", callback_data=ModCB(action="list", value="0|pending").pack()),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ad_delete_confirm_kb(ad: Ad, *, page: int = 0, status: str = "all") -> InlineKeyboardMarkup:
    back = f"{page}|{status}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o'chirish",
                    callback_data=ModCB(action="delete_confirm", ad_id=ad.id, value=back).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Bekor", callback_data=ModCB(action="ads_card", ad_id=ad.id, value=back).pack()
                ),
            ]
        ]
    )


def seller_label_kb(seller: Seller) -> str:
    """Kartochkada sotuvchini ko'rsatish uchun qisqa nom."""
    return truncate(seller.display_name or f"ID {seller.user_id}", 40)


__all__ = [
    "ADMIN_FILTERS",
    "REJECT_REASONS",
    "ad_delete_confirm_kb",
    "admin_ad_card_kb",
    "admin_ads_list_kb",
    "cancel_kb",
    "moderation_card_kb",
    "pending_list_kb",
    "reject_reasons_kb",
    "seller_label_kb",
]
