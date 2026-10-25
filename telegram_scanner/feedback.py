"""Bildirishnoma ustidan fikr-mulohaza: «✅ Foydali / ❌ Keraksiz».

Nega kerak: kalit so'zlarning vazni qo'lda qo'yiladi, ya'ni ular
foydalanuvchining real oqimini bilmaydi. Foydalanuvchi har bir
bildirishnomada bitta tugma bosadi — o'sha xabarda qatnashgan
so'zlarning vazni asta-sekin to'g'rilanadi. Bu "o'z-o'zini sozlash"
uchun eng arzon yo'l: qo'shimcha so'rovnoma ham, qo'lda sozlash ham
kerak emas.

Mantiq (oddiy va bashorat qilinadigan):

* **✅ Foydali** — xabarda qatnashgan musbat so'zlar kuchayadi
  (+qadam), manfiy so'zlar zaiflashadi (0 tomon −qadam). Ya'ni
  «men buni mijoz deb oldim» degan signal.
* **❌ Keraksiz** — musbat so'zlar zaiflashadi (−qadam). Manfiy
  so'zlarga tegilmaydi: ular o'z vazifasini to'g'ri bajargan
  (xabar o'tkazib yuborilgan bo'lsa).

Qadam kichik (0.25) — bitta bosish butun tizimni buzdirmaydi,
lekin bir xil xato takrorlansa vazn tez sur'atda to'g'rilanadi.
"""
from __future__ import annotations

import logging

from database import (
    get_lead_review,
    get_phrase,
    set_lead_verdict,
    update_phrase,
    word_id_by_text,
)

logger = logging.getLogger(__name__)

# Bir bosishdagi o'zgarish
STEP = 0.25
# Vazn 0 ga juda yaqinlashsa — belgi saqlanib qoladi (0 emas!)
MIN_ABS = 0.25
MAX_ABS = 10.0

VERDICT_USEFUL = "useful"
VERDICT_USELESS = "useless"


def _shift(weight: float, delta: float) -> float:
    """Vaznni siljitadi, chegaralarni va nolni hurmat qilib.

    Nolga o'tish taqiqlanadi: so'z «hisobga olinmaydigan» bo'lib
    qolmasin — aks holda foydalanuvchi nega endi bu so'z ishlamayotganini
    tushunmaydi.
    """
    new = weight + delta
    if weight > 0 and new <= 0:
        new = -MIN_ABS
    elif weight < 0 and new >= 0:
        new = MIN_ABS
    if new == 0:
        new = MIN_ABS if weight >= 0 else -MIN_ABS
    return round(max(-MAX_ABS, min(MAX_ABS, new)), 2)


def compute_changes(words, useful: bool, step: float = STEP) -> list[tuple[int, str, float, float]]:
    """Qaysi so'z qanday o'zgarishini hisoblaydi (bazaga yozmaydi).

    Qaytaradi: ``[(phrase_id, so'z, eski vazn, yangi vazn), ...]``.
    """
    changes: list[tuple[int, str, float, float]] = []
    for word in words or []:
        pid = word_id_by_text(word)
        if pid is None:
            continue
        row = get_phrase(pid)
        if not row:
            continue
        old = row[2]
        if useful:
            # Ikkalasi ham +qadam: musbat kuchayadi (0 dan uzoqlashadi),
            # manfiy zaiflashadi (0 tomon) — bu bitta formulada.
            delta = step
        else:
            # Faqat musbat zaiflashadi; manfiy o'z ishini qildi.
            if old <= 0:
                continue
            delta = -step
        new = _shift(old, delta)
        if new != old:
            changes.append((pid, row[1], old, new))
    return changes


def apply_feedback(review_id: int, useful: bool, step: float = STEP):
    """Fikrni qabul qiladi va vaznlarni moslashtiradi.

    Qaytaradi: ``(holat, o'zgarishlar)``, bunda holat:

    * ``"ok"`` — qabul qilindi;
    * ``"missing"`` — bunday bildirishnoma yo'q;
    * ``"done"`` — allaqachon belgilangan (takror bosish).
    """
    review = get_lead_review(review_id)
    if not review:
        return "missing", []
    _id, _owner, words, verdict = review
    if verdict:
        return "done", []
    changes = compute_changes(words, useful, step)
    for pid, _word, _old, new in changes:
        update_phrase(pid, weight=new)
    if not set_lead_verdict(
        review_id, VERDICT_USEFUL if useful else VERDICT_USELESS
    ):
        return "done", []
    logger.info(
        "[FEEDBACK] review=%s useful=%s so'zlar=%s",
        review_id, useful, [(c[1], c[3]) for c in changes],
    )
    return "ok", changes


def feedback_text(status: str, changes, useful: bool) -> str:
    """Foydalanuvchiga ko'rsatiladigan qisqa javob matni."""
    if status == "missing":
        return "Bu bildirishnoma topilmadi (baza tozalangan bo'lishi mumkin)."
    if status == "done":
        return "Bu xabar allaqachon baholangan. Rahmat!"
    emoji = "✅" if useful else "❌"
    if not changes:
        return (
            f"{emoji} Qabul qilindi. Bu xabardagi so'zlar ro'yxatda "
            "topilmadi — vazn o'zgarmadi."
        )
    shown = ", ".join(f"{word} {old:+g}→{new:+g}" for _p, word, old, new in changes)
    return (
        f"{emoji} Qabul qilindi, {len(changes)} so'z vazni moslashdi:\n"
        f"{shown}"
    )
