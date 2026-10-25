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


def _message_id() -> int | None:
    value = get_setting(MSG_KEY)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _set_message_id(message_id: int | None) -> None:
    set_setting(MSG_KEY, str(int(message_id)) if message_id else "")


# --- Telegram Bot API (bot tomonidagi yordamchilar) ---

async def _api(method: str, payload: dict) -> dict | None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json(content_type=None)
    except Exception:
        logger.exception("[REVIEW] API xatosi: %s", method)
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    return data.get("result")


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
    lines = [
        "🔍 <b>Nazorat — baholash</b>",
        f"<i>Kutilayotgan: {stats['pending']} ta · jami {stats['total']} ta</i>",
        "",
        f"<b>Xabar #{item_id}</b>",
        f"«{shown}»",
        "",
        f"⚖️ Ball: <b>{float(score):g}</b> (chegara {float(threshold):g})",
        f"🔑 So'zlar: {_words_line(words)}",
        "",
        "Bu xabar mijoz xabari deb qabul qilindi. <b>To'g'rimi?</b>",
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
        f"⏭ {stats['skip']}\n\n"
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
            if result is not None:
                return
            # Xabar o'chirilgan yoki tahrirlab bo'lmayapti — yangisini yuboramiz.
            _set_message_id(None)
        result = await _api("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": markup,
        })
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
