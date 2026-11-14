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
from telethon.tl.types import Channel, Chat, PeerUser, User

from config import ADMIN_ID, API_HASH, API_ID
from database import (
    get_all_users_full,
    is_sender_blocked,
    save_lead_review,
    get_owner_active_chat_ids,
    get_pending_user_groups,
    get_user_full,
    get_user_groups,
    get_user_group_created_at,
    delete_user_group,
    increment_counter,
    increment_user_counter,
    is_subscription_active,
    mark_user_group_error,
    mark_user_group_left,
    mark_user_group_duplicate,
    mark_warned_today,
    resolve_user_group,
    set_session_status,
    set_user_last_found,
)
from login_manager import revoke_session
from filters import evaluate, summary_line
from session_crypto import decrypt_session
from notifier import (
    build_feedback_row,
    build_message_link,
    build_profile_link,
    build_notification_text,
    build_protected_notification_markup,
    build_protected_notification_text,
    find_phone_text,
    send_to_bot_api,
)
from scan_diagnostics import (
    configure_telethon_no_updates_timeout,
    instrument_telethon_client,
    scan_diagnostics as scan_delay_diagnostics,
)

logger = logging.getLogger(__name__)
_TELETHON_NO_UPDATES_TIMEOUT_SECONDS = configure_telethon_no_updates_timeout()
logger.info(
    "[DIAG] Telethon no-updates timeout=%ss",
    _TELETHON_NO_UPDATES_TIMEOUT_SECONDS,
)

# Hozir ko'tarilayotgan sessiyalar (ikki marta ulanishning oldini oladi)
_starting: set = set()

_clients: dict[int, TelegramClient] = {}
_tasks: list[asyncio.Task] = []
_GROUP_MEMBERSHIP_AUDIT_SECONDS = 10 * 60
_last_group_membership_audit: dict[int, float] = {}
_resolving_owner_groups: set[int] = set()

def is_client_online(user_id: int) -> bool:
    client = _clients.get(user_id)
    return bool(client and client.is_connected())


def online_user_ids() -> list[int]:
    """Hozir ulangan (tirik) sessiyalar egalari."""
    return [uid for uid, client in _clients.items() if client.is_connected()]


async def _resolve_owner_groups(owner_id: int, client: TelegramClient) -> None:
    """Bir egaga parallel ravishda bir nechta guruh resolve qilishni oldini oladi."""
    if owner_id in _resolving_owner_groups:
        return
    _resolving_owner_groups.add(owner_id)
    try:
        await _resolve_owner_groups_once(owner_id, client)
    finally:
        _resolving_owner_groups.discard(owner_id)


async def _resolve_owner_groups_once(owner_id: int, client: TelegramClient) -> None:
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
            resolved_chat_id = utils.get_peer_id(entity)
            same_group_rows = [
                group for group in get_user_groups(owner_id)
                if group[0] != gid and group[3] == resolved_chat_id
            ]
            if same_group_rows:
                canonical = min(
                    same_group_rows,
                    key=lambda group: (
                        {"ok": 0, "left": 1, "pending": 2, "error": 3}.get(
                            group[6], 4
                        ),
                        group[0],
                    ),
                )
                if canonical[6] == "left":
                    resolve_user_group(canonical[0], resolved_chat_id, title)
                    await send_to_bot_api(
                        "✅ <b>Guruhga qayta a'zo bo'lgansiz</b>\n\n"
                        f"👥 {html.escape(title, quote=False)}\n"
                        "Kuzatuv tiklandi.",
                        chat_id=owner_id,
                    )
                new_created = get_user_group_created_at(gid)
                old_keys = [
                    (get_user_group_created_at(group[0]), group[0])
                    for group in same_group_rows
                ]
                is_new_duplicate = (
                    new_created > 0 and (new_created, gid) > max(old_keys)
                )
                if is_new_duplicate:
                    # Faqat hozirgina qo'shilgan takror yozuvni olib tashlaymiz;
                    # avvaldan mavjud yozuvlarga tegmaymiz.
                    delete_user_group(gid, owner_id)
                    await send_to_bot_api(
                        "ℹ️ Bu guruh allaqachon ro'yxatda bor edi. "
                        "Takror qo'shilgani bekor qilindi.",
                        chat_id=owner_id,
                    )
                else:
                    mark_user_group_duplicate(gid, resolved_chat_id, title)
                    await send_to_bot_api(
                        "⚠️ Guruh uchun avvaldan boshqa yozuv bor. "
                        "Bu qator kuzatuvga qo'shilmadi; 📋 Guruhlarimda "
                        "takror qatorni qo'lda o'chirishingiz mumkin.",
                        chat_id=owner_id,
                    )
                continue

            if not resolve_user_group(gid, resolved_chat_id, title):
                await _fail(
                    gid, value, "guruh yozuvini yangilab bo'lmadi", prev_status
                )
                continue
            logger.info("[GROUP] owner=%s ulandi: %s", owner_id, value)
            if prev_status != "ok":
                await send_to_bot_api(
                    "✅ <b>Guruh ulandi!</b>\n\n"
                    f"👥 {html.escape(title, quote=False)}\n"
                    f"🆔 <code>{resolved_chat_id}</code>\n\n"
                    "Endi bu guruh skanerlanadi. To'xtatish: menyudagi "
                    "🔴 ⏸ Stop",
                    chat_id=owner_id,
                )
        else:
            await _fail(
                gid, value, "bu guruh emas (kanal yoki foydalanuvchi)", prev_status
            )


