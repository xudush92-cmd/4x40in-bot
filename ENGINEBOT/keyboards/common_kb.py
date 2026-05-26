"""
keyboards/common_kb.py — barcha panellar uchun umumiy tugmalar.

QOIDALAR:
─────────
- Hamma callback_data: "cmd:<role>:<action>:<arg>" formatida
- "Bekor qilish" har joyda — qaytib ketish
- Reply keyboard: doimiy menyu (asosiy)
- Inline keyboard: kontekstga bogʻliq amallar
"""

from __future__ import annotations

from typing import Iterable

try:
    from aiogram.types import (
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        KeyboardButton,
        ReplyKeyboardMarkup,
        ReplyKeyboardRemove,
    )
    from aiogram.utils.keyboard import (
        InlineKeyboardBuilder,
        ReplyKeyboardBuilder,
    )
    _AIOGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AIOGRAM_AVAILABLE = False
    InlineKeyboardBuilder = None  # type: ignore
    ReplyKeyboardBuilder = None  # type: ignore
    ReplyKeyboardRemove = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────
# Tugma matnlari (matnga qarab handler ajratiladi)
# ─────────────────────────────────────────────────────────────────────
class Btn:
    """Reply keyboard tugma matnlari (asosiy menyular uchun)."""

    # Universal
    BACK = "⬅️ Orqaga"
    CANCEL = "❌ Bekor qilish"
    HELP = "ℹ️ Yordam"
    HOME = "🏠 Bosh menyu"

    # Foydalanuvchi rolini tanlash
    I_AM_TENANT = "🏢 Men guruh adminiman"
    I_AM_USER = "📝 Men eʼlon beraman"
    I_AM_SEARCHER = "🔍 Men eʼlon izlayman"

    # User panel
    NEW_POST = "📝 Yangi eʼlon"
    MY_POSTS = "📋 Mening eʼlonlarim"
    MY_PROFILE = "👤 Mening profilim"
    EDIT_PROFILE = "✏️ Profilni tahrirlash"
    LOGOUT = "🚪 Chiqish"

    # Tenant panel
    MY_CHANNELS = "📺 Kanallarim"
    ADD_CHANNEL = "➕ Kanal ulash"
    MANAGE_USERS = "👥 Foydalanuvchilar"
    MANAGE_POSTS = "📋 Eʼlonlar"
    ROTATION_SETTINGS = "🔄 Aylanish"
    BOT_SETTINGS = "⚙️ Sozlamalar"
    STATS = "📊 Statistika"
    AUDIT_LOG = "📜 Tarix (log)"
    MODERATORS = "👮 Moderatorlar"
    BILLING = "💰 Toʻlov"

    # Super admin panel
    ALL_TENANTS = "👥 Tenantlar"
    GLOBAL_STATS = "📊 Global statistika"
    GLOBAL_AUDIT = "📜 Global log"
    BROADCAST = "📨 Broadcast"
    SYSTEM = "🛠 Tizim"
    PAYMENTS = "💰 Toʻlovlar"


# ─────────────────────────────────────────────────────────────────────
# Reply keyboard (asosiy menyular)
# ─────────────────────────────────────────────────────────────────────
def make_reply(rows: list[list[str]], *, resize: bool = True):
    """
    Reply keyboard builder. Har row matn roʻyxati.

    Misol:
        make_reply([
            ["A", "B"],
            ["C"],
            [Btn.BACK],
        ])
    """
    if not _AIOGRAM_AVAILABLE:
        return {"keyboard": [[{"text": t} for t in row] for row in rows], "resize_keyboard": resize}
    builder = ReplyKeyboardBuilder()
    for row in rows:
        for t in row:
            builder.button(text=t)
        builder.adjust(*[len(r) for r in rows], repeat=False)
    # Yana sodda yondashuv:
    kb = ReplyKeyboardBuilder()
    for row in rows:
        kb.row(*[KeyboardButton(text=t) for t in row])
    return kb.as_markup(resize_keyboard=resize)


def remove_reply():
    """Reply keyboard'ni olib tashlash."""
    if not _AIOGRAM_AVAILABLE:
        return {"remove_keyboard": True}
    return ReplyKeyboardRemove()


# ─────────────────────────────────────────────────────────────────────
# Cancel/Back tugmalari (alohida row bilan)
# ─────────────────────────────────────────────────────────────────────
def cancel_button():
    """Reply keyboard: faqat 'Bekor qilish' tugmasi."""
    return make_reply([[Btn.CANCEL]])


def back_button():
    """Reply keyboard: faqat 'Orqaga' tugmasi."""
    return make_reply([[Btn.BACK]])


def back_cancel():
    """Reply keyboard: 'Orqaga' va 'Bekor qilish'."""
    return make_reply([[Btn.BACK, Btn.CANCEL]])


# ─────────────────────────────────────────────────────────────────────
# Inline keyboard yordamchilari
# ─────────────────────────────────────────────────────────────────────
def inline_grid(
    items: list[tuple[str, str]],
    *,
    columns: int = 2,
    extra_rows: list[list[tuple[str, str]]] | None = None,
):
    """
    Inline keyboard'ni grid shaklda yaratish.

    items   : (text, callback_data) tuple roʻyxati
    columns : qator boshiga necha tugma
    extra_rows : qoʻshimcha alohida qatorlar (masalan back/cancel)
    """
    if not _AIOGRAM_AVAILABLE:
        keyboard = []
        row: list[dict] = []
        for text, cb in items:
            row.append({"text": text, "callback_data": cb})
            if len(row) >= columns:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        for er in (extra_rows or []):
            keyboard.append([{"text": t, "callback_data": cb} for t, cb in er])
        return {"inline_keyboard": keyboard}

    builder = InlineKeyboardBuilder()
    for text, cb in items:
        builder.button(text=text, callback_data=cb)
    builder.adjust(columns)

    for extra in (extra_rows or []):
        row_btns = [InlineKeyboardButton(text=t, callback_data=cb) for t, cb in extra]
        builder.row(*row_btns)

    return builder.as_markup()


def inline_back(callback_data: str = "back"):
    """Faqat 'Orqaga' tugmasi (inline)."""
    return inline_grid([(Btn.BACK, callback_data)], columns=1)


def inline_cancel(callback_data: str = "cancel"):
    return inline_grid([(Btn.CANCEL, callback_data)], columns=1)


# ─────────────────────────────────────────────────────────────────────
# ON/OFF toggle (tenant sozlamalari uchun)
# ─────────────────────────────────────────────────────────────────────
def toggle_label(on: bool, label: str) -> str:
    """ON yoki OFF holatdagi label."""
    return f"{'🟢' if on else '🔴'} {label}: {'ON' if on else 'OFF'}"


# ─────────────────────────────────────────────────────────────────────
# Kontaktni soʻrash (telefon)
# ─────────────────────────────────────────────────────────────────────
def request_contact(text: str = "📱 Telefon raqamni yuborish"):
    """Telegram'ning 'request_contact' tugmasi (telefon avtomatik)."""
    if not _AIOGRAM_AVAILABLE:
        return {
            "keyboard": [[{"text": text, "request_contact": True}], [{"text": Btn.CANCEL}]],
            "resize_keyboard": True,
        }
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=text, request_contact=True))
    kb.row(KeyboardButton(text=Btn.CANCEL))
    return kb.as_markup(resize_keyboard=True)
