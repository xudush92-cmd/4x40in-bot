"""
utils/confirmation.py — universal tasdiqlash tizimi.

MAQSAD:
───────
Foydalanuvchi qatʼiy talab qildi: HAR BIR muhim amalda tasdiqlash
(tugma yoki matn). Tasodifiy bosishlar, xato amallar oldini olish.

USAGE (handler ichida):
───────────────────────
    # Tasdiqlash so'rash:
    text, kb = build_confirmation(
        action_id="delete_post:42",
        title="Eʼlonni oʻchirish",
        question="Bu eʼlongizni oʻchirasizmi?",
        details=["📋 Eʼlon ID: 42", "📺 Toshkent → Samarqand"],
        warning="❌ Oʻchirilgan eʼlonni qaytarib boʻlmaydi!",
    )
    await message.answer(text, reply_markup=kb)

    # Callback ichida tekshirish:
    if data.startswith("confirm:yes:delete_post:"):
        # Foydalanuvchi tasdiqladi, amalni bajaring
        ...
    elif data.startswith("confirm:no:"):
        # Bekor qilindi
        ...

CALLBACK FORMAT:
────────────────
    confirm:yes:<action_id>       — tasdiqlandi
    confirm:no:<action_id>        — bekor qilindi
    confirm:type:<action_id>      — matn yozish kerak (xavfli amal)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

# aiogram'dan import qilamiz — lekin import error fail-safe boʻlsin uchun
# defensive try/except ishlatamiz (test/preview muhitida aiogram boʻlmasligi mumkin)
try:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    _AIOGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AIOGRAM_AVAILABLE = False
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore
    InlineKeyboardBuilder = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────
# Asosiy tasdiqlash matni (oddiy amallar uchun)
# ─────────────────────────────────────────────────────────────────────
def build_confirmation_text(
    *,
    title: str,
    question: str,
    details: Optional[Iterable[str]] = None,
    warning: str = "",
    extra: str = "",
) -> str:
    """
    Tasdiqlash xabari matnini tayyorlash.

    Format:
        ⚠️ TASDIQLASH

        Sarlavha
        ━━━━━━━━━━━━━━━━━━

        Savol matni

        📌 Tafsilotlar:
           • A
           • B

        ⚠️ Diqqat: ...
    """
    lines = ["⚠️ <b>TASDIQLASH</b>", ""]
    if title:
        lines.append(f"<b>{title}</b>")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
    if question:
        lines.append(question)
        lines.append("")
    if details:
        details_list = list(details)
        if details_list:
            lines.append("📌 <b>Tafsilotlar:</b>")
            for d in details_list:
                lines.append(f"   • {d}")
            lines.append("")
    if warning:
        lines.append(warning)
        lines.append("")
    if extra:
        lines.append(extra)
    return "\n".join(lines).rstrip()


# ─────────────────────────────────────────────────────────────────────
# Inline keyboard (Ha / Yoʻq tugmalari)
# ─────────────────────────────────────────────────────────────────────
def build_confirmation_keyboard(
    action_id: str,
    yes_label: str = "✅ Ha, tasdiqlayman",
    no_label: str = "❌ Yoʻq, bekor qilish",
):
    """
    Standart Ha/Yoʻq tugmalari.

    Returns: InlineKeyboardMarkup (yoki dict aiogram boʻlmasa, debug uchun).
    """
    if not _AIOGRAM_AVAILABLE:
        # Preview/test rejimi — dict qaytaramiz
        return {
            "inline_keyboard": [
                [
                    {"text": yes_label, "callback_data": f"confirm:yes:{action_id}"},
                    {"text": no_label, "callback_data": f"confirm:no:{action_id}"},
                ]
            ]
        }
    builder = InlineKeyboardBuilder()
    builder.button(text=yes_label, callback_data=f"confirm:yes:{action_id}")
    builder.button(text=no_label, callback_data=f"confirm:no:{action_id}")
    builder.adjust(1)  # Har bittasi alohida qatorda — yanglish bosishni oldini olish
    return builder.as_markup()


def build_confirmation(
    *,
    action_id: str,
    title: str,
    question: str,
    details: Optional[Iterable[str]] = None,
    warning: str = "",
    yes_label: str = "✅ Ha, tasdiqlayman",
    no_label: str = "❌ Yoʻq, bekor qilish",
):
    """
    Bitta chaqiruvda tugallangan tasdiqlash (matn + keyboard).

    Returns: (text, keyboard) tuple
    """
    text = build_confirmation_text(
        title=title, question=question, details=details, warning=warning
    )
    kb = build_confirmation_keyboard(
        action_id=action_id, yes_label=yes_label, no_label=no_label
    )
    return text, kb


# ─────────────────────────────────────────────────────────────────────
# Xavfli amal — matn yozish talab qilinadigan tasdiqlash
# ─────────────────────────────────────────────────────────────────────
DANGER_KEYWORD = "TASDIQLAYMAN"


def build_danger_confirmation_text(
    *,
    title: str,
    question: str,
    details: Optional[Iterable[str]] = None,
    keyword: str = DANGER_KEYWORD,
) -> str:
    """
    Xavfli amal — foydalanuvchi maxsus soʻz yozishi kerak.

    Misol: tenantni butunlay oʻchirish, baza reset.
    """
    lines = [
        "⚠️⚠️ <b>DIQQAT — XAVFLI AMAL</b>",
        "",
        f"<b>{title}</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        question,
        "",
    ]
    if details:
        details_list = list(details)
        if details_list:
            lines.append("📌 <b>Natijasi:</b>")
            for d in details_list:
                lines.append(f"   • {d}")
            lines.append("")
    lines.append("❌ <b>Bu amalni QAYTARIB BOʻLMAYDI!</b>")
    lines.append("")
    lines.append(f"Davom etish uchun quyidagi soʻzni yozing:")
    lines.append(f"<code>{keyword}</code>")
    return "\n".join(lines)


def is_danger_confirmed(user_input: str, keyword: str = DANGER_KEYWORD) -> bool:
    """Foydalanuvchi danger keyword'ni toʻgʻri yozdi-mi?"""
    return user_input.strip().upper() == keyword.upper()


