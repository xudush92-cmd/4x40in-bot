"""Bildirishnoma yuborish va uni bezash (markaziy userbot YO'Q).

Bu modul faqat Telegram Bot API orqali xabar yuboradi va xabar matnini
tayyorlaydi. Skanerlash butunlay ``scanner_manager`` da: har bir
foydalanuvchi o'z sessiyasi bilan ishlaydi va topilgan xabar FAQAT
shu guruh egasiga boradi — boshqa foydalanuvchilarga tarqatilmaydi.

Eski "markaziy userbot" rejimi (bitta akkaunt, barcha oluvchilarga
tarqatish) ataylab olib tashlangan: u foydalanuvchilar ma'lumotini
aralashtirib yuborardi.

Fayl ``userbot.py`` deb nomlanmagan, chunki endi bu userbot emas.
"""
import html
import logging
import re

import aiohttp

from config import ADMIN_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

# O'zbekiston telefon raqamini topish uchun regex
PHONE_REGEX = re.compile(
    r"(\+?998|8)?[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"
)

async def send_to_bot_api(text, reply_markup=None, chat_id=None) -> bool:
    """Xabarni boshqaruv boti orqali berilgan chatga yuborish.

    chat_id berilmasa — ADMIN_ID (tizim xabarlari faqat adminga).
    Asosiy yuborish xato bersa (tugma/HTML sababli), bildirishnoma
    yo'qolmasligi uchun oddiy matn bilan qayta yuboriladi.
    """
    target = chat_id or ADMIN_ID
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                body = await resp.text()
                if resp.status == 200:
                    logger.info("[NOTIFY] Yuborildi (chat_id=%s)", target)
                    return True
                logger.warning("[NOTIFY] Bot API xatosi (%s): %s", resp.status, body)
            # Zaxira: tugmalarsiz va HTMLsiz oddiy matn
            plain = re.sub(r"<[^>]+>", "", text)
            async with session.post(
                url, json={"chat_id": target, "text": plain}
            ) as resp2:
                if resp2.status == 200:
                    logger.info("[NOTIFY] Zaxira matn yuborildi")
                    return True
                logger.error(
                    "[NOTIFY] Zaxira ham yuborilmadi (%s): %s",
                    resp2.status, await resp2.text(),
                )
    except Exception:
        logger.exception("[NOTIFY] Yuborishda tarmoq xatosi")
    return False


def build_message_link(chat, chat_id, message_id) -> str | None:
    """Xabarning o'ziga olib boradigan havola.

    Ochiq guruhda (username bo'lsa): https://t.me/username/123
    Superguruhda (username bo'lmasa): https://t.me/c/123456/123
    Oddiy yopiq guruhda Telegram to'g'ridan havola bermaydi -> None.
    """
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    raw_id = str(chat_id)
    if raw_id.startswith("-100"):
        return f"https://t.me/c/{raw_id[4:]}/{message_id}"
    return None


def find_phone_text(raw_text: str, sender=None) -> str:
    """Telefon: avval xabar matnidan, topilmasa profildan (agar ochiq bo'lsa)."""
    match = PHONE_REGEX.search(raw_text or "")
    if match:
        return match.group(0)
    profile_phone = getattr(sender, "phone", None)
    if profile_phone:
        digits = re.sub(r"\D", "", str(profile_phone))
        if digits:
            return f"+{digits} (Profil raqami)"
    return "Matnda ko'rsatilmagan"


def build_notification_text(
    *,
    group_title: str,
    sender_name: str,
    username: str,
    user_id,
    phone: str,
    raw_text: str,
    matched_words,
    required_count: int,
    message_link: str | None,
) -> str:
    """Bildirishnoma matni — skrinshotdagi ko'rinishda."""
    sep = "━━━━━━━━━━━━━━━"
    esc = html.escape

    if user_id is not None:
        sender_block = (
            f'👤 <b>Yuboruvchi:</b> '
            f'<a href="tg://user?id={user_id}">{esc(sender_name)}</a>'
        )
        if username and username != "Yo'q":
            sender_block += f"\n({esc(username)})"
        profile_line = (
            f'👉 <a href="tg://user?id={user_id}">'
            "Mijoz profiliga o'tish (Lichkasi)</a>"
        )
    else:
        sender_block = f"👤 <b>Yuboruvchi:</b> {esc(sender_name)}"
        profile_line = "💡 (Mijoz profiliga o'tish uchun asl xabarni oching)"

    lines = [
        "🚕 <b>YANGI BUYURTMA / MIJOZ TOPILDI!</b>",
        sep,
        f"📍 <b>Guruh:</b> {esc(group_title or 'Nomaʼlum guruh')}",
        sender_block,
        f"🆔 <b>Telegram ID:</b> <code>{user_id if user_id is not None else '—'}</code>",
        f"📞 <b>Telefon:</b> {esc(phone)}",
        "",
        "💬 <b>Xabar matni:</b>",
        esc(raw_text or ""),
        sep,
        f"✅ <b>Topilgan kalitlar ({len(matched_words)} ta):</b> "
        f"{esc(', '.join(matched_words))}",
        f"🔔 <b>Shart:</b> kamida {required_count} ta — bajarildi",
        sep,
        profile_line,
        "✍️ (Lichkasiga xabar yozish uchun ushbu xabarga «Reply / Javob» qiling)",
    ]
    if message_link:
        lines.append(
            f'🔗 <a href="{esc(message_link, quote=True)}">'
            "Guruhdagi asl xabarni ochish</a>"
        )
    return "\n".join(lines)
