"""Nazorat (o'qitish) rejimi — admin BOT ICHIDA slayd ko'rinishida baholaydi.

Muammo: vaznli model xato qilsa, buni faqat foydalanuvchi sezadi va u
umumiy kalitlarni o'zgartirishga haqli emas (kalitlar hammaga umumiy —
bitta xato bosish boshqalarga zarar qiladi).

Yechim: har topilgan xabar nusxasi **adminning botdagi shaxsiy chatiga**
tushadi. Chatda BITTA xabar turadi (slayd) va bot uni tahrirlab turadi —
chat xabarga to'lib ketmaydi, eski nusxalar ustiga yangisi yoziladi.
Admin `✅ To'g'ri / ❌ Noto'g'ri / ⏭ O'tkazish` ni bosadi va faqat
shundan keyin vazn o'zgaradi.

**Guruh kerak emas**: guruhlar bilan bog'liq hech qanday sozlama yo'q.
Slayd faqat ``ADMIN_ID`` ga (botning shaxsiy chatiga) yuboriladi.

Maxfiylik:

* nusxada **egasi, ismi, telefoni, guruh nomi saqlanmaydi** — faqat matn,
  ball va qaysi so'zlar ishlagani. Boshqa foydalanuvchi hech narsa
  ko'rmaydi.
* baholanmagan xabar avtomatik ravishda 90 kundan keyin o'chadi
  (``database.purge_review_items``).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging

import aiohttp

import feedback as fb
from config import ADMIN_ID, BOT_TOKEN
from database import (
    add_review_item,
    get_next_review_item,
    get_review_item,
    get_setting,
    purge_review_items,
    review_stats,
    set_review_item_label,
    set_setting,
    update_phrase,
)

logger = logging.getLogger(__name__)

CHAT_KEY = "review_chat_id"      # adminning shaxsiy chati (bot ichida)
MSG_KEY = "review_msg_id"        # slayd bo'lib turadigan bitta xabar

# Bir xabarni 90 kundan ortiq saqlamaymiz.
KEEP_DAYS = 90

# ⚡ Chegaraga yaqin xabarlar: ball chegaradan past, lekin shu qiymatdan
# yuqori bo'lsa navbatga tushadi. Maqsad — model O'TKAZIB YUBORGAN
# mijozlarni ham ko'rish (aks holda faqat xatolar ko'rinadi).
NEAR_MIN = 1.0
# Navbatda shuncha baholanmagan xabar to'plansa, yangi "chegarada"
# xabarlar qo'shilmaydi (navbat cheksiz o'smasin).
NEAR_MAX_PENDING = 300
# Bir vaqtda bitta slayd yangilanadi — poyga bo'lmasin.
_lock = asyncio.Lock()

LABEL_TITLES = {
    "ok": "✅ To'g'ri (mijoz)",
    "bad": "❌ Noto'g'ri",
    "skip": "⏭ O'tkazish",
}


# --- Sozlamalar ---

def review_chat_id() -> int | None:
    """Slayd yuboriladigan chat — faqat adminning shaxsiy chati.

    Guruh/kanal ID saqlanib qolgan bo'lsa (eski sozlama) — e'tiborsiz
    qoldiriladi: slayd hech qachon guruhga ketmaydi.
    """
    value = get_setting(CHAT_KEY)
    try:
        chat_id = int(value) if value else None
    except (TypeError, ValueError):
        return None
    if not chat_id or not ADMIN_ID or chat_id != int(ADMIN_ID):
        return None
    return chat_id


def set_review_chat(chat_id: int) -> None:
    """Nazoratni yoqadi (``ADMIN_ID``) yoki o'chiradi (``0``).

    Boshqa chat ID (masalan guruh) **qabul qilinmaydi** — guruhga
    yuborilgan slayd boshqa odamlarga ko'rinardi.
    """
    chat_id = int(chat_id or 0)
    if chat_id and (not ADMIN_ID or chat_id != int(ADMIN_ID)):
        logger.warning("[REVIEW] faqat adminning shaxsiy chati: %s rad etildi", chat_id)
        return
    set_setting(CHAT_KEY, str(chat_id) if chat_id else "")


async def disable() -> None:
    """Nazoratni o'chiradi va slayddagi eski baholash tugmalarini olib tashlaydi."""
    chat_id = review_chat_id()
    message_id = _message_id()
    set_review_chat(0)
    try:
        if chat_id and message_id:
            await _api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "🔕 <b>Nazorat o'chirildi</b>\n\n"
                        "Nusxalar endi navbatga kelmaydi. Qayta ochish uchun "
                        "🛠 Admin panel → 🎓 Nazorat (baholash) ni bosing.",
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": []},
            })
    finally:
        # Qayta yoqilganda eski, o'chirilgan slaydni tahrirlashga urinmasin.
        _set_message_id(None)


def _message_id() -> int | None:
    value = get_setting(MSG_KEY)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _set_message_id(message_id: int | None) -> None:
    set_setting(MSG_KEY, str(int(message_id)) if message_id else "")


