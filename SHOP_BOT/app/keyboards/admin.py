"""Boshqaruv paneli klaviaturalari (REJA.md 6-bo'lim).

Har bo'lim uchun tugma bor; qaysi Phase'da tayyor bo'lishi `ADMIN_SECTIONS`
jadvalida ko'rsatilgan — tugma bosilganda shu ma'lumot chiqadi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import AdminRole
from app.keyboards.callbacks import AdminCB, CounterAdminCB, GuideCB

# (kalit, tugma matni, tayyor bo'ladigan bosqich)
ADMIN_SECTIONS: list[tuple[str, str, int]] = [
    ("stats", "📊 Statistika", 0),
    ("groups", "👥 Guruhlar", 1),
    ("categories", "🗂 Toifalar", 1),
    ("applications", "📥 Arizalar", 2),
    ("sellers", "🛒 Sotuvchilar", 2),
    ("tariffs", "💳 Tariflar", 2),
    ("ads", "📢 E'lonlar", 3),
    ("moderation", "✅ Moderatsiya", 3),
    ("free_moderation", "🎁 Bepul e'lonlar", 3),
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

READY_SECTIONS = {
    "stats",
    "settings",
    "groups",
    "categories",
    "sellers",
    "applications",
    "tariffs",
    "ads",
    "moderation",
    "free_moderation",
    "payments",
    "guard",
    "cleaner",
    "counter",
    "referral",
    "texts",
    "errors",
    "broadcast",
    "admins",
    "permissions",
    "users",
}


# Yangi menyu eski `adm:section` callback'larini o'chirmaydi: barcha tayyor
# bo'limlar faqat bitta qo'shimcha bosqich orqali ochiladi.
HUB_SECTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "sales": ("🛒 Savdo", ("applications", "sellers", "tariffs", "payments", "referral")),
    "content": ("📢 Kontent", ("ads", "moderation", "free_moderation", "categories", "broadcast")),
    "control": ("📊 Nazorat", ("stats", "users", "errors")),
    "system": ("⚙️ Tizim", ("settings", "texts", "admins")),
}


# Qaysi bo'limlarga raqamli hisoblagich qo'shiladi
COUNTABLE_SECTIONS = {
    "applications",
    "groups",
    "categories",
    "sellers",
    "ads",
    "moderation",
    "free_moderation",
    "payments",
    "users",
    "errors",
}


def _section_button(key: str, counts: dict[str, int] | None = None) -> InlineKeyboardButton:
    label = SECTION_TITLES[key]
    count = (counts or {}).get(key)
    if key in COUNTABLE_SECTIONS and count is not None and count > 0:
        label += f" · {count}"
    return InlineKeyboardButton(text=label, callback_data=AdminCB(action="section", value=key).pack())


def _visible(key: str, role: str | None) -> bool:
    if key == "admins":
        return role == AdminRole.SUPER
    if role == AdminRole.MODERATOR and key in {"applications", "payments", "broadcast", "sellers", "tariffs", "referral", "errors"}:
        return False
    return True


def admin_main_kb(
    role: str | None = None, counts: dict[str, int] | None = None
) -> InlineKeyboardMarkup:
    """Navbatlar avval; beshta asosiy yo'nalish, eski callback'lar saqlanadi."""
    counts = counts or {}
    queues = []
    if _visible("applications", role):
        queues.append(_section_button("applications", counts))
    queues.append(_section_button("moderation", counts))
    if _visible("payments", role):
        queues.append(_section_button("payments", counts))
    rows: list[list[InlineKeyboardButton]] = [queues]
    rows.append([_section_button("free_moderation", counts)])
    rows.append([_section_button("groups", counts)])
    rows.append([
        InlineKeyboardButton(text=HUB_SECTIONS[key][0], callback_data=AdminCB(action="hub", value=key).pack())
        for key in ("sales", "content") if key != "sales" or role != AdminRole.MODERATOR
    ])
    rows.append([
        InlineKeyboardButton(text=HUB_SECTIONS[key][0], callback_data=AdminCB(action="hub", value=key).pack())
        for key in ("control", "system")
    ])
    rows.append([InlineKeyboardButton(text="📖 Foydalanish yo'riqnomasi", callback_data=GuideCB().pack())])
    rows.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data=AdminCB(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_hub_kb(hub: str, role: str | None = None,
                 counts: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    """Mavjud bo'limlarga qayta yozmasdan kirish; `hub` faqat whitelistdan."""
    if hub not in HUB_SECTIONS:
        raise ValueError("Noma'lum boshqaruv yo'nalishi")
    keys = [key for key in HUB_SECTIONS[hub][1] if _visible(key, role)]
    rows = [[_section_button(key, counts)] for key in keys]
    if hub == "control" and role in {AdminRole.ADMIN, AdminRole.SUPER}:
        rows.append([InlineKeyboardButton(
            text="📋 Harakatlar tarixi", callback_data=AdminCB(action="audit").pack()
        )])
    if hub == "system":
        rows.append([InlineKeyboardButton(
            text="📣 Umumiy kanallar", callback_data=CounterAdminCB(action="channels").pack()
        )])
        rows.append([InlineKeyboardButton(
            text="📚 Barcha bo'limlar", callback_data=AdminCB(action="all").pack()
        )])
    rows += [
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data=AdminCB(action="hub", value=hub).pack())],
        [InlineKeyboardButton(text="◀️ Boshqaruv", callback_data=AdminCB(action="menu").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_all_sections_kb(role: str | None = None) -> InlineKeyboardMarkup:
    """Eski 19 bo'limning xavfsiz, ixtiyoriy yo'li (eski callbacklar ishlaydi)."""
    buttons = [_section_button(key) for key, _, _ in ADMIN_SECTIONS if _visible(key, role)]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="◀️ Tizim", callback_data=AdminCB(action="hub", value="system").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(target: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action=target).pack())]
        ]
    )


def settings_kb(values: dict[str, object], role: str | None = None) -> InlineKeyboardMarkup:
    """Sozlamalar ekrani; moderator faqat ko'radi, yozish serverda ham yopiq."""
    if role == AdminRole.MODERATOR:
        return back_kb()

    def toggle(key: str, label: str) -> InlineKeyboardButton:
        on = bool(values.get(key))
        return InlineKeyboardButton(
            text=f"{'🟢' if on else '🔴'} {label}",
            callback_data=AdminCB(action="toggle", value=key).pack(),
        )

    rows = [
        [toggle("kill_switch", "🛑 HAMMASINI TO'XTATISH")],
        [toggle("maintenance_mode", "🔧 Texnik rejim (faqat adminlar)")],
    ]
    if role != AdminRole.MODERATOR:
        rows.extend([
            [toggle("counter_enabled_global", "🧮 Sanoqchi global")],
            [toggle("guard_enabled_global", "🛡 Posbon global")],
            [toggle("cleaner_enabled_global", "🧹 Tozalovchi global")],
            [toggle("broadcast_enabled_global", "📣 Broadcast global pauza")],
            [toggle("receipt_required", "🧾 Chek rasmi majburiy")],
            [toggle("receipt_duplicate_check", "🔍 Takroriy chekni ushlash")],
        ])
    rows += [
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
