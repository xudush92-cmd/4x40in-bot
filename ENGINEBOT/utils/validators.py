"""
utils/validators.py — input validatsiyasi.

MAQSAD:
───────
Foydalanuvchidan kelgan har qanday matnni TEKSHIRISH va NORMALIZATSIYA
qilish. SQL injection va format xatolaridan himoya.

USAGE:
──────
    ok, normalized, error = validate_phone("+998 90 123 45 67")
    if not ok:
        await msg.answer(error)
        return

PRINSIPLAR:
───────────
1. Har validator (ok, normalized, error) tuple qaytaradi.
2. ok=True boʻlsa — normalized qiymat tozalangan va ishlatishga tayyor.
3. ok=False boʻlsa — error foydalanuvchiga koʻrsatish uchun matn.
4. Hech qachon raise qilmaydi (defensive).
"""

from __future__ import annotations

import re
from typing import Tuple

from config import Limits


# Tip alias — qaytariladigan tuple
ValidationResult = Tuple[bool, str, str]
# (ok, normalized_value, error_message_uz)


# ─────────────────────────────────────────────────────────────────────
# Telefon raqam (O'zbekiston)
# ─────────────────────────────────────────────────────────────────────
_PHONE_DIGITS_RE = re.compile(r"\D+")
_UZ_PHONE_RE = re.compile(r"^\+998\d{9}$")


def validate_phone(text: str) -> ValidationResult:
    """
    O'zbekiston telefon raqami: +998XXXXXXXXX

    Bo'sh joy, qavslar, defislar olib tashlanadi.
    Misollar:
        "+998 90 123 45 67"  → "+998901234567"
        "998901234567"       → "+998901234567"
        "(90) 123-45-67"     → ❌ (kod yoʻq)
    """
    if not text or not text.strip():
        return False, "", "📵 Telefon raqam boʻsh."

    raw = text.strip()
    if len(raw) > Limits.MAX_PHONE_LEN * 3:
        return False, "", "📵 Telefon raqami juda uzun."

    # Faqat raqamlar
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if not digits:
        return False, "", "📵 Telefon raqamida raqam yoʻq."

    # 998... bilan boshlansa +998 qoʻyish
    if digits.startswith("998") and len(digits) == 12:
        normalized = "+" + digits
    elif digits.startswith("8") and len(digits) == 10:
        # 8XXXXXXXXX → 998XXXXXXXXX (eski format)
        normalized = "+998" + digits[1:]
    elif len(digits) == 9:
        # XXXXXXXXX → 998XXXXXXXXX
        normalized = "+998" + digits
    elif len(digits) == 12:
        normalized = "+" + digits
    else:
        return False, "", (
            "📵 Telefon raqami notoʻgʻri. Toʻgʻri format: +998XXXXXXXXX"
        )

    if not _UZ_PHONE_RE.match(normalized):
        return False, "", (
            "📵 Faqat Oʻzbekiston raqamlari qabul qilinadi (+998...)."
        )

    return True, normalized, ""


# ─────────────────────────────────────────────────────────────────────
# Ism va familiya
# ─────────────────────────────────────────────────────────────────────
_NAME_INVALID_RE = re.compile(r"[<>{}\[\]\\^|`]")
_NAME_VALID_RE = re.compile(r"^[a-zA-Z'\u00C0-\u024F\u0400-\u04FF\s\.\-]+$")


def validate_name(text: str) -> ValidationResult:
    """
    Ism familiya. Faqat harflar, bo'shliq, tire, apostrof.

    Min 2 belgi, max Limits.MAX_NAME_LEN.
    """
    if not text:
        return False, "", "👤 Ism boʻsh."

    cleaned = re.sub(r"\s+", " ", text.strip())

    if len(cleaned) < 2:
        return False, "", "👤 Ism juda qisqa (min 2 ta belgi)."

    if len(cleaned) > Limits.MAX_NAME_LEN:
        return False, "", f"👤 Ism juda uzun (max {Limits.MAX_NAME_LEN} ta belgi)."

    if _NAME_INVALID_RE.search(cleaned):
        return False, "", "👤 Ismda noruxsat belgilar bor."

    # Raqam yoʻq
    if any(ch.isdigit() for ch in cleaned):
        return False, "", "👤 Ismda raqam boʻlmasligi kerak."

    # Faqat harflar va ruxsat etilgan belgilar
    if not _NAME_VALID_RE.match(cleaned):
        return False, "", "👤 Ismda faqat harflar boʻlishi mumkin."

    return True, cleaned, ""


# ─────────────────────────────────────────────────────────────────────
# Telegram username
# ─────────────────────────────────────────────────────────────────────
_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")


def validate_username(text: str) -> ValidationResult:
    """
    Telegram username: 5-32 belgi, harfdan boshlanadi, _ ruxsat.
    @ boshida boʻlsa olib tashlanadi. Boʻsh boʻlsa OK (ixtiyoriy field).
    """
    if not text or not text.strip():
        return True, "", ""  # ixtiyoriy

    cleaned = text.strip().lstrip("@")
    if not _USERNAME_RE.match(cleaned):
        return False, "", (
            "📎 Username notoʻgʻri.\n"
            "5-32 belgi, harfdan boshlanadi, faqat harf/raqam/_ ruxsat."
        )
    return True, cleaned, ""