async def _audit_owner_group_membership(
    owner_id: int, client: TelegramClient,
) -> bool:
    """A'zolikni davriy tekshiradi; tark etilgan guruhni o'chirmaydi."""
    tracked = [
        group for group in get_user_groups(owner_id)
        if group[3] is not None and group[6] in {"ok", "left"}
    ]
    if not tracked:
        return True
    try:
        dialogs = await client.get_dialogs(limit=None)
    except Exception:
        logger.warning("[GROUP] a'zolik tekshiruvi xato owner=%s", owner_id, exc_info=True)
        return False

    dialog_by_id = {}
    for dialog in dialogs:
        try:
            dialog_by_id[utils.get_peer_id(dialog.entity)] = dialog.entity
        except Exception:
            continue

    checked_ids = set()
    for group in tracked:
        group_id, _owner, _input, chat_id, old_title, _active, status, _error = group
        if chat_id in checked_ids:
            continue
        checked_ids.add(chat_id)
        same_chat = [item for item in tracked if item[3] == chat_id]
        entity = dialog_by_id.get(chat_id)
        if status == "ok" and entity is None:
            changed = False
            for item in same_chat:
                if item[6] == "ok":
                    changed = mark_user_group_left(item[0]) or changed
            if changed:
                title = old_title or "Guruh"
                await send_to_bot_api(
                    "⚠️ <b>Guruhdan chiqib ketilgani aniqlandi</b>\n\n"
                    f"👥 {html.escape(title, quote=False)}\n"
                    "Bu guruhdan yangi xabarlar kuzatilmaydi. Guruh yozuvi "
                    "o'chirilmadi; akkaunt qayta a'zo bo'lsa, kuzatuv avtomatik tiklanadi.",
                    chat_id=owner_id,
                )
                logger.info("[GROUP] owner=%s a'zolik yo'qoldi chat=%s", owner_id, chat_id)
        elif status == "left" and entity is not None:
            title = getattr(entity, "title", "") or old_title or "Guruh"
            changed = False
            for item in same_chat:
                if item[6] == "left":
                    changed = resolve_user_group(item[0], chat_id, title) or changed
            if changed:
                await send_to_bot_api(
                    "✅ <b>Guruh kuzatuvi qayta tiklandi</b>\n\n"
                    f"👥 {html.escape(title, quote=False)}\n"
                    "Ulangan akkaunt yana guruh a'zosi.",
                    chat_id=owner_id,
                )
                logger.info("[GROUP] owner=%s a'zolik tiklandi chat=%s", owner_id, chat_id)
    return True


