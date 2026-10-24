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
    get_pending_user_groups,
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
from filters import evaluate, summary_line
from session_crypto import decrypt_session
from notifier import (
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


def online_user_ids() -> list[int]:
    """Hozir ulangan (tirik) sessiyalar egalari."""
    return [uid for uid, client in _clients.items() if client.is_connected()]


async def _resolve_owner_groups(owner_id: int, client: TelegramClient) -> None:
    """Tekshiruvdagi guruhlarni hal qiladi va egasiga natijani aytadi.

    Xabar yuborilmasa foydalanuvchi "guruh qo'shdim" deb kutib qoladi va
    "skaner ishlamayapti" deb o'ylaydi. Shuning uchun har bir natija
    (ulandi yoki xato + sabab) egasiga aytiladi.
    """
    rows = get_pending_user_groups(owner_id)
    if not rows:
        return
    try:
        dialogs = await client.get_dialogs(limit=None)
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

    async def _fail(gid: int, value: str, reason: str, prev: str) -> None:
        mark_user_group_error(gid, reason)
        logger.info("[GROUP] owner=%s xato: %s -> %s", owner_id, value, reason)
        # Xato guruhlar har 60 soniyada qayta tekshiriladi. Faqat birinchi
        # urinishda (pending -> xato) xabar beramiz, aks holda spam bo'ladi.
        if prev != "pending":
            return
        await send_to_bot_api(
            "⚠️ <b>Guruh ulanmadi</b>\n\n"
            f"👥 <code>{html.escape(value, quote=False)}</code>\n"
            f"Sabab: {html.escape(reason, quote=False)}\n\n"
            "🔄 Tuzatib, 📋 Guruhlarim → Qayta tekshirish ni bosing.",
            chat_id=owner_id,
        )

    for gid, _owner, input_value, _chat, prev_status in rows:
        value = (input_value or "").strip()
        entity = None
        if "t.me/+" in value or "t.me/joinchat/" in value:
            await _fail(
                gid, value,
                "yopiq taklif havolasini tekshirib bo'lmaydi — guruh ID "
                "sini (-100...) yuboring",
                prev_status,
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
                await _fail(
                    gid, value,
                    "akkauntingiz bu guruhda a'zo emas yoki ID noto'g'ri",
                    prev_status,
                )
                continue
        else:
            username = value.lstrip("@").lower()
            entity = by_username.get(username)
            if entity is None:
                await _fail(
                    gid, value,
                    "akkauntingiz bu guruhda a'zo emas yoki manzil noto'g'ri",
                    prev_status,
                )
                continue
        if isinstance(entity, Chat) or (
            isinstance(entity, Channel) and entity.megagroup
        ):
            title = getattr(entity, "title", "") or value
            resolve_user_group(gid, utils.get_peer_id(entity), title)
            logger.info("[GROUP] owner=%s ulandi: %s", owner_id, value)
            if prev_status != "ok":
                await send_to_bot_api(
                    "✅ <b>Guruh ulandi!</b>\n\n"
                    f"👥 {html.escape(title, quote=False)}\n"
                    f"🆔 <code>{utils.get_peer_id(entity)}</code>\n\n"
                    "Endi bu guruh skanerlanadi. To'xtatish: menyudagi "
                    "🔴 ⏸ Stop",
                    chat_id=owner_id,
                )
        else:
            await _fail(
                gid, value, "bu guruh emas (kanal yoki foydalanuvchi)", prev_status
            )


def _has_sticker(message) -> bool:
    """Telegram xabari stiker ekanini tekshiradi."""
    return bool(message is not None and getattr(message, "sticker", None))


def _make_handler(owner_id: int, client: TelegramClient):
    @client.on(events.NewMessage)
    async def _handler(event):
        is_sticker = _has_sticker(getattr(event, "message", None))
        if not event.raw_text and not is_sticker:
            return
        # Barcha filtrlar BITTA joyda — filters.evaluate(). Test ham
        # aynan shu funksiyani chaqiradi, shuning uchun test aytgan
        # natija bilan real skaner natijasi hech qachon farq qilmaydi.
        verdict = evaluate(
            owner_id,
            event.raw_text or "",
            is_sticker=is_sticker,
            chat_id=event.chat_id,
        )
        if not verdict.ok:
            # O'tkazib yuborish sababi logga yoziladi: [SCAN] skip ...
            logger.info(
                "[SCAN] skip owner=%s chat=%s: %s",
                owner_id, event.chat_id, summary_line(verdict),
            )
            return
        logger.info(
            "[SCAN] owner=%s chat=%s topildi=%s/%s",
            owner_id, event.chat_id, len(verdict.matched), verdict.required,
        )

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
            matched_words=verdict.matched,
            required_count=verdict.required,
            message_link=message_link,
        )
        rows = []
        if user_id is not None:
            rows.append([{"text": "💬 Mijozga yozish (Lichka)", "url": f"tg://user?id={user_id}"}])
        if message_link:
            rows.append([{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}])
        markup = {"inline_keyboard": rows} if rows else None

        # Bildirishnoma FAQAT guruh egasiga yuboriladi (chat_id=owner_id)
        increment_user_counter(owner_id, "leads_found")
        set_user_last_found(owner_id)
        increment_counter("leads_found")
        if await send_to_bot_api(text, markup, chat_id=owner_id):
            increment_counter("notifications_sent")
            logger.info("[SCAN] sent owner=%s chat=%s", owner_id, event.chat_id)
        else:
            logger.warning("[SCAN] SEND FAILED owner=%s chat=%s", owner_id, event.chat_id)

    return _handler


# Sessiya uzilganda foydalanuvchiga bir marta xabar berish uchun.
# Kalit — user_id, qiymat — oxirgi xabar yuborilgan vaqt (time.time()).
_NOTIFY_COOLDOWN = 6 * 3600  # 6 soat
_last_session_notice: dict[int, float] = {}


async def _notify_session_problem(owner_id: int, *, invalid: bool) -> None:
    """Sessiya bilan muammo bo'lsa egasiga aytadi (6 soatda bir marta).

    Foydalanuvchi sababini bilmasa "skaner ishlamayapti" deb o'ylaydi:
    xabar jimgina yo'qoladi. Shuning uchun aniq sabab va yechim yoziladi.
    """
    now = time.time()
    if now - _last_session_notice.get(owner_id, 0) < _NOTIFY_COOLDOWN:
        return
    _last_session_notice[owner_id] = now
    if invalid:
        text = (
            "⚠️ <b>Telegram sessiyangiz uzilgan.</b>\n\n"
            "Akkauntdan chiqilgan yoki sessiya bekor qilingan, shu sababli "
            "guruhlaringiz kuzatilmayapti va xabar kelmaydi.\n\n"
            "🔑 <b>Login</b> tugmasi orqali qayta kiring — sessiya "
            "tasdiqlangach skaner yana ishlaydi."
        )
    else:
        text = (
            "⚠️ <b>Akkauntga ulanishda xato.</b>\n\n"
            "Server Telegramga ulanmoqda, lekin sessiya hozircha "
            "ko'tarilmadi. Skaner vaqtincha ishlamasligi mumkin.\n"
            "Muammo davom etsa 🔑 <b>Login</b> dan qayta kiring."
        )
    try:
        await send_to_bot_api(text, chat_id=owner_id)
    except Exception:
        logger.warning("Sessiya ogohlantirishi yuborilmadi owner=%s", owner_id)
    logger.warning("[SESSION] ogohlantirish yuborildi owner=%s invalid=%s", owner_id, invalid)


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
        # SESSION_ENCRYPTION_KEY o'zgargan yoki yozuv buzilgan
        set_session_status(owner_id, "invalid")
        await _notify_session_problem(owner_id, invalid=True)
        return False
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            set_session_status(owner_id, "invalid")
            await client.disconnect()
            await _notify_session_problem(owner_id, invalid=True)
            return False
        me = await client.get_me()
        if not me or me.id != owner_id:
            set_session_status(owner_id, "invalid")
            await client.disconnect()
            await _notify_session_problem(owner_id, invalid=True)
            return False
    except Exception:
        logger.warning("Sessiya start xato owner=%s", owner_id, exc_info=True)
        try:
            await client.disconnect()
        except Exception:
            pass
        # Tarmoq/Telegram xatosi — sessiya yaroqsiz bo'lmagan bo'lishi mumkin,
        # shuning uchun "invalid" deb belgilanmaydi, faqat ogohlantiriladi.
        await _notify_session_problem(owner_id, invalid=False)
        return False
    _make_handler(owner_id, client)
    _clients[owner_id] = client
    set_session_status(owner_id, "active")
    _last_session_notice.pop(owner_id, None)
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
                # Admin ham o'z akkauntini ulab skanerlashi mumkin: u shu
                # bilan xatolarni o'z ko'zi bilan ko'radi va tekshiradi.
                # Tarif esa faqat oddiy foydalanuvchilarga tegishli (pastda).
                if not session_enc or awaiting or blocked:
                    continue
                if uid != ADMIN_ID and not is_subscription_active(uid):
                    continue
                should.add(uid)
            for uid in should - online:
                await start_user_client(uid)
            for uid in online - should:
                await stop_user_client(uid)
            # Ulangan client uzilib qolgan bo'lsa (tarmoq, Telegram) —
            # qayta ulanishga urinamiz, bo'lmasa egasini ogohlantiramiz.
            for uid, client in list(_clients.items()):
                try:
                    if client.is_connected():
                        continue
                    logger.warning("[SESSION] owner=%s uzilgan, qayta ulanmoqda", uid)
                    await client.connect()
                    if not client.is_connected():
                        raise ConnectionError("ulanmadi")
                except Exception:
                    logger.warning("[SESSION] owner=%s qayta tiklanmadi", uid)
                    _clients.pop(uid, None)
                    set_session_status(uid, "error")
                    await _notify_session_problem(uid, invalid=False)
                    continue
                # Har bir onlayn clientda egasining pending guruhlarini tekshirish
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
