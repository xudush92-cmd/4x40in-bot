"""Sotuvchilar bo'limi klaviaturalari (Phase 2)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import SellerStatus
from app.db.models import Seller
from app.keyboards.callbacks import AdminCB, SellerCB, TariffCB
from app.keyboards.common import confirm_row, nav_row
from app.services.seller_service import seller_label

MENU_BUTTON = InlineKeyboardButton(
    text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack()
)

# Filtr tugmalari: (kalit, matn)
FILTERS: tuple[tuple[str | None, str], ...] = (
    (None, "Hammasi"),
    (SellerStatus.PENDING, "🕓 Tarifsiz"),
    (SellerStatus.ACTIVE, "🟢 Faol"),
    (SellerStatus.BLOCKED, "🚫 Bloklangan"),
)


def seller_button(seller: Seller, *, active: bool = True) -> InlineKeyboardButton:
    """Ro'yxatdagi bitta sotuvchi tugmasi."""
    if seller.status == SellerStatus.BLOCKED:
        mark = "🚫"
    elif seller.status == SellerStatus.PENDING:
        mark = "🕓"
    else:
        mark = "🟢" if active else "🟠"
    verified = " ✅" if seller.is_verified else ""
    return InlineKeyboardButton(
        text=f"{mark} {seller_label(seller, 22)}{verified}",
        callback_data=SellerCB(action="card", seller_id=seller.id).pack(),
    )


def sellers_list_kb(
    sellers: list[Seller],
    page: int,
    total_pages: int,
    *,
    status: str | None = None,
    active_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    """Sotuvchilar ro'yxati + filtr + sahifalash."""
    active_ids = active_ids or set()
    rows: list[list[InlineKeyboardButton]] = [
        [seller_button(seller, active=seller.id in active_ids)] for seller in sellers
    ]

    # Filtr qatori
    filter_row: list[InlineKeyboardButton] = []
    for key, label in FILTERS:
        current = (status or None) == key
        prefix = "• " if current else ""
        filter_row.append(
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=SellerCB(action="filter", value=key or "all").pack(),
            )
        )
    rows.append(filter_row)

    rows.append(
        nav_row(
            prev_data=SellerCB(action="list", value=f"{page - 1}|{status or 'all'}").pack()
            if page > 0
            else None,
            next_data=SellerCB(action="list", value=f"{page + 1}|{status or 'all'}").pack()
            if page + 1 < total_pages
            else None,
            page=page,
            total_pages=total_pages,
            refresh_data=SellerCB(action="list", value=f"{page}|{status or 'all'}").pack(),
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Sotuvchi qo'shish", callback_data=SellerCB(action="add").pack()
            )
        ]
    )
    rows.append([MENU_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seller_card_kb(seller: Seller, *, has_subscription: bool, page: int = 0, status: str | None = None) -> InlineKeyboardMarkup:
    """Sotuvchi kartochkasi: obuna, blok, tasdiqlash, tahrir."""
    back = SellerCB(action="list", value=f"{page}|{status or 'all'}").pack()
    rows: list[list[InlineKeyboardButton]] = []

    if has_subscription:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Muddatni uzaytirish (+30 kun)",
                    callback_data=SellerCB(action="extend", seller_id=seller.id, value="30").pack(),
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏱ Muddat qo'lda", callback_data=SellerCB(action="days", seller_id=seller.id).pack()
                ),
                InlineKeyboardButton(
                    text="📢 Limit qo'lda", callback_data=SellerCB(action="limit", seller_id=seller.id).pack()
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💳 Tarif berish", callback_data=SellerCB(action="grant", seller_id=seller.id).pack()
                )
            ]
        )

    if seller.status == SellerStatus.BLOCKED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Blokdan chiqarish",
                    callback_data=SellerCB(action="unblock", seller_id=seller.id).pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚫 Bloklash", callback_data=SellerCB(action="block", seller_id=seller.id).pack()
                ),
                InlineKeyboardButton(
                    text="💳 Tarif berish", callback_data=SellerCB(action="grant", seller_id=seller.id).pack()
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlangan" if seller.is_verified else "☑️ Tasdiqlash",
                callback_data=SellerCB(action="verify", seller_id=seller.id).pack(),
            ),
            InlineKeyboardButton(
                text="📝 Profil", callback_data=SellerCB(action="profile", seller_id=seller.id).pack()
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🕘 Obunalar tarixi", callback_data=SellerCB(action="subs", seller_id=seller.id).pack()
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 O'chirish", callback_data=SellerCB(action="delete", seller_id=seller.id).pack()
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data=back),
            InlineKeyboardButton(
                text="🔄", callback_data=SellerCB(action="card", seller_id=seller.id).pack()
            ),
        ]
    )
    rows.append([MENU_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def grant_tariffs_kb(tariffs: list, seller_id: int) -> InlineKeyboardMarkup:
    """«Tarif berish» — faol tariflar ro'yxati."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{tariff.name} — {tariff.duration_days} kun",
                callback_data=SellerCB(action="grant_tariff", seller_id=seller_id, value=str(tariff.id)).pack(),
            )
        ]
        for tariff in tariffs
    ]

    if not tariffs:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Tarif yaratish",
                    callback_data=TariffCB(action="create").pack(),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Orqaga", callback_data=SellerCB(action="card", seller_id=seller_id).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def block_reasons_kb(seller_id: int) -> InlineKeyboardMarkup:
    """Tez-tez uchraydigan bloklash sabablari."""
    reasons = (
        ("Qoidabuzarlik (firibgarlik)", "fraud"),
        ("To'lov qilmadi", "no_pay"),
        ("Shikoyatlar ko'p", "complaints"),
        ("Boshqa", "other"),
    )
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=SellerCB(action="block_confirm", seller_id=seller_id, value=key).pack(),
            )
        ]
        for label, key in reasons
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Orqaga", callback_data=SellerCB(action="card", seller_id=seller_id).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(action: str, seller_id: int, *, yes: str = "✅ Ha, o'chirish") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            confirm_row(
                SellerCB(action=f"{action}_confirm", seller_id=seller_id).pack(),
                SellerCB(action="card", seller_id=seller_id).pack(),
                confirm_text=yes,
            )
        ]
    )


def cancel_kb(seller_id: int = 0) -> InlineKeyboardMarkup:
    """FSM qadamini bekor qilish."""
    back = (
        SellerCB(action="card", seller_id=seller_id).pack()
        if seller_id
        else SellerCB(action="list", value="0|all").pack()
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data=back)]]
    )


def profile_kb(seller: Seller) -> InlineKeyboardMarkup:
    """Profilni tahrirlash maydonlari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Ism", callback_data=SellerCB(action="edit_name", seller_id=seller.id).pack()
                ),
                InlineKeyboardButton(
                    text="📞 Telefon", callback_data=SellerCB(action="edit_phone", seller_id=seller.id).pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Kontakt", callback_data=SellerCB(action="edit_contact", seller_id=seller.id).pack()
                ),
                InlineKeyboardButton(
                    text="🗒 Izoh", callback_data=SellerCB(action="note", seller_id=seller.id).pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Orqaga", callback_data=SellerCB(action="card", seller_id=seller.id).pack()
                )
            ],
        ]
    )


__all__ = [
    "FILTERS",
    "MENU_BUTTON",
    "block_reasons_kb",
    "cancel_kb",
    "confirm_kb",
    "grant_tariffs_kb",
    "profile_kb",
    "seller_card_kb",
    "seller_button",
    "sellers_list_kb",
]