async def list_user_dialogs(owner_id: int, limit: int | None = None):
    """Akkaunt ko'radigan GURUHLAR ro'yxati: [(chat_id, title), ...].

    Guruh ID sini qo'lda yozishda xato bo'ladi. Bu funksiya sessiya
    haqiqatan ko'rayotgan guruhlarni aniq ID bilan qaytaradi — egasi
    ro'yxatdan tanlaydi. Sessiya onlayn bo'lmasa None.
    """
    client = _clients.get(owner_id)
    if client is None or not client.is_connected():
        return None
    try:
        dialogs = await client.get_dialogs(limit=limit)
    except Exception:
        logger.warning("Dialoglar xato owner=%s", owner_id, exc_info=True)
        return None
    out = []
    for d in dialogs:
        entity = d.entity
        if isinstance(entity, Chat) or (
            isinstance(entity, Channel) and entity.megagroup
        ):
            try:
                out.append(
                    (utils.get_peer_id(entity), getattr(entity, "title", "") or "")
                )
            except Exception:
                continue
    out.sort(key=lambda x: (x[1] or "").lower())
    return out


def _is_protected_content(chat=None, message=None) -> bool:
    """Telegram content-protection (noforwards) bayrog'ini aniqlaydi."""
    return bool(
        getattr(chat, "noforwards", False)
        or getattr(message, "noforwards", False)
    )


def _has_sticker(message) -> bool:
    """Telegram xabari stiker ekanini tekshiradi."""
    return bool(message is not None and getattr(message, "sticker", None))


# --- Diagnostika: sessiya xabarlarni umuman ko'ryaptimi? ---
# "Guruh qo'shdim, test KELADI deydi, lekin real xabar kelmaydi" degan
# holatda eng muhim savol: userbot guruhdagi xabarni UMUMAN ko'ryaptimi?
# Quyidagi hisoblagichlar shuni bot ekranida ko'rsatish uchun.
_seen_events: dict[int, int] = {}          # owner -> nechta guruh xabari
_seen_private: dict[int, int] = {}         # owner -> nechta lichka xabari
_last_event: dict[int, tuple] = {}         # owner -> (vaqt, chat_id, matn)
_start_error: dict[int, str] = {}          # owner -> oxirgi start xatosi
_last_sync_ts: int = 0                     # sync loop oxirgi ishlagan vaqt


def _note_event(owner_id: int, private: bool, chat_id, text: str) -> None:
    if private:
        _seen_private[owner_id] = _seen_private.get(owner_id, 0) + 1
    else:
        _seen_events[owner_id] = _seen_events.get(owner_id, 0) + 1
        # Diagnostics keeps the event time and chat, never message content.
        _last_event[owner_id] = (int(time.time()), chat_id, "")


def scan_diagnostics(owner_id: int) -> dict:
    """Skaner holati: client tirikmi, xabar ko'ryaptimi, qaysi chatlar."""
    client = _clients.get(owner_id)
    last = _last_event.get(owner_id)
    return {
        "client": client is not None,
        "start_error": _start_error.get(owner_id, ""),
        "last_sync": _last_sync_ts,
        "connected": bool(client is not None and client.is_connected()),
        "events": _seen_events.get(owner_id, 0),
        "private": _seen_private.get(owner_id, 0),
        "last_ts": last[0] if last else 0,
        "last_chat": last[1] if last else None,
        "last_text": last[2] if last else "",
        "watched": get_owner_active_chat_ids(owner_id),
    }


def reset_diagnostics(owner_id: int) -> None:
    _seen_events.pop(owner_id, None)
    _seen_private.pop(owner_id, None)
    _last_event.pop(owner_id, None)


# Takrorlanuvchi "skip" loglarini siyraklashtirish: kalit -> oxirgi yozilgan
# vaqt, hisob. Faqat bir xil sabab uchun.
_skip_state: dict[tuple, list] = {}
_SKIP_INTERVAL = 60      # sekund: bir xil sabab shu vaqtda bir marta yoziladi
_SKIP_STATE_MAX = 2000   # begona chatlar sababli dict cheksiz o'smasin


