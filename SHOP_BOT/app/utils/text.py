"""Matn bilan ishlash yordamchilari: emoji ajratish, qisqartirish, formatlash."""

from __future__ import annotations

import re
import unicodedata

# Telegram HTML uchun xavfli belgilar
_HTML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
_HTML_RE = re.compile("|".join(map(re.escape, _HTML_ESCAPE)))

_WS_RE = re.compile(r"\s+")


def escape_html(text: str | None) -> str:
    """Foydalanuvchi kiritgan matnni Telegram HTML uchun xavfsiz qilish.

    Muhim: foydalanuvchi matnini hech qachon to'g'ridan-to'g'ri HTML xabarga
    qo'shmaymiz (aks holda "<b>" kabi belgilar xabarni buzadi).
    """
    if not text:
        return ""
    return _HTML_RE.sub(lambda m: _HTML_ESCAPE[m.group(0)], str(text))


def clean_text(text: str | None, *, limit: int | None = None) -> str | None:
    """Ortiqcha bo'shliqlarni tozalash va uzunlikni cheklash."""
    if text is None:
        return None
    value = _WS_RE.sub(" ", str(text)).strip()
    if not value:
        return None
    if limit and len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def truncate(text: str | None, limit: int = 40, suffix: str = "…") -> str:
    """Uzun matnni qisqartirish (tugma matnlari uchun)."""
    if not text:
        return "—"
    text = str(text).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - len(suffix))].rstrip() + suffix


def _is_emoji(ch: str) -> bool:
    """Belgi emoji (yoki ramz) ekanini aniqlash."""
    code = ord(ch)
    if code >= 0x1F000:  # asosiy emoji diapazonlari
        return True
    if 0x2600 <= code <= 0x27BF:  # turli ramzlar
        return True
    return unicodedata.category(ch) in ("So", "Sk")


def split_name_emoji(text: str | None) -> tuple[str | None, str]:
    """'📱 Telefonlar' → ('📱', 'Telefonlar').

    Emoji bo'lmasa: (None, 'Telefonlar').
    """
    value = (text or "").strip()
    if not value:
        return None, ""

    emoji_chars: list[str] = []
    rest = value
    while rest and _is_emoji(rest[0]):
        emoji_chars.append(rest[0])
        rest = rest[1:].lstrip()
        if len(emoji_chars) >= 4:  # cheklov (masalan bayroq + teri rangi)
            break

    emoji = "".join(emoji_chars) or None
    return emoji, rest.strip() or value.strip()


def human_int(value: int | float | None) -> str:
    """1234567 → '1 234 567' (o'qishga qulay)."""
    if value is None:
        return "0"
    return f"{int(value):,}".replace(",", " ")


def fmt_amount(value: object, currency: str = "UZS") -> str:
    """Pul summasi: '1 500 000 so'm'."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        pretty = human_int(int(number))
    else:
        pretty = f"{number:,.2f}".replace(",", " ")
    return f"{pretty} {currency}".strip()


def fmt_interval(seconds: int | None) -> str:
    """Intervalni o'qishga qulay ko'rinishda: '30 daqiqa', '2 soat', '1 kun 2 soat'."""
    if not seconds or seconds <= 0:
        return "—"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} daqiqa"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} soat" + (f" {mins} daqiqa" if mins else "")
    days, hrs = divmod(hours, 24)
    return f"{days} kun" + (f" {hrs} soat" if hrs else "")


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_QUIET_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)\s*[-–—]\s*([01]?\d|2[0-3]):([0-5]\d)$")


def parse_time(value: str) -> str | None:
    """'9:30' → '09:30' (noto'g'ri bo'lsa None)."""
    match = _TIME_RE.match((value or "").strip())
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_quiet_hours(value: str) -> tuple[str, str] | None:
    """'23:00-08:00' → ('23:00', '08:00'); 'off' → None (o'chirilgan).

    Noto'g'ri format uchun ValueError ko'tariladi (handler xato xabarini ko'rsatadi).
    """
    text = (value or "").strip().lower()
    if text in ("off", "yoq", "o'chir", "ochir", "-"):
        return None
    match = _QUIET_RE.match(text)
    if not match:
        raise ValueError("format")
    return f"{int(match.group(1)):02d}:{match.group(2)}", f"{int(match.group(3)):02d}:{match.group(4)}"


def fmt_quiet_hours(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "o'chirilgan"
    return f"{start} – {end}"


def percent_badge(value: bool, on: str = "🟢", off: str = "🔴") -> str:
    return on if value else off
