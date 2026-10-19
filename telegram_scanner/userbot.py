import asyncio
import html
import logging
import re

import aiohttp
from telethon import TelegramClient, events

from config import (
    ADMIN_ID,
    API_HASH,
    API_ID,
    BOT_TOKEN,
    SESSION_NAME,
    missing_settings,
)
from database import (
    get_active_groups_ids,
    get_phrases,
    get_setting,
    init_db,
    save_groups,
)
from matcher import find_match

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# O'zbekiston telefon raqamini topish uchun regex
PHONE_REGEX = re.compile(
    r"(\+?998|8)?[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"
)


async def send_to_bot_api(text, reply_markup=None):
    """Topilgan xabarni boshqaruv boti orqali adminga yuborish."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                logger.warning(
                    "Bot API xatosi (%s): %s", resp.status, await resp.text()
                )


@client.on(events.NewMessage)
async def handler(event):
    if not event.raw_text:
        return

    # 1. Tizim yoqilganmi?
    if get_setting("is_active") != "1":
        return

    # 2. Xabar kuzatilayotgan guruhdanmi?
    if event.chat_id not in get_active_groups_ids():
        return

    # 3-4. Ko'p so'zli kalitlarni tekshirish: iboradagi BARCHA so'zlar
    # xabarda bo'lsa mos hisoblanadi (tartib/oraliq so'zlar muhim emas).
    # Batafsil: matcher.py
    found_phrase = find_match(event.raw_text, get_phrases())

    if not found_phrase:
        return

    sender = await event.get_sender()
    # Kanal nomidan yozilgan xabarlarda sender None bo'lishi mumkin
    sender_name = "Noma'lum"
    username = "Yo'q"
    user_id = getattr(sender, "id", None)
    if sender is not None:
        sender_name = (
            f"{getattr(sender, 'first_name', '') or ''} "
            f"{getattr(sender, 'last_name', '') or ''}"
        ).strip() or getattr(sender, "title", "") or "Noma'lum"
        if getattr(sender, "username", None):
            username = f"@{sender.username}"

    # Telefon raqamini qidirish
    phone_match = PHONE_REGEX.search(event.raw_text)
    phone = phone_match.group(0) if phone_match else "Matnda topilmadi"

    chat = await event.get_chat()
    group_title = getattr(chat, "title", None) or "Noma'lum guruh"

    result_text = (
        "🚖 <b>YANGI MIJOZ TOPILDI!</b>\n\n"
        f"📍 <b>Guruh:</b> {html.escape(group_title)}\n"
        f"👤 <b>Yuboruvchi:</b> {html.escape(sender_name)} ({html.escape(username)})\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id if user_id is not None else '—'}</code>\n"
        f"📞 <b>Telefon:</b> {html.escape(phone)}\n\n"
        f"💬 <b>Xabar matni:</b>\n<i>{html.escape(event.raw_text)}</i>\n\n"
        f"🔍 <b>Topilgan ibora:</b> {html.escape(found_phrase)}\n"
        f"📊 <b>O'xshashlik:</b> {match.percent}% "
        f"({match.matched_count}/{match.total_words} so'z topildi)"
    )

    # Supergroup ID: -100xxxxxxxxxx -> ichki qism havola uchun
    raw_id = str(event.chat_id)
    internal_id = raw_id[4:] if raw_id.startswith("-100") else raw_id.lstrip("-")

    buttons = [
        [{"text": "🔗 Asl xabarni ochish", "url": f"https://t.me/c/{internal_id}/{event.id}"}]
    ]
    if user_id is not None:
        buttons[0].insert(
            0, {"text": "💬 Mijozga yozish", "url": f"tg://user?id={user_id}"}
        )

    await send_to_bot_api(result_text, {"inline_keyboard": buttons})


async def main():
    missing = missing_settings()
    if missing:
        raise SystemExit(
            "❌ Sozlamalar yetishmaydi: "
            + ", ".join(missing)
            + ". telegram_scanner/.env faylini .env.example asosida to'ldiring."
        )
    init_db()
    logger.info("Userbot ishga tushdi...")
    await client.start()  # birinchi marta telefon raqami/kod so'raydi

    # Akkaunt a'zo bo'lgan barcha guruhlarni bazaga yozish (sinxronizatsiya)
    logger.info("Guruhlar sinxronizatsiya qilinmoqda...")
    dialogs = await client.get_dialogs()
    groups = [d.entity for d in dialogs if d.is_group or d.is_channel]
    save_groups(groups)
    logger.info("%s ta guruh bazaga saqlandi.", len(groups))

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