def _log_skip(owner_id: int, chat_id, verdict) -> None:
    """«skip» sababini logga yozadi, takrorlarni siyraklashtirib.

    Bir xil sabab bir daqiqada bir marta yoziladi va shu oraliqdagi
    takrorlar soni keyingi yozuvda ko'rsatiladi. Tizim sababida chat ID
    hisobga olinmaydi; qolgan sabablar chat bo'yicha alohida turadi.
    """
    line = summary_line(verdict)
    stage = getattr(verdict, "stage", "") or ""
    # «Tizim» sababi barcha chatlarga bir xil — bitta kalit yetadi.
    # Boshqa sabablar chat bo'yicha alohida ko'rsatiladi.
    key = (
        (owner_id, stage, line)
        if stage == "system"
        else (owner_id, stage, chat_id, line)
    )
    now = time.time()
    prev = _skip_state.get(key)
    if prev and now - prev[0] < _SKIP_INTERVAL:
        prev[1] += 1
        return
    extra = ""
    if prev and prev[1] > 0:
        extra = f" (+{prev[1]} ta shunga o'xshash xabar)"
    # Expired keyni oxiriga ko'chiramiz; LRU kabi eski yozuvlarni
    # chiqarish orqali yangi/noma'lum chatlar sonini cheklaymiz.
    _skip_state.pop(key, None)
    if len(_skip_state) >= _SKIP_STATE_MAX:
        _skip_state.pop(next(iter(_skip_state)))
    _skip_state[key] = [now, 0]
    logger.info(
        "[SCAN] skip owner=%s chat=%s: %s%s", owner_id, chat_id, line, extra
    )


