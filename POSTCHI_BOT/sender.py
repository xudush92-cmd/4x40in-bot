"""
sender.py — E'lonni bitta guruhga yuborish (Bot API).

Bot e'lonni O'ZI yuboradi, shuning uchun inline tugmalar to'liq ishlaydi:
- 📞 Bog'lanish → e'lon beruvchi kontaktiga
- 📢 E'lon berish → referal havola (bot username + ref_<uid>)

Entitylar (bold/italic/link) PTB MessageEntity sifatida saqlanadi va
qayta tiklanadi.
"""

from __future__ import annotations

import json
import logging
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
)

from config import BOT_USERNAME, SEND_TIMEOUT_S

logger = logging.getLogger("PostchiBot")


# ─────────────────────────────────────────────────────────────────────────
# ENTITY (PTB MessageEntity <-> dict)
# ─────────────────────────────────────────────────────────────────────────
def entity_to_dict(e: MessageEntity) -> dict:
    d = {"type": e.type, "offset": e.offset, "length": e.length}
    if e.url:
        d["url"] = e.url
    if e.language:
        d["language"] = e.language
    if e.custom_emoji_id:
        d["custom_emoji_id"] = e.custom_emoji_id
    return d


def entities_to_json(entities: list[MessageEntity] | None) -> str:
    return json.dumps([entity_to_dict(e) for e in (entities or [])], ensure_ascii=False)


def json_to_entities(raw: str) -> list[MessageEntity]:
    out: list[MessageEntity] = []
    try:
        items = json.loads(raw or "[]")
    except Exception:
        return out
    for d in items:
        try:
            out.append(
                MessageEntity(
                    type=d["type"],
                    offset=int(d["offset"]),
                    length=int(d["length"]),
                    url=d.get("url"),
                    language=d.get("language"),
                    custom_emoji_id=d.get("custom_emoji_id"),
                )
            )
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────────────────────────────────
# E'LON OSTIDAGI TUGMALAR
# ─────────────────────────────────────────────────────────────────────────
def _contact_url(contact: str) -> str | None:
    """Kontaktni bosiladigan URL ga aylantiradi (@username yoki telefon)."""
    c = (contact or "").strip()
    if not c:
        return None
    if c.startswith("@"):
        return f"https://t.me/{c[1:]}"
    if c.startswith("https://t.me/") or c.startswith("http"):
        return c
    # Telefon raqam — tel: link
    digits = c.lstrip("+")
    if digits.isdigit():
        return f"tel:{c}"
    return None


def build_ad_keyboard(uid: int, contact: str) -> InlineKeyboardMarkup | None:
    """E'lon ostidagi 2 tugma: 📞 Bog'lanish + 📢 E'lon berish (referal)."""
    buttons = []

    contact_url = _contact_url(contact)
    if contact_url:
        buttons.append(InlineKeyboardButton("📞 Bog'lanish", url=contact_url))

    ref_url = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    buttons.append(InlineKeyboardButton("📢 E'lon berish", url=ref_url))

    if not buttons:
        return None
    return InlineKeyboardMarkup([buttons])


# ─────────────────────────────────────────────────────────────────────────
# YUBORISH
# ─────────────────────────────────────────────────────────────────────────
async def send_ad_to_group(bot, chat_id: int, ad: dict) -> None:
    """
    Bitta e'lonni bitta guruhga yuboradi.

    Xato bo'lsa exception ko'tariladi — chaqiruvchi (worker) ushlaydi.
    """
    text = ad.get("text_content", "") or ""
    entities = json_to_entities(ad.get("entities", "[]"))
    photo_path = ad.get("photo_path")
    contact = ad.get("contact", "") or ""
    uid = ad.get("uid")

    keyboard = build_ad_keyboard(uid, contact)

    if photo_path and os.path.exists(photo_path):
        with open(photo_path, "rb") as f:
            await bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=text or None,
                caption_entities=entities or None,
                reply_markup=keyboard,
                read_timeout=SEND_TIMEOUT_S,
                write_timeout=SEND_TIMEOUT_S,
            )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            entities=entities or None,
            reply_markup=keyboard,
            read_timeout=SEND_TIMEOUT_S,
            write_timeout=SEND_TIMEOUT_S,
        )
