import asyncio
import html
import logging
import re
import time

import aiohttp
from telethon import TelegramClient, events, utils
from telethon.tl.types import Channel, Chat

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
    get_keywords,
    get_match_count,
    get_pending_groups,
    get_setting,
    init_db,
    mark_managed_group_error,
    resolve_managed_group,
    set_setting,
)
from matcher import find_match, match_keywords

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    asyncio.get_event_loop()
except RuntimeError:  # Python 3.12+ da loop oldindan yaratilgan bo'lishi kerak
    asyncio.set_event_loop(asyncio.new_event_loop())

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# O'zbekiston telefon raqamini topish uchun regex
PHONE_REGEX = re.compile(
    r"(\+?998|8)?[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"
)


async def send_to_bot_api(text, reply_markup=None) -> bool:
    """Topilgan xabarni boshqaruv boti orqali ADMIN_ID ga yuborish.

    Manzil FAQAT Secrets dagi ADMIN_ID — boshqa joyga ketmaydi.
    Asosiy yuborish xato bersa (tugma/HTML sababli), bildirishnoma
    yo'qolmasligi uchun oddiy matn bilan qayta yuboriladi.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
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
                    logger.info("[NOTIFY] Adminga yuborildi (ADMIN_ID=%s)", ADMIN_ID)
                    return True
                logger.warning("[NOTIFY] Bot API xatosi (%s): %s", resp.status, body)
            # Zaxira: tugmalarsiz va HTMLsiz oddiy matn
            plain = re.sub(r"<[^>]+>", "", text)
            async with session.post(
                url, json={"chat_id": ADMIN_ID, "text": plain}
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


@client.on(events.NewMessage)
async def handler(event):
    if not event.raw_text:
        return

    keywords = get_keywords()
    required = get_match_count()
    active_ids = get_active_groups_ids()
    is_active_chat = event.chat_id in active_ids

    # Diagnostika: Replit logida [SCAN] deb qidiring — qaysi bosqichda
    # to'xtagani ko'rinadi.
    logger.info(
        "[SCAN] chat_id=%s faol_guruh=%s tizim=%s kalitlar=%s shart=%s xabar=%r",
        event.chat_id, is_active_chat, get_setting("is_active"),
        len(keywords), required, event.raw_text[:80],
    )

    # 1. Tizim yoqilganmi?
    if get_setting("is_active") != "1":
        logger.info("[SCAN] tashlandi: tizim ⏸ to'xtatilgan (botdan ▶️ yoqing)")
        return

    # 2. Xabar qo'lda qo'shilib, tekshirilgan va yoqilgan guruhdanmi?
    if not is_active_chat:
        logger.info(
            "[SCAN] tashlandi: bu guruh faol ro'yxatda yo'q "
            "(qo'shilmagan, tekshiruvda yoki ⏸ to'xtatilgan)"
        )
        return

    # 3-4. Kalit so'zlarni tekshirish: kalitlar soni cheksiz, admin
    # belgilagan soni (match_count) topilsa — xabar beriladi.
    result = match_keywords(event.raw_text, keywords, required)
    logger.info(
        "[SCAN] topilgan kalitlar=%s (%s/%s)",
        result.matched_words, result.matched_count, required,
    )
    match = find_match(event.raw_text, keywords, required)

    if not match:
        logger.info("[SCAN] tashlandi: kalitlar soni shartga yetmadi")
        return
    found_phrase = match.matched_words

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

    # Telefon: matndan, bo'lmasa profildan
    phone = find_phone_text(event.raw_text, sender)

    chat = await event.get_chat()
    group_title = getattr(chat, "title", None) or "Noma'lum guruh"

    # Xabarning o'ziga olib boradigan havola (ochiq/superguruhda ishlaydi)
    message_link = build_message_link(chat, event.chat_id, event.id)

    result_text = build_notification_text(
        group_title=group_title,
        sender_name=sender_name,
        username=username,
        user_id=user_id,
        phone=phone,
        raw_text=event.raw_text,
        matched_words=found_phrase,
        required_count=match.required_count,
        message_link=message_link,
    )

    # Tugmalar: skrinshotdagi kabi alohida qatorlarda
    button_rows = []
    if user_id is not None:
        button_rows.append(
            [{"text": "💬 Mijozga yozish (Lichka)", "url": f"tg://user?id={user_id}"}]
        )
    if message_link:
        button_rows.append(
            [{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}]
        )
    buttons = {"inline_keyboard": button_rows} if button_rows else None

    await send_to_bot_api(result_text, buttons)


def _is_group_entity(entity) -> bool:
    """Faqat guruhlar: oddiy guruh (Chat) yoki superguruh (megagroup).

    Kanallar (broadcast) skaner qilinmaydi.
    """
    if isinstance(entity, Chat):
        return True
    if isinstance(entity, Channel):
        return bool(entity.megagroup)
    return False


async def _resolve_one(row, dialogs_by_id) -> None:
    gid, input_value, _chat_id, prev_status = row
    value = (input_value or "").strip()
    entity = None

    try:
        if "t.me/+" in value or "t.me/joinchat/" in value:
            mark_managed_group_error(
                gid,
                "Yopiq taklif havolasini tekshirib bo'lmaydi: userbot "
                "guruhga a'zo bo'lsa, guruhning raqamli ID sini (-100...) yuboring",
            )
            if prev_status == "pending":
                await send_to_bot_api(
                    f"⚠️ Guruh qo'shilmadi: <code>{html.escape(value)}</code>\n"
                    "Yopiq havola tekshirilmaydi — guruh ID sini (-100...) yuboring."
                )
            return

        if value.lstrip("-").isdigit():
            num = int(value)
            # event.chat_id formati: superguruhda -100..., oddiy guruhda -...
            candidates = [num]
            if num > 0:
                candidates += [-int(f"100{num}"), -num]
            for cand in candidates:
                if cand in dialogs_by_id:
                    entity = dialogs_by_id[cand]
                    break
            if entity is None:
                mark_managed_group_error(
                    gid,
                    "Bu ID dialoglarda topilmadi: userbot shu guruhda a'zo emas "
                    "yoki ID noto'g'ri",
                )
                if prev_status == "pending":
                    await send_to_bot_api(
                        f"⚠️ Guruh topilmadi: <code>{html.escape(value)}</code>\n"
                        "Userbot shu guruhda a'zo ekanini tekshiring yoki "
                        "ID to'g'riligini qayta ko'ring, keyin 🔄 Qayta tekshirish bosing."
                    )
                return
        else:
            username = value.lstrip("@")
            try:
                found = await client.get_entity(username)
            except Exception:
                mark_managed_group_error(
                    gid, "Bunday username topilmadi yoki mavjud emas"
                )
                if prev_status == "pending":
                    await send_to_bot_api(
                        f"⚠️ Guruh topilmadi: <code>{html.escape(value)}</code>\n"
                        "Manzilni tekshirib, 🔄 Qayta tekshirish bosing."
                    )
                return
            # A'zolik dialoglarda borligi bilan tasdiqlanadi
            if utils.get_peer_id(found) not in dialogs_by_id:
                mark_managed_group_error(
                    gid,
                    "Userbot bu guruhda a'zo emas: avval skaner akkauntini "
                    "guruhga qo'shing, keyin 🔄 Qayta tekshirish bosing",
                )
                if prev_status == "pending":
                    await send_to_bot_api(
                        f"⚠️ Userbot <b>{html.escape(value)}</b> guruhida a'zo emas.\n"
                        "Avval skaner akkauntini guruhga qo'shing, keyin botda "
                        "🔄 Qayta tekshirish tugmasini bosing."
                    )
                return
            entity = found

        if not _is_group_entity(entity):
            mark_managed_group_error(
                gid, "Bu guruh emas (kanal yoki foydalanuvchi) — faqat guruhlar qo'shiladi"
            )
            if prev_status == "pending":
                await send_to_bot_api(
                    f"⚠️ <b>{html.escape(value)}</b> — bu guruh emas, "
                    "faqat guruhlar skaner qilinadi."
                )
            return

        marked_id = utils.get_peer_id(entity)
        title = getattr(entity, "title", None) or value
        if resolve_managed_group(gid, marked_id, title) and prev_status != "ok":
            logger.info("Guruh ulandi: %s (%s)", title, marked_id)
            await send_to_bot_api(
                f"✅ <b>Guruh ulandi!</b>\n\n"
                f"👥 {html.escape(title)}\n"
                f"🆔 <code>{marked_id}</code>\n\n"
                "Endi bu guruh skanerlanadi. To'xtatish uchun: "
                "📋 Guruhlarim → ⏸ To'xtatish"
            )
    except Exception as exc:  # bitta guruhdagi xato boshqalarini to'xtatmasin
        logger.exception("Guruhni tekshirishda xato (%s)", value)
        mark_managed_group_error(gid, f"Tekshiruv xatosi: {exc}")


async def resolve_pending_groups() -> None:
    """Qo'lda qo'shilgan, tekshiruvdagi guruhlarni tekshiradi."""
    rows = get_pending_groups()
    if not rows:
        return
    dialogs = await client.get_dialogs()
    dialogs_by_id = {}
    for d in dialogs:
        try:
            dialogs_by_id[utils.get_peer_id(d.entity)] = d.entity
        except Exception:
            continue
    for row in rows:
        await _resolve_one(row, dialogs_by_id)


async def _group_resolver_loop() -> None:
    """Har 30 soniyada guruhlarni tekshiradi va 'tirik' signalini yozadi.

    Botdagi 📊 holatda userbot onlaynligi shu signal orqali ko'rinadi.
    """
    while True:
        try:
            set_setting("userbot_last_seen", int(time.time()))
            await resolve_pending_groups()
        except Exception:
            logger.exception("Guruh tekshiruvida xato")
        await asyncio.sleep(30)


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

    # MUHIM: endi akkauntdagi BARCHA guruhlar avtomatik yozilmaydi.
    # Faqat botdan qo'lda qo'shilgan guruhlar tekshiriladi va skanerlanadi.
    resolver_task = asyncio.create_task(_group_resolver_loop())
    logger.info("Skaner tayyor: faqat qo'lda qo'shilgan guruhlar kuzatiladi.")
    try:
        await client.run_until_disconnected()
    finally:
        resolver_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