def _make_handler(owner_id: int, client: TelegramClient):
    @client.on(events.NewMessage)
    async def _handler(event):
        handler_started = time.monotonic()
        chat_id = getattr(event, "chat_id", None)
        is_private = bool(getattr(event, "is_private", False))
        initial_text = event.raw_text or ""
        _note_event(owner_id, is_private, chat_id, "")
        if not is_private:
            # Har bir guruh xabari logga tushadi: "kelmayapti" deganda
            # xabar umuman kelmaganini yoki filtrda to'xtaganini ajratish
            # oson bo'ladi.
            logger.info(
                "[SCAN] event owner=%s chat=%s out=%s",
                owner_id, chat_id, bool(getattr(event, "out", False)),
            )
        # Shaxsiy yozishmalar skanerlanmaydi. get_peer_id ijobiy bo'lsa —
        # bu PeerUser (lichka). Ilgari bunday xabarlar ham logga tushib,
        # "guruh ro'yxatida yo'q" degan chalg'ituvchi yozuv berardi.
        if getattr(event, "is_private", False):
            return
        if chat_id is None or chat_id > 0:
            return
        raw_text = initial_text
        message = getattr(event, "message", None)
        trace = scan_delay_diagnostics.begin_trace(
            owner_id=owner_id,
            chat_id=chat_id,
            message_id=getattr(event, "id", 0) or 0,
            message_date=getattr(message, "date", None),
            received_monotonic=handler_started,
        )

        async def _send_notification(text, markup=None):
            send_started = time.monotonic()
            sent = await send_to_bot_api(text, markup, chat_id=owner_id)
            scan_delay_diagnostics.record_notification(
                trace,
                success=sent,
                duration_ms=(time.monotonic() - send_started) * 1000,
            )
            return sent

        is_sticker = _has_sticker(message)
        if not raw_text and not is_sticker:
            return

        chat = None
        protected = _is_protected_content(message=message)
        protection_unknown = False
        # Yozma xabarlar mavjud filtr zanjiridan o'tadi.
        filter_started = time.monotonic()
        verdict = evaluate(
            owner_id,
            raw_text,
            is_sticker=is_sticker,
            chat_id=chat_id,
        )
        scan_delay_diagnostics.record_evaluation(
            trace,
            matched=verdict.ok,
            filter_duration_ms=(time.monotonic() - filter_started) * 1000,
            handler_to_filter_ms=(filter_started - handler_started) * 1000,
        )
        if not verdict.ok:
            if protected or protection_unknown:
                logger.info(
                    "[SCAN] protected-skip owner=%s chat=%s stage=%s",
                    owner_id, chat_id, verdict.stage,
                )
            else:
                # Takror skip sabablari daqiqada bir marta yoziladi.
                _log_skip(owner_id, event.chat_id, verdict)
            return

        # Faqat Telethon tasdiqlagan shaxsiy PeerUser ID ishlatiladi;
        # anonim administrator/kanal ID si hech qachon shaxs deb bloklanmaydi.
        peer = getattr(message, "from_id", None)
        sender_user_id = peer.user_id if isinstance(peer, PeerUser) else None
        if sender_user_id and is_sender_blocked(owner_id, sender_user_id):
            logger.info("[SCAN] blocked-sender owner=%s", owner_id)
            return

        if chat is None:
            try:
                chat = await event.get_chat()
                if chat is None:
                    protection_unknown = True
                else:
                    protected = protected or _is_protected_content(chat, message)
            except Exception:
                protection_unknown = True
                logger.warning(
                    "[SCAN] chat himoyasini aniqlab bo'lmadi owner=%s chat=%s",
                    owner_id, chat_id, exc_info=True,
                )
        group_title = getattr(chat, "title", None) or "Noma'lum guruh"
        message_link = build_message_link(chat, event.chat_id, event.id)

        if protected or protection_unknown:
            logger.info("[SCAN] protected-match owner=%s chat=%s", owner_id, chat_id)
            # Faqat himoya holati aniq bo'lsa, cheklangan ko'rinadigan
            # ma'lumotni ko'rsatamiz. Xabar matnini yoki profilning yashirin
            # telefon raqamini bildirishnomaga ko'chirmaymiz.
            include_details = protected and not protection_unknown
            sender_name, username = None, None
            # Telethon ma'lumoti entity keshida bo'lmasa get_sender() None qaytarishi
            # mumkin. Eventning sender_id si profil havolasi uchun fallback bo'ladi.
            protected_sender_id = sender_user_id or getattr(event, "sender_id", None)
            if include_details:
                try:
                    sender = await event.get_sender()
                    if sender is not None:
                        sender_name = (
                            f"{getattr(sender, 'first_name', '') or ''} "
                            f"{getattr(sender, 'last_name', '') or ''}"
                        ).strip() or getattr(sender, "title", "") or None
                        username = getattr(sender, "username", None)
                        protected_sender_id = getattr(sender, "id", None) or protected_sender_id
                        if peer is None and sender_user_id is None and isinstance(sender, User):
                            sender_user_id = sender.id
                            if is_sender_blocked(owner_id, sender_user_id):
                                return
                except Exception:
                    logger.warning(
                        "[SCAN] protected-match yuboruvchi olinmadi "
                        "owner=%s chat=%s",
                        owner_id, chat_id, exc_info=True,
                    )
            phone = find_phone_text(raw_text) if include_details else None
            matched_words = getattr(verdict, "matched", []) if include_details else []
            text = build_protected_notification_text(
                group_title=group_title,
                message_link=message_link,
                protected=protected,
                include_details=include_details,
                sender_name=sender_name,
                username=username,
                user_id=protected_sender_id,
                phone=phone,
                matched_words=matched_words,
            )
            markup = build_protected_notification_markup(
                message_link,
                username=username if include_details else None,
                user_id=protected_sender_id if include_details else None,
            )
            if include_details and sender_user_id and sender_user_id != owner_id:
                if markup is None:
                    markup = {"inline_keyboard": []}
                markup["inline_keyboard"].append([{
                    "text": "🚫 Shu odamni bloklash",
                    "callback_data": f"bsp:{sender_user_id}",
                }])
            increment_user_counter(owner_id, "leads_found")
            set_user_last_found(owner_id)
            increment_counter("leads_found")
            if await _send_notification(text, markup):
                increment_counter("notifications_sent")
                logger.info("[SCAN] sent protected owner=%s chat=%s", owner_id, chat_id)
            else:
                logger.warning(
                    "[SCAN] SEND FAILED owner=%s chat=%s", owner_id, chat_id
                )
            return
        if verdict.mode == "weight":
            # Vazn rejimida "nechta kalit" shart emas — ball va chegara muhim.
            logger.info(
                "[SCAN] owner=%s chat=%s topildi ball=%g/%g: %s",
                owner_id, event.chat_id, verdict.score, verdict.threshold,
                ", ".join(f"{w:+g} {n}"
                          for n, w in {**verdict.positives,
                                       **verdict.negatives}.items()),
            )
        else:
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

        if peer is None and sender_user_id is None and isinstance(sender, User):
            sender_user_id = sender.id
            if is_sender_blocked(owner_id, sender_user_id):
                return

        phone = find_phone_text(raw_text, sender)
        text = build_notification_text(
            group_title=group_title,
            sender_name=sender_name,
            username=username,
            user_id=user_id,
            phone=phone,
            raw_text=raw_text,
            matched_words=verdict.matched,
            required_count=verdict.required,
            message_link=message_link,
            match_mode=verdict.mode,
            score=verdict.score,
            score_threshold=verdict.threshold,
            positive_weights=verdict.positives,
            negative_weights=verdict.negatives,
        )
        rows = []
        profile_link = build_profile_link(username)
        if user_id is not None and profile_link:
            rows.append([{
                "text": "💬 Mijozga yozish (Lichka)",
                "url": profile_link,
            }])
        if message_link:
            rows.append([{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}])
        if sender_user_id and sender_user_id != owner_id:
            rows.append([{"text": "🚫 Shu odamni bloklash",
                          "callback_data": f"bsp:{sender_user_id}"}])
        # Fikr-mulohaza statistikasi; vaznni faqat admin baholashi o'zgartiradi.
        review_id = save_lead_review(owner_id, verdict.matched)
        if review_id:
            rows.append(build_feedback_row(review_id))
            text += (
                "\n\nℹ️ ❌ Keraksiz bosilsa, ushbu bildirishnoma "
                "ko‘rib chiqish uchun adminga yuboriladi."
            )
        markup = {"inline_keyboard": rows} if rows else None

        # Bildirishnoma FAQAT guruh egasiga yuboriladi (chat_id=owner_id)
        increment_user_counter(owner_id, "leads_found")
        set_user_last_found(owner_id)
        increment_counter("leads_found")
        if await _send_notification(text, markup):
            increment_counter("notifications_sent")
            logger.info("[SCAN] sent owner=%s chat=%s", owner_id, event.chat_id)
        else:
            logger.warning("[SCAN] SEND FAILED owner=%s chat=%s", owner_id, event.chat_id)

    return _handler


