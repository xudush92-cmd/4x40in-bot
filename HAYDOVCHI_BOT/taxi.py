"""
taxi.py — yo'lovchi "🚕 Taksi chaqirish" tugmasi.

Oqim:
1. Yo'lovchi guruh oynasi ostidagi tugmani bosadi (botga yozish shart emas).
2. Bot shu guruhda hozir faol e'loni bor, taksi yoqqan haydovchilarga so'rov yuboradi:
   yo'lovchining ismi, @username, guruh nomi, vaqt va 2 ta tugma.
3. Haydovchi "👤 Bog'lanish" bilan yo'lovchiga yozadi, yoki
   "🔕 So'rovlarni to'xtatish" bilan barcha taksi so'rovlarini o'chiradi
   (qayta yoqish haydovchi menyusida).

Spamdan himoya: bir yo'lovchi har guruhda TAXI_COOLDOWN_SEC da bir marta so'rov yuboradi.
"""

from __future__ import annotations

import logging
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, User as TgUser
from telegram.error import TelegramError

from db import Database
from utils import LOCAL_TZ
from datetime import datetime

log = logging.getLogger("haydovchi.taxi")

TAXI_COOLDOWN_SEC = 180

BTN_MUTE = "🔕 So'rovlarni to'xtatish"
MUTE_CALLBACK = "tmx"


def _contact_url(passenger: TgUser) -> str:
    if passenger.username:
        return f"https://t.me/{passenger.username}"
    return f"tg://user?id={passenger.id}"


def _request_text(group_title: str, passenger: TgUser, now: int) -> str:
    who = passenger.full_name
    if passenger.username:
        who += f" (@{passenger.username})"
    when = datetime.fromtimestamp(now, LOCAL_TZ).strftime("%H:%M")
    return (
        "🚕 Taksi so'rovi\n"
        f"🏘 {group_title or 'Guruh'}\n"
        f"👤 {who}\n"
        f"🕐 {when}"
    )


def _request_kb(passenger: TgUser) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Bog'lanish", url=_contact_url(passenger))],
        [InlineKeyboardButton(BTN_MUTE, callback_data=MUTE_CALLBACK)],
    ])


async def passenger_request(bot: Bot, db: Database, chat_id: int, passenger: TgUser) -> str:
    """
    Yo'lovchi so'rovini qayta ishlaydi. Yo'lovchiga ko'rsatiladigan matnni qaytaradi.
    """
    now = int(time.time())
    group = await db.get_group(chat_id)
    if group is None or not group["taxi_enabled"]:
        return "Bu guruhda taksi xizmati yoqilmagan."

    last = await db.taxi_last_request(chat_id, passenger.id)
    wait = TAXI_COOLDOWN_SEC - (now - last)
    if last and wait > 0:
        return f"⏳ Iltimos, {wait} soniyadan keyin qayta urinib ko'ring."

    recipients = await db.taxi_recipients(chat_id, now)
    if not recipients:
        return "Hozir faol taksi haydovchi yo'q."

    text = _request_text(group["title"], passenger, now)
    kb = _request_kb(passenger)
    sent = 0
    for uid in recipients:
        try:
            await bot.send_message(chat_id=uid, text=text, reply_markup=kb)
            sent += 1
        except TelegramError as e:
            log.info("Taksi so'rovi yuborilmadi (%s): %s", uid, e)

    if sent == 0:
        return "Hozir taksi haydovchiga yetkazib bo'lmadi. Keyinroq urinib ko'ring."
    await db.add_taxi_log(chat_id, passenger.id, now)
    return "✅ So'rov taksi haydovchilariga yuborildi."


async def mute_driver(db: Database, driver_id: int) -> None:
    """Haydovchi barcha taksi so'rovlarini to'xtatadi (menyudan qayta yoqiladi)."""
    await db.update_user_fields(driver_id, taxi_on=0)