# ─────────────────────────────────────────────────────────────────────
# Callback parser (handler tomonida ishlatish uchun)
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ConfirmationCallback:
    """`confirm:yes:delete_post:42` formatdagi callback parsed."""
    decision: str   # "yes" | "no"
    action_id: str  # masalan "delete_post:42"


def parse_confirmation(callback_data: str) -> Optional[ConfirmationCallback]:
    """
    Callback data'dan tasdiqlash maʼlumotini ajratib olish.

    Format: confirm:<decision>:<action_id>
    Returns: None — agar format notoʻgʻri.
    """
    if not callback_data.startswith("confirm:"):
        return None
    parts = callback_data.split(":", 2)
    if len(parts) < 3:
        return None
    _, decision, action_id = parts
    if decision not in ("yes", "no"):
        return None
    return ConfirmationCallback(decision=decision, action_id=action_id)


# ─────────────────────────────────────────────────────────────────────
# Tipik tasdiqlash matnlari (eng ko'p ishlatiladigan)
# ─────────────────────────────────────────────────────────────────────
def confirm_delete_post(post_id: int, post_title: str = ""):
    """E'lonni oʻchirish tasdig'i."""
    return build_confirmation(
        action_id=f"delete_post:{post_id}",
        title="Eʼlonni oʻchirish",
        question="Bu eʼlongizni oʻchirasizmi?",
        details=[f"📋 ID: #{post_id}"] + ([f"📝 {post_title}"] if post_title else []),
        warning="❌ Oʻchirilgan eʼlonni qaytarib boʻlmaydi.",
    )


def confirm_logout(uid: int):
    """Logout tasdig'i."""
    return build_confirmation(
        action_id=f"logout:{uid}",
        title="Tizimdan chiqish",
        question="Botdan chiqib ketasizmi?",
        details=[
            "📌 Profilingiz saqlanadi",
            "📌 Aktiv eʼlonlaringiz oʻchadi",
            "📌 Qaytadan kirish: /start",
        ],
    )


def confirm_block_user(target_uid: int, name: str):
    return build_confirmation(
        action_id=f"block_user:{target_uid}",
        title="Foydalanuvchini bloklash",
        question=f"<b>{name}</b> (#{target_uid}) ni bloklaysizmi?",
        details=[
            "📌 U eʼlon yaza olmaydi",
            "📌 Aktiv eʼlonlari oʻchadi",
            "📌 Keyinchalik tiklash mumkin",
        ],
        warning="⚠️ Foydalanuvchiga sabab bilan xabar yuboriladi.",
    )


def confirm_rotation_toggle(enable: bool, interval_min: int):
    action = "yoqish" if enable else "oʻchirish"
    return build_confirmation(
        action_id=f"rotation_toggle:{1 if enable else 0}",
        title=f"Aylanishni {action}",
        question=f"Aylanish funksiyasini {action}ni xohlaysizmi?",
        details=(
            [f"⏱ Interval: {interval_min} daqiqa", "🔄 Eʼlonlar avtomatik yangilanadi"]
            if enable
            else ["📌 Mavjud eʼlonlar guruhda qoladi", "📌 Avtomatik yangilanish toʻxtaydi"]
        ),
    )