# Sessiya uzilganda foydalanuvchiga bir marta xabar berish uchun.
# Kalit — user_id, qiymat — oxirgi xabar yuborilgan vaqt (time.time()).
_NOTIFY_COOLDOWN = 6 * 3600  # 6 soat
_last_session_notice: dict[int, float] = {}
_last_session_notice_attempt: dict[int, float] = {}
_SESSION_NOTICE_RETRY = 300  # muvaffaqiyatsiz urinishdan keyin 5 daqiqa


async def _notify_session_problem(owner_id: int, *, invalid: bool) -> None:
    """Sessiya bilan muammo bo'lsa egasiga aytadi (6 soatda bir marta).

    Foydalanuvchi sababini bilmasa "skaner ishlamayapti" deb o'ylaydi:
    xabar jimgina yo'qoladi. Shuning uchun aniq sabab va yechim yoziladi.
    """
    now = time.time()
    if owner_id in _last_session_notice and now - _last_session_notice[owner_id] < _NOTIFY_COOLDOWN:
        return
    if owner_id in _last_session_notice_attempt and now - _last_session_notice_attempt[owner_id] < _SESSION_NOTICE_RETRY:
        return
    _last_session_notice_attempt[owner_id] = now
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
        sent = await send_to_bot_api(text, chat_id=owner_id)
    except Exception:
        sent = False
        logger.exception("Sessiya ogohlantirishida xato owner=%s", owner_id)
    if sent:
        _last_session_notice[owner_id] = now
        logger.warning("[SESSION] ogohlantirish yuborildi owner=%s invalid=%s", owner_id, invalid)
    else:
        logger.warning("[SESSION] ogohlantirish yuborilmadi owner=%s", owner_id)


