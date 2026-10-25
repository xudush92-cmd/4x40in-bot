"""👁 Kuzatuv rejimi — vaqtincha har bir skanerlangan xabarni ko'rsatadi.

Nega kerak: «nega bu xabar keldi / nega kelmadi» degan savolga log
o'qimasdan javob berish uchun. Admin ``/kuzat 15`` yozadi va 15 daqiqa
davomida **har bir** skanerlangan xabar kartasi unga shaxsiy chatga
keladi: matn, ball, ishlagan so'zlar, natija.

Maxfiylik (qat'iy):

* karta faqat **adminning o'ziga** boradi (``ADMIN_ID``);
* faqat **adminning o'z akkaunti** skanerlagan xabarlar ko'rsatiladi —
  boshqa foydalanuvchilarning guruhlari hech qachon ko'rinmaydi;
* vaqt tugagach rejim o'zi o'chadi.
"""
from __future__ import annotations

import html
import time

DEFAULT_MINUTES = 15
MAX_MINUTES = 120

# Kuzatuv tugash vaqti (0 — o'chirilgan).
_until: float = 0.0


def enable(minutes: int = DEFAULT_MINUTES) -> int:
    """Kuzatuvni yoqadi va necha daqiqaga yoqilganini qaytaradi."""
    global _until
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    minutes = max(1, min(MAX_MINUTES, minutes))
    _until = time.time() + minutes * 60
    return minutes


def disable() -> None:
    global _until
    _until = 0.0


def is_active() -> bool:
    return _until > time.time()


def remaining() -> int:
    """Tugashiga necha daqiqa qoldi (0 — o'chiq)."""
    left = int(_until - time.time())
    if left <= 0:
        return 0
    return (left + 59) // 60


def _cut(text: str, limit: int = 400) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def card_text(text: str, verdict) -> str:
    """Bitta xabarning kuzatuv kartasi (HTML)."""
    score = float(getattr(verdict, "score", 0) or 0)
    threshold = float(getattr(verdict, "threshold", 0) or 0)
    ok = bool(getattr(verdict, "ok", False))
    stage = getattr(verdict, "stage", "") or ""
    positives = dict(getattr(verdict, "positives", {}) or {})
    negatives = dict(getattr(verdict, "negatives", {}) or {})
    plus = ", ".join(f"+{w:g} {n}" for n, w in positives.items()) or "—"
    minus = ", ".join(f"{w:g} {n}" for n, w in negatives.items()) or "—"
    if ok:
        result = "✅ yuborildi"
    elif stage == "keywords" and 0 < score < threshold:
        result = "⚡ chegarada — o'tmadi"
    else:
        result = f"⛔ to'xtadi: {html.escape(stage or '—')}"
    return "\n".join([
        f"👁 <b>Kuzatuv</b> · <i>{remaining()} daq qoldi</i>",
        f"«{html.escape(_cut(text), quote=False)}»",
        f"⚖️ ball <b>{score:g}</b> / {threshold:g}",
        f"➕ {html.escape(plus, quote=False)}",
        f"➖ {html.escape(minus, quote=False)}",
        f"Natija: {result}",
    ])