# --- Telegram Bot API (bot tomonidagi yordamchilar) ---

# Bitta doimiy HTTP sessiya: har chaqiruvda TCP/TLS ulanish ochmaydi.
# Bot API javobi sust bo'lsa, bir urinish 4.5 sekunddan oshmaydi.
_api_session: aiohttp.ClientSession | None = None
_API_TIMEOUT = aiohttp.ClientTimeout(
    total=4.5, connect=2.0, sock_connect=2.0, sock_read=3.0
)
_API_TEMPORARY_FAILURE = object()


async def _get_api_session() -> aiohttp.ClientSession:
    global _api_session
    if _api_session is None or _api_session.closed:
        _api_session = aiohttp.ClientSession(timeout=_API_TIMEOUT)
    return _api_session


async def close_api_session() -> None:
    """Bot to'xtaganda ulashilgan HTTP sessiyani to'g'ri yopadi."""
    global _api_session
    session, _api_session = _api_session, None
    if session is not None and not session.closed:
        await session.close()


async def _api(method: str, payload: dict):
    """Bot API chaqiruvi: ulanishni qayta ishlatadi va vaqtincha xatoda retry.

    ``_API_TEMPORARY_FAILURE`` tarmoq/timeout xatosini bildiradi; bu oddiy
    Telegram API rad javobidan alohida, shuning uchun edit muvaffaqiyatsiz
    bo'lganda eski slayd ustiga ortiqcha yangi xabar yuborilmaydi.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    # edit* ni qayta urinib ko'rish xavfsiz (xabar ID o'zgarmaydi).
    # sendMessage da timeoutdan so'ng Telegram xabarni yetkazgan, ammo
    # javob yo'qolgan bo'lishi mumkin — retry yangi dublikat yaratadi.
    attempts = 2 if method.startswith("edit") else 1
    for attempt in range(attempts):
        try:
            session = await _get_api_session()
            async with session.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 500 or resp.status == 429:
                    if attempt + 1 < attempts:
                        logger.warning(
                            "[REVIEW] API %s HTTP %s, yana urinadi",
                            method, resp.status,
                        )
                        await asyncio.sleep(0.2)
                        continue
                    logger.error(
                        "[REVIEW] API %s vaqtincha HTTP %s qaytardi",
                        method, resp.status,
                    )
                    return _API_TEMPORARY_FAILURE
                if not isinstance(data, dict) or not data.get("ok"):
                    description = data.get("description", "javob xato") if isinstance(data, dict) else "javob xato"
                    # Tahrirlangan matn allaqachon aynan shunday bo'lsa,
                    # Telegram 400 qaytaradi. Bu muvaffaqiyatga teng —
                    # aks holda refresh ikkinchi, takroriy slayd yuborardi.
                    if method.startswith("edit") and "message is not modified" in description.lower():
                        return {"message_id": payload.get("message_id")}
                    logger.warning(
                        "[REVIEW] API %s rad etdi (HTTP %s): %s",
                        method, resp.status, description,
                    )
                    return None
                return data.get("result")
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if attempt + 1 < attempts:
                logger.warning(
                    "[REVIEW] API %s vaqtincha xato (%s); qayta urinadi",
                    method, type(exc).__name__,
                )
                await asyncio.sleep(0.2)
                continue
            logger.error(
                "[REVIEW] API %s %s urinishda bajarilmadi (%s)",
                method, attempts, type(exc).__name__,
            )
            return _API_TEMPORARY_FAILURE
        except Exception:
            logger.exception("[REVIEW] API %s kutilmagan xato", method)
            return _API_TEMPORARY_FAILURE
    return _API_TEMPORARY_FAILURE


def near_miss(score, threshold) -> bool:
    """Xabar chegaraga yaqin, lekin o'tmaganmi (⚡)."""
    try:
        score_f = float(score)
        threshold_f = float(threshold)
    except (TypeError, ValueError):
        return False
    if threshold_f <= 0:
        return False
    return NEAR_MIN <= score_f < threshold_f


def is_near_item(item) -> bool:
    """Navbatdagi yozuv ⚡ chegarada bo'lganmi (``item`` — DB qatori)."""
    if not item or len(item) < 4:
        return False
    return near_miss(item[2], item[3])


# --- Slayd matni va tugmalari ---

def _words_line(words) -> str:
    if not words:
        return "—"
    return ", ".join(html.escape(str(w), quote=False) for w in words)


def slide_text(item) -> str:
    """Bitta xabarning slayd ko'rinishi."""
    item_id, text, score, threshold, words_raw = item
    try:
        words = json.loads(words_raw or "[]")
    except (TypeError, ValueError):
        words = []
    stats = review_stats()
    shown = html.escape(str(text or ""), quote=False)
    near = near_miss(score, threshold)
    head = (
        "⚡ <b>Chegarada — o'tmadi</b>"
        if near
        else "✅ <b>O'tgan xabar</b>"
    )
    question = (
        "Model buni <b>o'tkazib yubordi</b>. Mijoz xabarimi?"
        if near
        else "Bu xabar mijoz xabari deb qabul qilindi. <b>To'g'rimi?</b>"
    )
    lines = [
        "🔍 <b>Nazorat — baholash</b>",
        f"<i>Kutilayotgan: {stats['pending']} ta · jami {stats['total']} ta "
        f"(⚡ {stats['near']} ta)</i>",
        "",
        head,
        f"<b>Xabar #{item_id}</b>",
        f"«{shown}»",
        "",
        f"⚖️ Ball: <b>{float(score):g}</b> (chegara {float(threshold):g})",
        f"🔑 So'zlar: {_words_line(words)}",
        "",
        question,
    ]
    return "\n".join(lines)