async def start_user_client(owner_id: int) -> bool:
    """Foydalanuvchi sessiyasini ko'taradi (bitta client, poygasiz).

    MUHIM: ``_clients`` ga yozish faqat ulanish tugagandan keyin bo'ladi.
    ``sync_now()`` va sync loop bir vaqtda chaqirsa, ikkalasi ham
    "client yo'q" deb ko'rib, **ikkita** Telethon klienti yaratardi —
    natijada har bir xabar ikki marta skanerlanib, egasiga xabar ikki
    marta ketardi. Shuning uchun boshlash jarayoni ``_starting`` bilan
    belgilanadi.
    """
    if owner_id in _clients:
        return True
    if owner_id in _starting:
        return True
    _starting.add(owner_id)
    try:
        return await _start_user_client(owner_id)
    finally:
        _starting.discard(owner_id)


async def _start_user_client(owner_id: int) -> bool:
    row = get_user_full(owner_id)
    if not row:
        _start_error[owner_id] = "foydalanuvchi bazada yo'q"
        return False
    # row: ... 8=session_enc, 10=awaiting
    session_enc, awaiting = row[8], row[10]
    if not session_enc:
        _start_error[owner_id] = "sessiya saqlanmagan (login qilinmagan)"
        return False
    if awaiting:
        _start_error[owner_id] = "login tasdiq kutmoqda"
        return False
    session_str = decrypt_session(session_enc)
    if not session_str:
        # SESSION_ENCRYPTION_KEY o'zgargan yoki yozuv buzilgan
        _start_error[owner_id] = (
            "sessiya shifrini ochib bo'lmadi (SESSION_ENCRYPTION_KEY "
            "o'zgargan bo'lishi mumkin) — qayta login kerak"
        )
        set_session_status(owner_id, "invalid")
        await _notify_session_problem(owner_id, invalid=True)
        return False
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    instrument_telethon_client(client, owner_id)
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
    except Exception as exc:
        _start_error[owner_id] = f"Telegramga ulanmadi: {type(exc).__name__}"
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
    _start_error.pop(owner_id, None)
    set_session_status(owner_id, "active")
    _last_session_notice.pop(owner_id, None)
    logger.info("[SESSION] owner=%s client ishga tushdi", owner_id)
    asyncio.create_task(_resolve_owner_groups(owner_id, client))
    return True


async def sync_now() -> None:
    """Sync loopsiz darhol barcha sessiyalarni ko'tarishga urinish."""
    for row in get_all_users_full():
        uid, blocked, session_enc, awaiting = row[0], row[3], row[8], row[10]
        if not session_enc or awaiting or blocked:
            continue
        if uid != ADMIN_ID and not is_subscription_active(uid):
            continue
        if uid not in _clients:
            await start_user_client(uid)


async def restart_user_client(owner_id: int) -> bool:
    """Clientni to'xtatib qayta ko'taradi (qo'lda tuzatish tugmasi)."""
    await stop_user_client(owner_id)
    _clients.pop(owner_id, None)
    return await start_user_client(owner_id)


async def stop_user_client(owner_id: int, revoke: bool = False) -> None:
    client = _clients.pop(owner_id, None)
    _last_group_membership_audit.pop(owner_id, None)
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


async def _event_loop_lag_loop():
    """Har soniyada event loopni tekshiradi; faqat 250 ms dan oshganini yozadi."""
    loop = asyncio.get_running_loop()
    interval = 1.0
    deadline = loop.time() + interval
    while True:
        await asyncio.sleep(max(0.0, deadline - loop.time()))
        now = loop.time()
        lag_ms = max(0.0, (now - deadline) * 1000)
        if lag_ms >= 250:
            for owner_id, client in tuple(_clients.items()):
                try:
                    if client.is_connected():
                        scan_delay_diagnostics.record_loop_lag(owner_id, lag_ms)
                except Exception:
                    continue
        deadline += interval
        if deadline <= now:
            deadline = now + interval


