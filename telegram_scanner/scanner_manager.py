"""Ko'p foydalanuvchili skaner: har bir foydalanuvchi — alohida sessiya.

Har bir tasdiqlangan foydalanuvchining shifrlangan sessiyasidan alohida
Telethon client ko'tariladi. Client FAQAT egasining guruhlarini kuzatadi,
xabar topilsa FAQAT egasiga boradi. Kalitlar va shart — adminniki (global).
"""
import asyncio
import datetime
import html
import logging
import time

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat

from config import ADMIN_ID, API_HASH, API_ID
from database import (
    get_all_users_full,
    get_keywords,
    get_match_count,
    get_notification_recipients,  # noqa: F401 (eski moslik)
    get_owner_active_chat_ids,
    get_pending_user_groups,
    get_setting,
    get_user_full,
    increment_counter,
    increment_user_counter,
    is_subscription_active,
    mark_user_group_error,
    mark_warned_today,
    resolve_user_group,
    set_session_status,
    set_user_last_found,
)
from login_manager import revoke_session
from matcher import find_match, match_keywords
from session_crypto import decrypt_session
from userbot import (
    build_message_link,
    build_notification_text,
    find_phone_text,
    send_to_bot_api,
)

logger = logging.getLogger(__name__)

_clients: dict[int, TelegramClient] = {}
_tasks: list[asyncio.Task] = []


def is_client_online(user_id: int) -> bool:
    client = _clients.get(user_id)
    return bool(client and client.is_connected())


async def _resolve_owner_groups(owner_id: int, client: TelegramClient) -> None:
    rows = get_pending_user_groups(owner_id)
    if not rows:
        return
    try:
        dialogs = await client.get_dialogs()
    except Exception:
        logger.warning("Dialoglarni olishda xato owner=%s", owner_id, exc_info=True)
        return
    by_id = {}
    by_username = {}
    for d in dialogs:
        try:
            by_id[utils.get_peer_id(d.entity)] = d.entity
            uname = getattr(d.entity, "username", None)
            if uname:
                by_username[uname.lower()] = d.entity
        except Exception:
            continue

    for gid, _owner, input_value, _chat, _status in rows:
        value = (input_value or "").strip()
        entity = None
        if "t.me/+" in value or "t.me/joinchat/" in value:
            mark_user_group_error(
                gid,
                "Yopiq havolani tekshirib bo'lmaydi: guruh ID sini (-100...) yuboring",
            )
            continue
        if value.lstrip("-").isdigit():
            num = int(value)
            candidates = [num]
            if num > 0:
                candidates += [-int(f"100{num}"), -num]
            for cand in candidates:
                if cand in by_id:
                    entity = by_id[cand]
                    break
            if entity is None:
                mark_user_group_error(
                    gid, "Akkauntingiz bu guruhda a'zo emas yoki ID noto'g'ri"
                )
                continue
        else:
            username = value.lstrip("@").lower()
            entity = by_username.get(username)
            if entity is None:
                # Dialogda yo'q — a'zo emas yoki username xato
                mark_user_group_error(
                    gid,
                    "Akkauntingiz bu guruhda a'zo emas yoki manzil noto'g'ri",
                )
                continue
        if isinstance(entity, Chat) or (
            isinstance(entity, Channel) and entity.megagroup
        ):
            resolve_user_group(
                gid, utils.get_peer_id(entity), getattr(entity, "title", "") or value
            )
            logger.info("[GROUP] owner=%s ulandi: %s", owner_id, value)
        else:
            mark_user_group_error(gid, "Bu guruh emas (kanal/foydalanuvchi)")


def _make_handler(owner_id: int, client: TelegramClient):
    @client.on(events.NewMessage)
    async def _handler(event):
        if not event.raw_text:
            return
        # 1. Tizim (admin) to'xtatganmi?
        if get_setting("is_active") != "1":
            return
        # 2. Egasi: bloklangan/tarifi tugagan bo'lsa — xabar yo'q
        if not is_subscription_active(owner_id):
            return
        # 3. Faqat EGASINING faol guruhlari
        if event.chat_id not in get_owner_active_chat_ids(owner_id):
            return
        # 4. Admin kalitlari + admin sharti
        keywords = get_keywords()
        required = get_match_count()
        result = match_keywords(event.raw_text, keywords, required)
        logger.info(
            "[SCAN] owner=%s chat=%s topildi=%s/%s",
            owner_id, event.chat_id, result.matched_count, required,
        )
        match = find_match(event.raw_text, keywords, required)
        if not match:
            return

        sender = await event.get_sender()
        sender_name, username, user_id = "Noma'lum", "Yo'q", getattr(sender, "id", None)
        if sender is not None:
            sender_name = (
                f"{getattr(sender, 'first_name', '') or ''} "
                f"{getattr(sender, 'last_name', '') or ''}"
            ).strip() or getattr(sender, "title", "") or "Noma'lum"
            if getattr(sender, "username", None):
                username = f"@{sender.username}"

        phone = find_phone_text(event.raw_text, sender)
        chat = await event.get_chat()
        group_title = getattr(chat, "title", None) or "Noma'lum guruh"
        message_link = build_message_link(chat, event.chat_id, event.id)
        text = build_notification_text(
            group_title=group_title,
            sender_name=sender_name,
            username=username,
            user_id=user_id,
            phone=phone,
            raw_text=event.raw_text,
            matched_words=match.matched_words,
            required_count=match.required_count,
            message_link=message_link,
        )
        rows = []
        if user_id is not None:
            rows.append([{"text": "💬 Mijozga yozish (Lichka)", "url": f"tg://user?id={user_id}"}])
        if message_link:
            rows.append([{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}])
        markup = {"inline_keyboard": rows} if rows else None

        # FAQAT egasiga (va adminga nusxa — admin nazorati uchun)
        increment_user_counter(owner_id, "leads_found")
        set_user_last_found(owner_id)
        increment_counter("leads_found")
        if await send_to_bot_api(text, markup, chat_id=owner_id):
            increment_counter("notifications_sent")

    return _handler


