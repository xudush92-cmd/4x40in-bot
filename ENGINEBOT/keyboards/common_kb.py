"""
keyboards/common_kb.py — barcha panellar uchun umumiy tugmalar.

V1 yangilanish:
- Yangi rollar: I_AM_POSTER, I_AM_CUSTOMER (ROLA_TANLASH menyusida)
- Poster uchun: NEW_POST, MY_POSTS, INTERVAL, START_ROTATION, STOP_ROTATION
- Customer uchun: SEARCH, BROWSE_FEED, MY_BOOKMARKS

QOIDALAR:
─────────
- Hamma callback_data: "<scope>:<action>:<arg>" formatida
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

    # ─── Universal ───────────────────────────────────────────────────
    BACK = "⬅️ Orqaga"
    CANCEL = "❌ Bekor qilish"
    HELP = "ℹ️ Yordam"
    HOME = "🏠 Bosh menyu"

    # ─── Rol tanlash (/start menyusida) ──────────────────────────────
    I_AM_TENANT = "🏢 Men guruh adminiman"
    I_AM_POSTER = "📝 Men eʼlon beraman"
    I_AM_CUSTOMER = "🔍 Men mijozman"

    # ─── POSTER paneli ───────────────────────────────────────────────
    NEW_POST = "➕ Yangi eʼlon"
    MY_POSTS = "📋 Mening eʼlonlarim"
    POSTER_START = "▶️ Auto-post YOQISH"
    POSTER_STOP = "⛔ Auto-post TOʻXTATISH"
    POSTER_INTERVAL = "⏱ Interval"
    POSTER_STATS = "📊 Statistika"
    CHANGE_CATEGORY = "🔄 Soha oʻzgartirish"

    # ─── CUSTOMER paneli ─────────────────────────────────────────────
    SEARCH = "🔍 Qidirish"
    BROWSE_FEED = "📰 Yangi eʼlonlar"
    MY_BOOKMARKS = "⭐ Saqlanganlar"
    SEARCH_HISTORY = "📋 Qidiruv tarixi"

    # ─── User umumiy ─────────────────────────────────────────────────
    MY_PROFILE = "👤 Profilim"
    EDIT_PROFILE = "✏️ Profilni tahrirlash"
    LOGOUT = "🚪 Chiqish"

    # ─── TENANT paneli ───────────────────────────────────────────────
    MY_CHANNELS = "📺 Kanallarim"
    ADD_CHANNEL = "➕ Kanal ulash"
    MANAGE_USERS = "👥 Foydalanuvchilar"
    MANAGE_POSTS = "📋 Eʼlonlar"
    BOT_SETTINGS = "⚙️ Sozlamalar"
    STATS = "📊 Statistika"
    AUDIT_LOG = "📜 Tarix (log)"
    MODERATORS = "👮 Moderatorlar"
    DEEP_LINK = "🔗 Havola"
    CATEGORY_RESTRICTION = "🚫 Kategoriyalar"

    # ─── SUPER ADMIN paneli ──────────────────────────────────────────
    ALL_TENANTS = "👥 Tenantlar"
    GLOBAL_STATS = "📊 Global statistika"
    GLOBAL_AUDIT = "📜 Global log"
    BROADCAST = "📨 Broadcast"
    SYSTEM = "🛠 Tizim"
    PAYMENTS = "📜 Muddat tarixi"


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
        return {
            "keyboard": [[{"text": t} for t in row] for row in rows],
            "resize_keyboard": resize,
        }
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
# ON/OFF toggle (sozlamalar uchun)
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
            "keyboard": [
                [{"text": text, "request_contact": True}],
                [{"text": Btn.CANCEL}],
            ],
            "resize_keyboard": True,
        }
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=text, request_contact=True))
    kb.row(KeyboardButton(text=Btn.CANCEL))
    return kb.as_markup(resize_keyboard=True)