async def _sync_loop():
    global _last_sync_ts
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
                if not client.is_connected():
                    try:
                        logger.warning("[SESSION] owner=%s uzilgan, qayta ulanmoqda", uid)
                        await client.connect()
                        if not client.is_connected():
                            raise ConnectionError("ulanmadi")
                    except Exception:
                        logger.warning("[SESSION] owner=%s qayta tiklanmadi", uid)
                        _clients.pop(uid, None)
                        _last_group_membership_audit.pop(uid, None)
                        set_session_status(uid, "error")
                        await _notify_session_problem(uid, invalid=False)
                        continue
                # Pending guruhlarni har syncda, a'zolikni esa 10 daqiqada bir tekshiramiz.
                await _resolve_owner_groups(uid, client)
                now_mono = time.monotonic()
                if uid not in _last_group_membership_audit:
                    # 50-100 akkauntning get_dialogs so'rovlari bir paytga
                    # to'planmasligi uchun birinchi auditni yoyib yuboramiz.
                    offset = abs(uid) % _GROUP_MEMBERSHIP_AUDIT_SECONDS
                    _last_group_membership_audit[uid] = now_mono - offset
                if (
                    now_mono - _last_group_membership_audit[uid]
                    >= _GROUP_MEMBERSHIP_AUDIT_SECONDS
                ):
                    _last_group_membership_audit[uid] = now_mono
                    await _audit_owner_group_membership(uid, client)
            _last_sync_ts = int(time.time())
            from database import set_setting as _ss
            _ss("userbot_last_seen", _last_sync_ts)
        except Exception:
            logger.exception("Sync loop xato")
        await asyncio.sleep(60)


async def _send_expiry_warnings(bot_send=send_to_bot_api):
    """Bugungi ogohlantirishni faqat muvaffaqiyatli yuborilganda qayd etadi."""
    from database import get_expiring_users

    today = datetime.date.today().isoformat()
    for row in get_expiring_users(3):
        uid, expires, last_warn = row[0], row[4], row[12]
        if last_warn == today:
            continue
        days_left = max(1, (expires - int(time.time()) + 86399) // 86400)
        date_text = time.strftime("%d.%m.%Y", time.localtime(expires))
        try:
            sent = await bot_send(
                "⏰ <b>Tarif muddatingiz tugayapti!</b>\n\n"
                f"📅 Tugash sanasi: <b>{date_text}</b>\n"
                f"⏳ Qolgan muddat: <b>{days_left} kun</b>\n\n"
                "Davom ettirish uchun admin bilan bog'laning.",
                chat_id=uid,
            )
            if sent:
                mark_warned_today(uid)
            else:
                logger.warning("Tarif ogohlantirishi yuborilmadi owner=%s", uid)
        except Exception:
            logger.exception("Tarif ogohlantirishida xato owner=%s", uid)


async def _expiry_warning_loop(bot_send=send_to_bot_api):
    """Tugashga <=3 kun: yuborilsa har kuni bir marta, aks holda qayta urinadi."""
    while True:
        try:
            await _send_expiry_warnings(bot_send)
        except Exception:
            logger.exception("Expiry warning xato")
        await asyncio.sleep(3600)


_background_started = False


def start_background() -> None:
    """Sync loop va ogohlantirish loopini ishga tushiradi (bir marta).

    MUHIM: bu funksiya bot.py dan ham chaqiriladi. Ilgari u faqat
    main.py orqali ishga tushardi — servis to'g'ridan-to'g'ri bot.py
    bilan ko'tarilsa, sync loop umuman ishlamay, hech bir sessiya
    yuklanmasdi va xabar kelmasdi.
    """
    global _background_started
    if _background_started:
        return
    _background_started = True
    logger.info("Sessiya manageri ishga tushdi...")
    _tasks.append(asyncio.create_task(_sync_loop()))
    _tasks.append(asyncio.create_task(_expiry_warning_loop()))
    _tasks.append(asyncio.create_task(_event_loop_lag_loop()))


async def run():
    """Barcha sessiyalar managerini ishga tushiradi (main.py dan)."""
    start_background()
    if _tasks:
        await asyncio.gather(*_tasks)