def slide_keyboard(item) -> dict:
    item_id = item[0]
    return {"inline_keyboard": [
        [
            {"text": "✅ To'g'ri", "callback_data": f"rv:ok:{item_id}"},
            {"text": "❌ Noto'g'ri", "callback_data": f"rv:bad:{item_id}"},
        ],
        [
            {"text": "⏭ O'tkazish", "callback_data": f"rv:skip:{item_id}"},
            {"text": "📊 Statistika", "callback_data": "rv:stats:0"},
        ],
    ]}


def empty_text() -> str:
    stats = review_stats()
    return (
        "✅ <b>Navbat bo'sh</b>\n\n"
        f"Jami: {stats['total']} · ✅ {stats['ok']} · ❌ {stats['bad']} · "
        f"⏭ {stats['skip']} · ⚡ {stats['near']}\n\n"
        "Yangi xabar kelganda shu xabar o'zi yangilanadi — chat to'lmaydi."
    )


def stats_text() -> str:
    stats = review_stats()
    labeled = stats["ok"] + stats["bad"]
    if labeled:
        share = round(100 * stats["ok"] / labeled)
        line = f"✅ To'g'ri: {stats['ok']} ({share}%) · ❌ Noto'g'ri: {stats['bad']}"
    else:
        line = "Hozircha hech narsa baholanmagan."
    return (
        "📊 <b>Nazorat statistikasi</b>\n\n"
        f"{line}\n"
        f"⏭ O'tkazilgan: {stats['skip']}\n"
        f"⚡ Chegarada (o'tmagan): {stats['near']}\n"
        f"⏳ Kutilayotgan: {stats['pending']}\n"
        f"Jami: {stats['total']}"
    )


# --- Slaydni yangilash ---

async def refresh(force_new: bool = False) -> None:
    """Slayd xabarini joriy holatga keltiradi (edit; bo'lmasa — yangi)."""
    chat_id = review_chat_id()
    if not chat_id:
        return
    async with _lock:
        item = get_next_review_item()
        if item:
            text, markup = slide_text(item), slide_keyboard(item)
        else:
            text, markup = empty_text(), {"inline_keyboard": [[
                {"text": "📊 Statistika", "callback_data": "rv:stats:0"},
            ]]}
        message_id = None if force_new else _message_id()
        if message_id:
            result = await _api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": markup,
            })
            if result is _API_TEMPORARY_FAILURE:
                return
            if result is not None:
                return
            # API javobi kelib, eski xabar topilmagan bo'lsa — yangisini yuboramiz.
            _set_message_id(None)
        result = await _api("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": markup,
        })
        if result is _API_TEMPORARY_FAILURE:
            return
        if isinstance(result, dict):
            _set_message_id(result.get("message_id"))


# --- Navbatga qo'shish ---

async def enqueue(text: str, score: float = 0.0, threshold: float = 0.0,
                  words=None) -> int:
    """Topilgan xabarni navbatga qo'shadi va slaydni yangilaydi."""
    item_id = add_review_item(text, score, threshold, words)
    if item_id:
        await refresh()
    return item_id


# --- Baholash ---

async def label(item_id: int, choice: str) -> tuple[str, list, dict]:
    """Yorliqni yozadi; ``ok/bad`` da vaznlar ham moslashadi.

    Qaytaradi: ``(holat, o'zgarishlar, statistika)`` — holat
    ``ok`` / ``done`` / ``missing`` / ``bad-choice``.
    """
    if choice not in ("ok", "bad", "skip"):
        return "bad-choice", [], review_stats()
    row = get_review_item(item_id)
    if not row:
        return "missing", [], review_stats()
    if not set_review_item_label(item_id, choice):
        return "done", [], review_stats()
    changes = []
    if choice in ("ok", "bad"):
        try:
            words = json.loads(row[4] or "[]")
        except (TypeError, ValueError):
            words = []
        # ``ok`` -> musbat so'zlar kuchayadi; ``bad`` -> zaiflashadi.
        changes = fb.compute_changes(words, choice == "ok")
        for pid, _word, _old, new in changes:
            update_phrase(pid, weight=new)
        logger.info(
            "[REVIEW] item=%s choice=%s so'zlar=%s",
            item_id, choice, [(c[1], c[3]) for c in changes],
        )
    else:
        logger.info("[REVIEW] item=%s o'tkazildi", item_id)
    return "ok", changes, review_stats()


def purge_old() -> int:
    return purge_review_items(KEEP_DAYS)
