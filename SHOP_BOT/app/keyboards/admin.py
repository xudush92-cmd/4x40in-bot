"""Boshqaruv paneli klaviaturalari (REJA.md 6-bo'lim).

Har bo'lim uchun tugma bor; qaysi Phase'da tayyor bo'lishi `ADMIN_SECTIONS`
jadvalida ko'rsatilgan — tugma bosilganda shu ma'lumot chiqadi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import AdminRole
from app.keyboards.callbacks import AdminCB

# (kalit, tugma matni, tayyor bo'ladigan bosqich)
ADMIN_SECTIONS: list[tuple[str, str, int]] = [
    ("stats", "📊 Statistika", 0),
    ("groups", "👥 Guruhlar", 1),
    ("categories", "🗂 Toifalar", 1),
    ("sellers", "🛒 Sotuvchilar", 2),
    ("tariffs", "💳 Tariflar", 2),
    ("ads", "📢 E'lonlar", 3),
    ("moderation", "✅ Moderatsiya", 3),
    ("payments", "💰 To'lovlar", 5),
    ("guard", "🛡 Posbon", 6),
    ("cleaner", "🧹 Tozalovchi", 6),
    ("permissions", "🔑 Ruxsatlar", 6),
    ("users", "👤 Foydalanuvchilar", 6),
    ("counter", "🧮 Sanoqchi", 7),
    ("referral", "🤝 Referal", 8),
    ("texts", "✍️ Bot matnlari", 8),
    ("errors", "⚠️ Xatolar jurnali", 8),
    ("admins", "🛠 Adminlar", 8),
    ("broadcast", "📣 Broadcast", 8),
    ("settings", "⚙️ Sozlamalar", 0),
]

SECTION_TITLES: dict[str, str] = {key: label for key, label, _ in ADMIN_SECTIONS}
SECTION_PHASES: dict[str, int] = {key: phase for key, _, phase in ADMIN_SECTIONS}

READY_SECTIONS = {"stats", "settings", "groups", "categories", "sellers", "tariffs"}


# Qaysi bo'limlarga raqamli hisoblagich qo'shiladi
COUNTABLE_SECTIONS = {
    "groups",
    "categories",
    "sellers",
    "ads",
    "moderation",
    "payments",
    "users",
    "errors",
}


def admin_main_kb(
    role: str | None = None, counts: dict[str, int] | None = None
) -> InlineKeyboardMarkup:
    """Asosiy panel: 2 tugma bir qatorda (+ hisoblagichlar).

    `counts` — `stats_service.get_menu_counts()` natijasi.
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for key, label, _phase in ADMIN_SECTIONS:
        # Adminlarni boshqarish — faqat super admin uchun
        if key == "admins" and role != AdminRole.SUPER:
            continue

        text = label
        if counts and key in COUNTABLE_SECTIONS:
            value = counts.get(key)
            if value is not None and value > 0:
                text = f"{label} · {value}"

        button = InlineKeyboardButton(
            text=text,
            callback_data=AdminCB(action="section", value=key).pack(),
        )
        row.append(button)
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Yangilash", callback_data=AdminCB(action="menu").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(target: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action=target).pack())]
        ]
    )


def settings_kb(values: dict[str, object]) -> InlineKeyboardMarkup:
    """Sozlamalar ekrani uchun tumblerlar."""

    def toggle(key: str, label: str) -> InlineKeyboardButton:
        on = bool(values.get(key))
        return InlineKeyboardButton(
            text=f"{'🟢' if on else '🔴'} {label}",
            callback_data=AdminCB(action="toggle", value=key).pack(),
        )

    rows = [
        [toggle("kill_switch", "🛑 HAMMASINI TO'XTATISH")],
        [toggle("maintenance_mode", "🔧 Texnik rejim (faqat adminlar)")],
        [toggle("referral_enabled", "🤝 Referal tizimi")],
        [toggle("receipt_required", "🧾 Chek rasmi majburiy")],
        [
            InlineKeyboardButton(
                text="⏱ Joylash intervali (default)",
                callback_data=AdminCB(action="edit", value="default_interval_sec").pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="☎️ Yordam kontakti",
                callback_data=AdminCB(action="edit", value="support_contact").pack(),
            )
        ],
        [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