# ─────────────────────────────────────────────────────────────────────
# Kanal ID yoki @username
# ─────────────────────────────────────────────────────────────────────
_CHANNEL_USERNAME_RE = re.compile(r"^@?[a-zA-Z][a-zA-Z0-9_]{4,31}$")
_CHANNEL_INT_RE = re.compile(r"^-100\d{6,15}$")
_TME_RE = re.compile(r"^https?://(?:t|telegram)\.me/([a-zA-Z][a-zA-Z0-9_]{4,31})$")


def validate_channel(text: str) -> ValidationResult:
    """
    Kanal kiritish: @username yoki -1001234567 yoki t.me link.

    Returns: (ok, normalized, error)
    normalized — yo @username yo "-1001234567" string.
    """
    if not text or not text.strip():
        return False, "", "📺 Kanal kiritilmagan."

    raw = text.strip()

    # t.me link?
    m = _TME_RE.match(raw)
    if m:
        return True, "@" + m.group(1), ""

    # @username yoki username?
    if _CHANNEL_USERNAME_RE.match(raw):
        return True, raw if raw.startswith("@") else f"@{raw}", ""

    # Numeric -100...?
    if _CHANNEL_INT_RE.match(raw):
        return True, raw, ""

    return False, "", (
        "📺 Kanal notoʻgʻri.\n"
        "Toʻgʻri format: @kanal_nomi yoki -1001234567"
    )


# ─────────────────────────────────────────────────────────────────────
# E'lon matni
# ─────────────────────────────────────────────────────────────────────
def validate_post_text(text: str) -> ValidationResult:
    """E'lon matni: bo'sh emas, max uzunlikda."""
    if not text or not text.strip():
        return False, "", "📝 Eʼlon matni boʻsh."

    cleaned = text.strip()
    if len(cleaned) > Limits.MAX_POST_TEXT_LEN:
        return False, "", (
            f"📝 Eʼlon juda uzun (max {Limits.MAX_POST_TEXT_LEN} belgi). "
            f"Hozir: {len(cleaned)} belgi."
        )
    return True, cleaned, ""


# ─────────────────────────────────────────────────────────────────────
# Vaqt (HH:MM)
# ─────────────────────────────────────────────────────────────────────
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def validate_time(text: str) -> ValidationResult:
    """HH:MM format. 14:30, 09:00 va h.k."""
    if not text:
        return False, "", "⏰ Vaqt kiritilmagan."

    cleaned = text.strip()
    m = _TIME_RE.match(cleaned)
    if not m:
        return False, "", "⏰ Vaqt notoʻgʻri. Format: HH:MM (masalan 14:30)"

    hh, mm = m.groups()
    return True, f"{int(hh):02d}:{mm}", ""


# ─────────────────────────────────────────────────────────────────────
# Interval (daqiqa)
# ─────────────────────────────────────────────────────────────────────
def validate_interval(
    text: str, *, min_min: int = 10, max_min: int = 24 * 60
) -> ValidationResult:
    """
    Aylanish intervali (daqiqa). Min 10 daq (foydalanuvchi qatʼiy talab qildi).
    """
    if not text:
        return False, "", "⏱ Interval kiritilmagan."

    cleaned = text.strip()
    try:
        n = int(cleaned)
    except ValueError:
        return False, "", "⏱ Interval butun son boʻlishi kerak (daqiqa)."

    if n < min_min:
        return False, str(min_min), (
            f"⏱ Interval juda kichik. Minimum: {min_min} daqiqa."
        )
    if n > max_min:
        return False, str(max_min), (
            f"⏱ Interval juda katta. Maksimum: {max_min} daqiqa ({max_min // 60} soat)."
        )
    return True, str(n), ""


# ─────────────────────────────────────────────────────────────────────
# Mashina raqami (O'zbekiston)
# ─────────────────────────────────────────────────────────────────────
_CAR_PLATE_RE = re.compile(r"^\d{2}[A-Z]\d{3}[A-Z]{2}$")


def validate_car_plate(text: str) -> ValidationResult:
    """
    O'zbekiston mashina raqami: 01A123BC formati.
    Boʻsh joylar va kichik harflar tushuriladi.
    """
    if not text:
        return False, "", "🚗 Mashina raqami kiritilmagan."

    cleaned = re.sub(r"\s+", "", text.strip().upper())
    if not _CAR_PLATE_RE.match(cleaned):
        return False, "", (
            "🚗 Raqam notoʻgʻri.\n"
            "Toʻgʻri format: 01A123BC"
        )
    return True, cleaned, ""


# ─────────────────────────────────────────────────────────────────────
# Sabab matni (warning, block uchun)
# ─────────────────────────────────────────────────────────────────────
def validate_reason(text: str, min_len: int = 3, max_len: int = 500) -> ValidationResult:
    """Block/warning sababi."""
    if not text or not text.strip():
        return False, "", "📝 Sabab kiritilmagan."

    cleaned = text.strip()
    if len(cleaned) < min_len:
        return False, "", f"📝 Sabab juda qisqa (min {min_len} belgi)."
    if len(cleaned) > max_len:
        return False, "", f"📝 Sabab juda uzun (max {max_len} belgi)."

    return True, cleaned, ""