async def start_user_client(owner_id: int) -> bool:
    if owner_id in _clients:
        return True
    row = get_user_full(owner_id)
    if not row:
        return False
    # row: ... 8=session_enc, 10=awaiting
    session_enc, awaiting = row[8], row[10]
    if not session_enc or awaiting:
        return False
    session_str = decrypt_session(session_enc)
    if not session_str:
        set_session_status(owner_id, "invalid")
        return False
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            set_session_status(owner_id, "invalid")
            await client.disconnect()
            return False
        me = await client.get_me()
        if not me or me.id != owner_id:
            set_session_status(owner_id, "invalid")
            await client.disconnect()
            return False
    except Exception:
        logger.warning("Sessiya start xato owner=%s", owner_id, exc_info=True)
        try:
            await client.disconnect()
        except Exception:
            pass
        return False
    _make_handler(owner_id, client)
    _clients[owner_id] = client
    set_session_status(owner_id, "active")
    logger.info("[SESSION] owner=%s client ishga tushdi", owner_id)
    asyncio.create_task(_resolve_owner_groups(owner_id, client))
    return True


async def stop_user_client(owner_id: int, revoke: bool = False) -> None:
    client = _clients.pop(owner_id, None)
    if client:
        try:
            if revoke:
                await client.log_out()
            else:
                await client.disconnect()
        except Exception:
            pass
    if revoke:
        row = get_user_full(owner_id)
        if row and row[8]:
            await revoke_session(decrypt_session(row[8]))


async def _sync_loop():
    while True:
        try:
            online = set(_clients)
            should = set()
            for row in get_all_users_full():
                uid, blocked, session_enc, awaiting = row[0], row[3], row[8], row[10]
                if session_enc and not awaiting and not blocked and uid != ADMIN_ID:
                    should.add(uid)
            for uid in should - online:
                await start_user_client(uid)
            for uid in online - should:
                await stop_user_client(uid)
            # Har bir onlayn clientda egasining pending guruhlarini tekshirish
            for uid, client in list(_clients.items()):
                await _resolve_owner_groups(uid, client)
            from database import set_setting as _ss
            _ss("userbot_last_seen", int(time.time()))
        except Exception:
            logger.exception("Sync loop xato")
        await asyncio.sleep(60)


async def _expiry_warning_loop(bot_send=send_to_bot_api):
    """Tugashga <=3 kun: har kuni faqat 1 marta ogohlantirish."""
    while True:
        try:
            from database import get_expiring_users

            today = datetime.date.today().isoformat()
            for row in get_expiring_users(3):
                uid, expires, last_warn = row[0], row[4], row[12]
                if last_warn == today:
                    continue
                days_left = max(1, (expires - int(time.time()) + 86399) // 86400)
                date_text = time.strftime("%d.%m.%Y", time.localtime(expires))
                await bot_send(
                    "⏰ <b>Tarif muddatingiz tugayapti!</b>\n\n"
                    f"📅 Tugash sanasi: <b>{date_text}</b>\n"
                    f"⏳ Qolgan muddat: <b>{days_left} kun</b>\n\n"
                    "Davom ettirish uchun admin bilan bog'laning.",
                    chat_id=uid,
                )
                mark_warned_today(uid)
        except Exception:
            logger.exception("Expiry warning xato")
        await asyncio.sleep(3600)


async def run():
    """Barcha sessiyalar managerini ishga tushiradi (main.py dan)."""
    logger.info("Sessiya manageri ishga tushdi...")
    _tasks.append(asyncio.create_task(_sync_loop()))
    _tasks.append(asyncio.create_task(_expiry_warning_loop()))
    await asyncio.gather(*_tasks)
