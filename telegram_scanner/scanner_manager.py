"""Ko'p foydalanuvchili skaner: har bir foydalanuvchi — alohida sessiya.

Har bir tasdiqlangan foydalanuvchining shifrlangan sessiyasidan alohida
Telethon client ko'tariladi. Client FAQAT egasining guruhlarini kuzatadi,
xabar topilsa FAQAT egasiga boradi. Kalitlar va shart — adminniki (global).
"""
import asyncio
import datetime
import html
import json
import logging
import os
import time
from collections import OrderedDict, deque

from telethon import TelegramClient, events, utils, __version__ as TELETHON_VERSION
from telethon.errors import FloodWaitError
from telethon.extensions import html as telethon_html
from telethon.sessions import StringSession
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatForbiddenError,
)
from telethon.tl.types import (
    Channel,
    ChannelForbidden,
    Chat,
    ChatForbidden,
    InputMessageEntityMentionName,
    MessageEntityTextUrl,
    MessageService,
    PeerChannel,
    PeerUser,
    UpdateChannel,
    UpdateNewChannelMessage,
    User,
)

from config import ADMIN_ID, API_HASH, API_ID, BASE_DIR
from database import (
    get_active_chat_watchers,
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
    build_protected_sender_link,
    build_notification_text,
    build_protected_notification_markup,
    build_protected_notification_text,
    find_phone_text,
    send_to_bot_api,
)
from scan_diagnostics import (
    configure_telethon_no_updates_timeout,
    instrument_telethon_client,
    group_timing,
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
_session_health_states: dict[int, tuple[object, tuple[str, str]]] = {}
_SESSION_HEALTH_INTERVAL = 15


def _session_health(client) -> tuple[str, str]:
    """Passiv namuna; tarmoq so'rovi, reconnect yoki exception matni yo'q.

    _updates_handle — private API: faqat pin qilingan 1.34.0 da tekshiriladi.
    Task ishlashi Telegram xabar yetkazayotganini isbotlamaydi.
    """
    try:
        connection = "connected" if client.is_connected() else "disconnected"
    except Exception:
        connection = "unknown"
    update_loop = "unknown"
    if TELETHON_VERSION == "1.34.0":
        try:
            task = getattr(client, "_updates_handle", None)
            if isinstance(task, asyncio.Future):
                update_loop = "stopped" if task.done() else "running"
        except Exception:
            pass
    return connection, update_loop


def _sample_session_health() -> None:
    """O'zgargan holatlarni alohida maxfiy faylga yozadi; xabar bo'lmasa restart qilmaydi."""
    clients = dict(_clients)
    for owner_id in set(_session_health_states) - set(clients):
        _session_health_states.pop(owner_id, None)
    for owner_id, client in clients.items():
        try:
            connection, update_loop = _session_health(client)
            current = (connection, update_loop)
            previous = _session_health_states.get(owner_id)
            if previous is None or previous[0] is not client or previous[1] != current:
                scan_delay_diagnostics.record_session_health(
                    owner_id, connection=connection, update_loop=update_loop,
                )
                _session_health_states[owner_id] = (client, current)
        except Exception:
            logger.warning("Sessiya holati diagnostikasi yozilmadi")


def _record_session_event(owner_id: int, event: str) -> None:
    try:
        scan_delay_diagnostics.record_session_event(owner_id, event=event)
    except Exception:
        logger.warning("Sessiya hodisasi diagnostikasi yozilmadi")


async def _session_health_loop():
    while True:
        _sample_session_health()
        await asyncio.sleep(_SESSION_HEALTH_INTERVAL)


def is_client_online(user_id: int) -> bool:
    client = _clients.get(user_id)
    return bool(client and client.is_connected())


def online_user_ids() -> list[int]:
    """Hozir ulangan (tirik) sessiyalar egalari."""
    return [uid for uid, client in _clients.items() if client.is_connected()]


def _is_active_member(entity) -> bool:
    """Akkaunt shu guruhning haqiqiy a'zosimi (dialogdagi entity bo'yicha).

    Telethon ban qilingan (ChannelForbidden), chiqib ketilgan (left) yoki
    superguruhga ko'chgan/o'chirilgan (deactivated) guruhlarni ham dialog
    sifatida qaytaradi — ular a'zolik hisoblanmaydi.
    """
    if entity is None or isinstance(entity, (ChannelForbidden, ChatForbidden)):
        return False
    if getattr(entity, "left", False) or getattr(entity, "deactivated", False):
        return False
    if getattr(entity, "migrated_to", None) is not None:
        return False
    rights = getattr(entity, "banned_rights", None)
    return not (rights is not None and getattr(rights, "view_messages", False))


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
        if not _is_active_member(entity):
            await _fail(
                gid, value,
                "akkauntingiz bu guruhdan chiqqan yoki chiqarilgan (ban)",
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
        member = _is_active_member(entity)
        if status == "ok" and not member:
            changed = False
            for item in same_chat:
                if item[6] == "ok":
                    changed = mark_user_group_left(item[0]) or changed
            if changed:
                title = old_title or "Guruh"
                await send_to_bot_api(
                    "⚠️ <b>Guruhdan chiqib ketilgani yoki chiqarilgani aniqlandi</b>\n\n"
                    f"👥 {html.escape(title, quote=False)}\n"
                    "Bu guruhdan yangi xabarlar kuzatilmaydi. Guruh yozuvi "
                    "o'chirilmadi; akkaunt qayta a'zo bo'lsa, kuzatuv avtomatik tiklanadi.",
                    chat_id=owner_id,
                )
                logger.info("[GROUP] owner=%s a'zolik yo'qoldi chat=%s", owner_id, chat_id)
        elif status == "left" and member:
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
        if not _is_active_member(entity):
            continue
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


async def list_group_public_usernames(owner_id: int):
    """Faqat ulangan akkaunt dialoglaridagi ochiq username'lar, ID bo'yicha.

    Hech qanday xabar, taklif havolasi yoki sessiya ma'lumoti qaytarilmaydi.
    None — dialoglar olinmadi; bo'sh dict — olindi, username yo'q.
    """
    client = _clients.get(owner_id)
    if client is None or not client.is_connected():
        return None
    try:
        dialogs = await client.get_dialogs(limit=None)
    except Exception:
        logger.warning("[GROUP] Ochiq manzillarni olish muvaffaqiyatsiz")
        return None
    result = {}
    for dialog in dialogs:
        entity = dialog.entity
        if isinstance(entity, Chat) or (isinstance(entity, Channel) and entity.megagroup):
            username = getattr(entity, 'username', None)
            if username:
                result[str(utils.get_peer_id(entity))] = username
    return result


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
        "update_loop": _session_health(client)[1] if client is not None else "unknown",
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


class _RecentKeys:
    """Oxirgi N ta kalitni eslab qoladigan cheklangan to'plam (LRU)."""

    def __init__(self, limit: int):
        self._keys: OrderedDict = OrderedDict()
        self._limit = limit

    def __contains__(self, key) -> bool:
        return key in self._keys

    def add(self, key) -> bool:
        """Yangi bo'lsa qo'shadi va True; avval bor bo'lsa False."""
        if key in self._keys:
            return False
        self._keys[key] = None
        if len(self._keys) > self._limit:
            self._keys.popitem(last=False)
        return True


class _RecentValues:
    """Oxirgi N ta kalit -> qiymat (LRU)."""

    def __init__(self, limit: int):
        self._items: OrderedDict = OrderedDict()
        self._limit = limit

    def get(self, key):
        return self._items.get(key)

    def put(self, key, value) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        if len(self._items) > self._limit:
            self._items.popitem(last=False)


# (owner, chat, message_id): push yoki zaxira tekshiruv orqali allaqachon
# ko'rilgan xabarlar. Zaxira tekshiruv shu xabarlarni qayta ishlamaydi.
_seen_messages = _RecentKeys(200_000)
# Har bir egasining ishlovchisi — zaxira tekshiruv topgan xabarni shu
# egasining filtri va bildirishnomasidan o'tkazish uchun.
_handlers: dict[int, object] = {}


class _PolledEvent:
    """``get_messages()`` natijasini NewMessage eventi kabi ko'rsatadi.

    ``polled_by`` — xabarni olgan akkaunt (u egasidan farq qilishi mumkin).
    """

    def __init__(self, message, polled_by: int | None = None):
        self.message = message
        self.polled_by = polled_by

    def __getattr__(self, name):
        return getattr(self.message, name)


def _public_sender_view(sender):
    """Boshqa akkaunt orqali olingan yuboruvchidan faqat ommaviy ma'lumot.

    Telegram kontakt uchun akkaunt egasi saqlagan ismni va unga ko'rinadigan
    telefonni qaytaradi — ular boshqa egaga o'tmasligi kerak. Username va
    ID ommaviy, ular qoladi.
    """
    if not isinstance(sender, User):
        return sender
    private_names = bool(
        getattr(sender, "contact", False) or getattr(sender, "mutual_contact", False)
    )
    return User(
        id=sender.id,
        username=getattr(sender, "username", None),
        first_name=None if private_names else getattr(sender, "first_name", None),
        last_name=None if private_names else getattr(sender, "last_name", None),
        bot=getattr(sender, "bot", None),
    )


# --- Topilgan mijozni egasining "Saved Messages"iga saqlash ---
# Guruh boti xabarni o'chirsa, bot bildirishnomasidagi "asl xabar"
# havolasi ishlamay qoladi, username'siz mijozning profil havolasini esa
# Bot API ko'pincha rad etadi. Egasining o'z akkaunti mijozni guruh
# xabaridan taniydi: Saved Messages'ga bosiladigan nom (mention) va asl
# xabarning forward nusxasi yuboriladi — xabar o'chsa ham mijoz topiladi.
_SAVED_COPY_ENABLED = os.getenv("SCANNER_SAVED_MESSAGES", "1").strip() != "0"
_SAVED_TEXT_LIMIT = 3000


async def _owner_input_user(client, sender, sender_id, foreign_view):
    """Egasining akkaunti uchun yaroqli InputUser (access_hash akkauntga xos)."""
    if not sender_id:
        return None
    if not foreign_view and isinstance(sender, User) and sender.id == sender_id:
        if sender.access_hash and not getattr(sender, "min", False):
            return utils.get_input_user(sender)
    try:
        return utils.get_input_user(await client.get_input_entity(PeerUser(sender_id)))
    except Exception:
        return None


def _saved_card(*, group_title, sender_name, username, sender_id, phone,
                raw_text, message_link, protected, input_user):
    """Saved Messages kartochkasi: (matn, entity'lar)."""
    esc = html.escape
    lines = [
        "🚕 <b>MIJOZ TOPILDI</b>" + (" 🔒" if protected else ""),
        f"📍 {esc(group_title or 'Nomaʼlum guruh')}",
    ]
    name = esc(sender_name or "Mijoz")
    if sender_id:
        lines.append(f'👤 <a href="tg://user?id={int(sender_id)}">{name}</a>'
                     + (f" ({esc(username)})" if username else ""))
        lines.append(f"🆔 <code>{int(sender_id)}</code>")
    else:
        lines.append(f"👤 {name}" + (f" ({esc(username)})" if username else ""))
    if phone:
        lines.append(f"📞 {esc(phone)}")
    if raw_text and not protected:
        text = raw_text if len(raw_text) <= _SAVED_TEXT_LIMIT else raw_text[:_SAVED_TEXT_LIMIT] + "…"
        lines += ["", f"💬 {esc(text)}"]
    if message_link:
        lines += ["", f'🔗 <a href="{esc(message_link, quote=True)}">Guruhdagi xabar</a>']
    if sender_id and input_user is None:
        lines.append("ℹ️ Profilni ochib bo'lmadi — ID orqali qidiring.")
    text, entities = telethon_html.parse("\n".join(lines))
    out = []
    for entity in entities:
        if isinstance(entity, MessageEntityTextUrl) and entity.url.startswith("tg://user?id="):
            if input_user is not None:
                out.append(InputMessageEntityMentionName(entity.offset, entity.length, input_user))
            continue
        out.append(entity)
    return text, out


async def _save_lead_copy(client, *, chat_id, message_id, protected, sender,
                          sender_id, foreign_view, **card) -> None:
    try:
        if not protected and message_id:
            # Avval forward: guruh boti xabarni bir necha soniyada o'chirishi mumkin.
            try:
                await client.forward_messages("me", message_id, from_peer=chat_id)
            except Exception as exc:
                logger.info("[SAVED] forward bo'lmadi: %s", type(exc).__name__)
        input_user = await _owner_input_user(client, sender, sender_id, foreign_view)
        text, entities = _saved_card(
            sender_id=sender_id, protected=protected, input_user=input_user, **card,
        )
        await client.send_message("me", text, formatting_entities=entities, link_preview=False)
        logger.info("[SAVED] kartochka saqlandi chat=%s mention=%s", chat_id, input_user is not None)
    except Exception as exc:
        logger.warning("[SAVED] kartochka saqlanmadi: %s", type(exc).__name__)


def _spawn_saved_copy(client, **details) -> None:
    """Bildirishnomani kechiktirmaslik uchun alohida task."""
    if not _SAVED_COPY_ENABLED or not hasattr(client, "send_message"):
        return
    task = asyncio.create_task(_save_lead_copy(client, **details))
    _side_tasks.add(task)
    task.add_done_callback(_side_tasks.discard)


# A'zolik o'zgarganda (masalan, akkaunt guruhdan chiqarilsa) Telegram
# UpdateChannel yuboradi — shunda 10 daqiqani kutmay darhol tekshiramiz.
_MEMBERSHIP_RECHECK_DEBOUNCE = 30
_membership_recheck_at: dict[int, float] = {}
_side_tasks: set = set()


def _request_membership_audit(owner_id: int) -> None:
    now = time.monotonic()
    last = _membership_recheck_at.get(owner_id)
    if last is not None and now - last < _MEMBERSHIP_RECHECK_DEBOUNCE:
        return
    client = _clients.get(owner_id)
    if client is None:
        return
    _membership_recheck_at[owner_id] = now

    async def _run():
        await asyncio.sleep(2)  # Telegram dialoglarni yangilab ulgursin
        if _clients.get(owner_id) is client:
            try:
                await _audit_owner_group_membership(owner_id, client)
            except Exception:
                logger.warning("[GROUP] tezkor a'zolik tekshiruvi xato owner=%s", owner_id)

    task = asyncio.create_task(_run())
    _side_tasks.add(task)
    task.add_done_callback(_side_tasks.discard)


def _make_handler(owner_id: int, client: TelegramClient, ready: asyncio.Event | None = None):
    # Bir xabar push, zaxira tekshiruv va tahrir orqali bir necha marta
    # kelishi mumkin; egasiga bildirishnoma esa faqat bir marta boradi.
    notified = _RecentKeys(50_000)
    # (chat, message_id) -> tekshirilgan matn xeshi: tahrirda matn
    # o'zgarmagan bo'lsa, xabar qayta tekshirilmaydi.
    seen_texts = _RecentValues(50_000)

    def _claim_notification(chat_id, message_id) -> bool:
        return notified.add((chat_id, message_id))

    @client.on(events.Raw(UpdateChannel))
    async def _membership_changed(update):
        if ready is not None and not ready.is_set():
            return
        try:
            chat_id = utils.get_peer_id(PeerChannel(update.channel_id))
        except Exception:
            return
        if owner_id in _poll_watchers.get(chat_id, ()):
            _request_membership_audit(owner_id)

    # O'lchov: xabar bizga qachon yetdi (servis xabarlar ham — guruh
    # botlari "qo'shildi" xabarlarini ham o'chiradi) va qachon o'chirildi.
    @client.on(events.Raw(UpdateNewChannelMessage))
    async def _measure_arrival(update):
        if ready is not None and not ready.is_set():
            return
        message = getattr(update, "message", None)
        try:
            chat_id = utils.get_peer_id(message.peer_id)
        except Exception:
            return
        _note_arrival(
            chat_id, getattr(message, "id", 0), message, "push",
            service=isinstance(message, MessageService),
        )

    @client.on(events.MessageDeleted)
    async def _measure_deleted(event):
        if ready is not None and not ready.is_set():
            return
        _note_deleted(getattr(event, "chat_id", None), getattr(event, "deleted_ids", None) or ())

    @client.on(events.MessageEdited)
    @client.on(events.NewMessage)
    async def _handler(event):
        handler_started = time.monotonic()
        received_at = datetime.datetime.now(datetime.timezone.utc)
        # Handler ulanmasdan oldin ro'yxatga olinadi, ammo akkaunt egasi
        # tasdiqlanmaguncha xabarni ishlash yoki yuborish mumkin emas.
        if ready is not None:
            await ready.wait()
        chat_id = getattr(event, "chat_id", None)
        is_private = bool(getattr(event, "is_private", False))
        initial_text = event.raw_text or ""
        text_key = (chat_id, getattr(event, "id", 0) or 0)
        if isinstance(event, events.MessageEdited.Event):
            # Ko'rinmas tahrir (reaksiya, ko'rishlar, havola ko'rinishi)
            # yoki matni o'zgarmagan tahrir qayta tekshirilmaydi.
            if getattr(getattr(event, "message", None), "edit_hide", False):
                return
            if seen_texts.get(text_key) == hash(initial_text):
                return
        seen_texts.put(text_key, hash(initial_text))
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
        if chat_id in _poll_watchers:
            # Zaxira tekshiruv bu xabarni qayta ishlamasligi uchun.
            _seen_messages.add((owner_id, chat_id, getattr(event, "id", 0) or 0))
        # Zaxira xabarni boshqa akkaunt olgan bo'lsa, uning shaxsiy
        # ko'rinishi (kontakt ismi, telefon) egaga o'tmaydi.
        foreign_view = getattr(event, "polled_by", owner_id) not in (None, owner_id)
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
            send_ms = (time.monotonic() - send_started) * 1000
            scan_delay_diagnostics.record_notification(
                trace, success=sent, duration_ms=send_ms,
            )
            group_timing.notification(
                owner_id, chat_id, getattr(event, "id", 0) or 0,
                getattr(message, "date", None), received_at,
                (send_started - handler_started) * 1000, send_ms, sent,
            )
            scan_delay_diagnostics.record_match_notification(
                owner_id, message_date=getattr(message, "date", None),
                received_at=received_at,
                before_send_ms=(send_started - handler_started) * 1000,
                send_ms=send_ms, success=sent,
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
        filter_ms = (time.monotonic() - filter_started) * 1000
        before_filter_ms = (filter_started - handler_started) * 1000
        scan_delay_diagnostics.record_evaluation(
            trace, matched=verdict.ok, filter_duration_ms=filter_ms,
            handler_to_filter_ms=before_filter_ms,
        )
        group_timing.evaluation(
            owner_id, chat_id, getattr(event, "id", 0) or 0,
            getattr(message, "date", None), received_at, filter_ms,
            before_filter_ms, verdict.ok, getattr(verdict, "stage", ""),
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
                # Update bilan kelgan entity — tarmoq so'rovisiz, darhol.
                chat = getattr(event, "chat", None) or await event.get_chat()
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
            sender_name, username, sender = None, None, None
            # Telethon ma'lumoti entity keshida bo'lmasa get_sender() None qaytarishi
            # mumkin. Eventning sender_id si profil havolasi uchun fallback bo'ladi.
            protected_sender_id = sender_user_id or getattr(event, "sender_id", None)
            if include_details:
                try:
                    sender = getattr(event, "sender", None) or await event.get_sender()
                    if foreign_view:
                        sender = _public_sender_view(sender)
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
            if not _claim_notification(chat_id, getattr(event, "id", 0) or 0):
                return
            if include_details:
                # Himoyalangan guruh: forward va matn yo'q, faqat mijoz kartochkasi.
                _spawn_saved_copy(
                    client, chat_id=chat_id, message_id=getattr(event, "id", 0) or 0,
                    protected=True, sender=sender, sender_id=sender_user_id,
                    foreign_view=foreign_view, group_title=group_title,
                    sender_name=sender_name,
                    username=f"@{username}" if username else None,
                    phone=phone if phone and phone != "Matnda ko'rsatilmagan" else None,
                    raw_text=None, message_link=message_link,
                )
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

        # Update bilan kelgan yuboruvchi — tarmoq so'rovisiz va xabar
        # o'chirilgan bo'lsa ham saqlanib qoladi. Yo'q bo'lsagina so'raymiz.
        sender = getattr(event, "sender", None) or await event.get_sender()
        if foreign_view:
            sender = _public_sender_view(sender)
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
            profile_user_id=sender_user_id,
        )
        rows = []
        profile_link = build_protected_sender_link(username, sender_user_id)
        if profile_link:
            rows.append([{
                "text": "💬 Mijozga yozish (Lichka)",
                "url": profile_link,
            }])
        if message_link:
            rows.append([{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}])
        if sender_user_id and sender_user_id != owner_id:
            rows.append([{"text": "🚫 Shu odamni bloklash",
                          "callback_data": f"bsp:{sender_user_id}"}])
        if not _claim_notification(chat_id, getattr(event, "id", 0) or 0):
            return
        _spawn_saved_copy(
            client, chat_id=chat_id, message_id=getattr(event, "id", 0) or 0,
            protected=False, sender=sender, sender_id=sender_user_id,
            foreign_view=foreign_view, group_title=group_title,
            sender_name=sender_name if sender_name != "Noma'lum" else None,
            username=username if username != "Yo'q" else None,
            phone=phone if phone != "Matnda ko'rsatilmagan" else None,
            raw_text=raw_text, message_link=message_link,
        )
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
    ready = asyncio.Event()
    handler = _make_handler(owner_id, client, ready=ready)
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
    _clients[owner_id] = client
    _handlers[owner_id] = handler
    _start_error.pop(owner_id, None)
    set_session_status(owner_id, "active")
    ready.set()
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
    _handlers.pop(owner_id, None)
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
                        _record_session_event(uid, "reconnect_attempt")
                        await client.connect()
                        if not client.is_connected():
                            raise ConnectionError("ulanmadi")
                        _record_session_event(uid, "reconnect_succeeded")
                    except Exception:
                        _record_session_event(uid, "reconnect_failed")
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


# --- Zaxira tekshiruv (polling) ---
# Telegram ba'zan superguruh xabarini push qilmaydi yoki kechiktiradi;
# Telethon bo'shliqni ancha keyin to'ldiradi va bu orada guruh boti
# xabarni o'chirib ulgurgan bo'ladi. Shuning uchun har bir kuzatuvdagi
# superguruhning yangi xabarlari qisqa oraliqda so'rab turiladi.
#
# Bir guruhni o'nlab foydalanuvchi kuzatsa ham, uni faqat BITTA akkaunt
# so'raydi (yuklama a'zo akkauntlar orasida teng bo'linadi), topilgan xabar
# esa shu guruhni kuzatayotgan har bir egasining filtridan o'tadi. Ega
# guruhning o'zi a'zosi (status=ok), shuning uchun begona ma'lumot o'tmaydi.


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return min(high, max(low, value))


_POLL_ENABLED = os.getenv("SCANNER_POLL_ENABLED", "1").strip() != "0"
# Bitta guruh shu oraliqdan tez-tez so'ralmaydi.
_POLL_INTERVAL = _env_float("SCANNER_POLL_INTERVAL_SECONDS", 10.0, 3.0, 300.0)
# Bitta akkaunt so'rovlari orasidagi minimal pauza (FloodWait'dan himoya).
_POLL_GAP = _env_float("SCANNER_POLL_ACCOUNT_GAP_SECONDS", 1.0, 0.5, 10.0)
_POLL_BATCH = 100
_POLL_PEEK = 10            # odatiy so'rov: oxirgi 10 ta xabar
_POLL_DISPATCH_GRACE = 5   # sekund: push'ga ulgurish uchun
# Shundan eski xabarlar zaxira orqali yuborilmaydi (restartdan keyin ham).
_POLL_MAX_AGE = 15 * 60
_POLL_PLAN_SECONDS = 10
_POLL_REWARM_SECONDS = 10 * 60
_POLL_STATE_PATH = BASE_DIR / "poll_state.json"

_poll_last: dict[int, int] = {}            # chat -> oxirgi ko'rilgan message_id
_poll_plan: dict[int, list[int]] = {}      # akkaunt -> u so'raydigan guruhlar
_poll_assignee: dict[int, int] = {}        # guruh -> so'rovchi akkaunt
_poll_watchers: dict[int, set[int]] = {}   # guruh -> kuzatuvchi egalar
_poll_workers: dict[int, asyncio.Task] = {}
_poll_paused_until: dict[int, float] = {}  # akkaunt -> FloodWait tugashi
# (akkaunt, guruh) -> shu vaqtgacha bu akkaunt guruhni so'ramaydi
_poll_chat_backoff: dict[tuple[int, int], float] = {}
# (ega, guruh) -> guruhga kirish yo'q (ban/chiqarilgan): zaxira xabar
# bu egaga yuborilmaydi, a'zolik tekshiruvi holatni yangilaguncha.
_poll_no_access: dict[tuple[int, int], float] = {}
_POLL_NO_ACCESS_SECONDS = 10 * 60
_POLL_ACCESS_ERRORS = (
    ChannelPrivateError, ChannelInvalidError, ChatForbiddenError,
    ChatAdminRequiredError,
)
_poll_need_warm: set[int] = set()
_poll_dispatch_tasks: set = set()
_poll_stats = {"recovered": 0}


# --- O'lchov: push kechikishi va o'chirilgan xabarlar ---
# Faqat kuzatuvdagi superguruhlar. Har 10 daqiqada logga bitta qator:
#   * push: xabar yozilganidan bizga yetguncha (Telegram vaqti bo'yicha);
#   * zaxira birinchi topgan: push'dan oldin zaxira topgan xabar yoshi;
#   * push zaxiradan keyin keldi: zaxira topgandan keyin push necha s kechikdi;
#   * o'chirilgan: o'chirilishidan oldin ko'rib ulgurdikmi yoki umuman yo'q.
# Xabar matni yoki shaxsiy ma'lumot yozilmaydi — faqat sonlar.
_MEASURE_INTERVAL = 600
_MEASURE_WINDOW = 15 * 60           # shundan eski xabar o'chirilishi hisoblanmaydi
_MEASURE_BUCKETS = (1, 5, 15, 60)   # sekund chegaralari
_MEASURE_LABELS = ("≤1s", "1–5s", "5–15s", "15–60s", ">60s")
_arrivals = _RecentValues(60_000)   # (chat, id) -> [manba, monotonic, push_keyin]
_deleted_counted = _RecentKeys(60_000)
_recent_arrival_ids: dict[int, deque] = {}
_max_seen_id: dict[int, int] = {}


def _new_measure() -> dict:
    size = len(_MEASURE_LABELS)
    return {
        "push": [0] * size, "poll": [0] * size, "late_push": [0] * size,
        "deleted_seen": [0] * size, "deleted_missed": 0,
    }


_measure_window = _new_measure()
_measure_total = _new_measure()
_measure_window_started = time.monotonic()


def _measure_bucket(seconds: float) -> int:
    for index, limit in enumerate(_MEASURE_BUCKETS):
        if seconds <= limit:
            return index
    return len(_MEASURE_BUCKETS)


def _measure_count(kind: str, seconds: float | None = None) -> None:
    for store in (_measure_window, _measure_total):
        if seconds is None:
            store[kind] += 1
        else:
            store[kind][_measure_bucket(seconds)] += 1


def _message_age_seconds(message) -> float | None:
    date = getattr(message, "date", None)
    if date is None:
        return None
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, (now - date).total_seconds())
    except Exception:
        return None


def _note_arrival(chat_id, message_id, message, source: str, *, service: bool = False) -> None:
    """Xabar bizga birinchi marta qaysi yo'l bilan va qachon yetganini yozadi."""
    if not message_id or chat_id not in _poll_watchers:
        return
    key = (chat_id, message_id)
    now = time.monotonic()
    known = _arrivals.get(key)
    if known is None:
        _arrivals.put(key, [source, now, False])
        ids = _recent_arrival_ids.setdefault(chat_id, deque())
        ids.append((now, message_id))
        while ids and now - ids[0][0] > _MEASURE_WINDOW:
            ids.popleft()
        if message_id > _max_seen_id.get(chat_id, 0):
            _max_seen_id[chat_id] = message_id
        if not service:
            age = _message_age_seconds(message)
            if age is not None:
                _measure_count(source, age)
    elif source == "push" and known[0] == "poll" and not known[2]:
        known[2] = True
        if not service:
            _measure_count("late_push", now - known[1])


def _note_deleted(chat_id, message_ids) -> None:
    """O'chirilgan xabarni o'chirilishidan oldin ko'rganmidik — sanaydi."""
    if chat_id is None or chat_id not in _poll_watchers:
        return
    now = time.monotonic()
    ids = _recent_arrival_ids.get(chat_id)
    while ids and now - ids[0][0] > _MEASURE_WINDOW:
        ids.popleft()
    floor = min(mid for _t, mid in ids) if ids else None
    last_max = _max_seen_id.get(chat_id)
    for message_id in message_ids:
        key = (chat_id, message_id)
        known = _arrivals.get(key)
        if known is not None and now - known[1] <= _MEASURE_WINDOW:
            if _deleted_counted.add(key):
                _measure_count("deleted_seen", now - known[1])
            continue
        # Ko'rilmagan, lekin yaqinda yozilgan (oxirgi 15 daqiqada ko'rilgan
        # xabarlardan yangiroq) — haqiqatan o'tkazib yuborilgan xabar.
        recent = (floor is not None and message_id >= floor) or (
            last_max is not None and message_id > last_max
        )
        if recent and _deleted_counted.add(key):
            _measure_count("deleted_missed")


def _measure_line(store: dict, title: str) -> str:
    def fmt(values):
        return ", ".join(f"{label} {value}" for label, value in zip(_MEASURE_LABELS, values))

    return (
        f"[MEASURE] {title} | push: {sum(store['push'])} ({fmt(store['push'])})"
        f" | zaxira birinchi topgan: {sum(store['poll'])} (xabar yoshi: {fmt(store['poll'])})"
        f" | push zaxiradan keyin keldi: {sum(store['late_push'])} ({fmt(store['late_push'])})"
        f" | o'chirilgan: oldin ko'rilgan {sum(store['deleted_seen'])}"
        f" (ko'rilgandan o'chirilguncha: {fmt(store['deleted_seen'])}),"
        f" umuman ko'rilmagan {store['deleted_missed']}"
    )


def _maybe_log_measure() -> None:
    global _measure_window, _measure_window_started
    if time.monotonic() - _measure_window_started < _MEASURE_INTERVAL:
        return
    logger.info(_measure_line(_measure_window, "oxirgi 10 daqiqa"))
    logger.info(_measure_line(_measure_total, "ishga tushgandan beri"))
    _measure_window = _new_measure()
    _measure_window_started = time.monotonic()


def _client_connected(client) -> bool:
    try:
        return bool(client.is_connected())
    except Exception:
        return False


def _is_supergroup(chat_id: int) -> bool:
    # Oddiy guruhda message_id har akkauntda alohida — umumiy so'rov
    # ishlamaydi; ular push orqali kuzatiladi.
    return str(chat_id).startswith("-100")


def _build_poll_plan(watchers: dict[int, set[int]], online: set[int]):
    """Guruhlarni a'zo onlayn akkauntlar orasida teng taqsimlaydi.

    Oldingi so'rovchi yuklamasi me'yorda bo'lsa o'zgarmaydi (keshlangan
    entity va oqim barqaror qoladi).
    """
    now = time.monotonic()
    load = dict.fromkeys(online, 0)
    plan: dict[int, list[int]] = {uid: [] for uid in online}
    assignee: dict[int, int] = {}
    chats = [chat for chat in watchers if _is_supergroup(chat)]
    # Kam nomzodli guruhlar birinchi: ularning tanlovi cheklangan.
    chats.sort(key=lambda chat: (len(watchers[chat] & online), chat))
    for chat_id in chats:
        # Xato bergan akkaunt vaqtincha so'rovchi bo'lmaydi — guruh
        # boshqa a'zoga o'tadi va kuzatuv to'xtab qolmaydi.
        candidates = [
            uid for uid in sorted(watchers[chat_id] & online)
            if _poll_chat_backoff.get((uid, chat_id), 0) <= now
        ]
        if not candidates:
            continue
        best = min(candidates, key=lambda uid: (load[uid], uid))
        previous = _poll_assignee.get(chat_id)
        pick = (
            previous
            if previous in candidates and load[previous] <= load[best] + 1
            else best
        )
        plan[pick].append(chat_id)
        load[pick] += 1
        assignee[chat_id] = pick
    return plan, assignee


def _load_poll_state() -> None:
    """Restartdan oldingi holat: qisqa to'xtashdagi xabarlar ham topiladi."""
    try:
        data = json.loads(_POLL_STATE_PATH.read_text(encoding="utf-8"))
        if time.time() - float(data.get("saved_at", 0)) > _POLL_MAX_AGE:
            return
        for chat_id, message_id in (data.get("last") or {}).items():
            _poll_last.setdefault(int(chat_id), int(message_id))
    except (OSError, ValueError, TypeError, AttributeError):
        return


def _save_poll_state() -> None:
    try:
        tmp = _POLL_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"saved_at": int(time.time()), "last": _poll_last}),
            encoding="utf-8",
        )
        os.replace(tmp, _POLL_STATE_PATH)
    except OSError:
        logger.warning("[POLL] holat saqlanmadi")


def _dispatch_polled(chat_id: int, message, polled_by: int | None = None) -> None:
    """Zaxira topgan xabarni push ko'rmagan har bir kuzatuvchiga beradi."""
    now = time.monotonic()
    for owner_id in sorted(_poll_watchers.get(chat_id, ())):
        handler = _handlers.get(owner_id)
        if handler is None or owner_id not in _clients:
            continue
        if _poll_no_access.get((owner_id, chat_id), 0) > now:
            continue
        if not _seen_messages.add((owner_id, chat_id, message.id)):
            continue
        _poll_stats["recovered"] += 1
        logger.info(
            "[POLL] push kelmagan xabar zaxiradan olindi owner=%s chat=%s msg=%s",
            owner_id, chat_id, message.id,
        )
        task = asyncio.create_task(handler(_PolledEvent(message, polled_by)))
        _poll_dispatch_tasks.add(task)
        task.add_done_callback(_poll_dispatch_tasks.discard)


async def _poll_chat(owner_id: int, client, chat_id: int) -> None:
    key = (owner_id, chat_id)
    if _poll_chat_backoff.get(key, 0) > time.monotonic():
        return
    last = _poll_last.get(chat_id)
    try:
        entity = await client.get_input_entity(chat_id)
        if last is None:
            # Birinchi marta: faqat boshlang'ich nuqta, eski xabarlar emas.
            latest = await client.get_messages(entity, limit=1)
            _poll_last.setdefault(chat_id, latest[0].id if latest else 0)
            return
        # Telethon min_id ni serverga yubormaydi: oxirgi ``limit`` ta xabarni
        # yuklab, o'zi filtrlaydi. Shuning uchun avval oz so'raymiz; hammasi
        # yangi bo'lsagina (ko'proq bo'lishi mumkin) to'liq partiya olinadi.
        messages = await client.get_messages(entity, limit=_POLL_PEEK, min_id=last)
        if len(messages) >= _POLL_PEEK:
            messages = await client.get_messages(entity, limit=_POLL_BATCH, min_id=last)
    except FloodWaitError as exc:
        _poll_paused_until[owner_id] = time.monotonic() + exc.seconds + 1
        logger.warning(
            "[POLL] FloodWait owner=%s %ss — guruhlari boshqa akkauntlarga o'tadi",
            owner_id, exc.seconds,
        )
        return
    except _POLL_ACCESS_ERRORS as exc:
        # Akkaunt guruhga kira olmaydi (ban/chiqarilgan): unga zaxira xabar
        # yuborilmaydi, guruh boshqa a'zoga o'tadi, a'zolik darhol tekshiriladi.
        until = time.monotonic() + _POLL_NO_ACCESS_SECONDS
        _poll_chat_backoff[key] = until
        _poll_no_access[key] = until
        logger.warning(
            "[POLL] owner=%s chat=%s guruhga kirish yo'q: %s",
            owner_id, chat_id, type(exc).__name__,
        )
        _request_membership_audit(owner_id)
        return
    except ValueError:
        # Entity sessiya keshida yo'q — dialoglar qayta yuklanadi.
        _poll_need_warm.add(owner_id)
        _poll_chat_backoff[key] = time.monotonic() + 60
        return
    except Exception as exc:
        _poll_chat_backoff[key] = time.monotonic() + 300
        logger.warning(
            "[POLL] owner=%s chat=%s so'rov xato: %s",
            owner_id, chat_id, type(exc).__name__,
        )
        return
    if not messages:
        return
    for message in messages:
        if message.id > last:
            _note_arrival(
                chat_id, message.id, message, "poll",
                service=getattr(message, "action", None) is not None,
            )
    newest = max(message.id for message in messages)
    _poll_last[chat_id] = max(_poll_last.get(chat_id, 0), newest)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=_POLL_MAX_AGE
    )
    fresh = []
    for message in sorted(messages, key=lambda item: item.id):
        if message.id <= last or getattr(message, "action", None) is not None:
            continue
        date = getattr(message, "date", None)
        if date is not None and date < cutoff:
            continue
        fresh.append(message)
    if fresh:
        _schedule_polled_dispatch(chat_id, fresh, owner_id)


def _schedule_polled_dispatch(chat_id: int, messages, polled_by: int) -> None:
    """Push'ga ulgurish vaqti beriladi: faqat u ko'rmagan xabarlar ishlanadi.

    Odatda push xabarni 1 soniya ichida yetkazadi. Zaxira uni darhol
    ishlasa, bir xabar ikki marta tekshirilardi (CPU sarfi, yolg'on
    "push kelmagan" yozuvlari).
    """
    async def _later():
        await asyncio.sleep(_POLL_DISPATCH_GRACE)
        for message in messages:
            _dispatch_polled(chat_id, message, polled_by=polled_by)

    task = asyncio.create_task(_later())
    _poll_dispatch_tasks.add(task)
    task.add_done_callback(_poll_dispatch_tasks.discard)


async def _poll_worker(owner_id: int) -> None:
    """Bitta akkaunt: o'ziga biriktirilgan guruhlarni navbat bilan so'raydi."""
    warmed_client = None
    warmed_at = 0.0
    while True:
        client = _clients.get(owner_id)
        chats = list(_poll_plan.get(owner_id, ()))
        if client is None or not chats or not _client_connected(client):
            return
        now = time.monotonic()
        if warmed_client is not client or (
            owner_id in _poll_need_warm and now - warmed_at >= _POLL_REWARM_SECONDS
        ):
            # Guruh entity'lari (access_hash) keshga tushishi uchun.
            try:
                await client.get_dialogs(limit=None)
            except FloodWaitError as exc:
                _poll_paused_until[owner_id] = time.monotonic() + exc.seconds + 1
                return
            except Exception:
                logger.warning("[POLL] dialoglar yuklanmadi owner=%s", owner_id)
            warmed_client, warmed_at = client, time.monotonic()
            _poll_need_warm.discard(owner_id)
        cycle_started = time.monotonic()
        for chat_id in chats:
            if _clients.get(owner_id) is not client or not _client_connected(client):
                return
            if _poll_paused_until.get(owner_id, 0) > time.monotonic():
                return
            started = time.monotonic()
            await _poll_chat(owner_id, client, chat_id)
            await asyncio.sleep(max(0.0, _POLL_GAP - (time.monotonic() - started)))
        rest = _POLL_INTERVAL - (time.monotonic() - cycle_started)
        if rest > 0:
            await asyncio.sleep(rest)


async def _poll_supervisor() -> None:
    global _poll_plan, _poll_assignee, _poll_watchers
    if not _POLL_ENABLED:
        logger.info("[POLL] zaxira tekshiruv o'chirilgan (SCANNER_POLL_ENABLED=0)")
        return
    _load_poll_state()
    logger.info(
        "[POLL] zaxira tekshiruv yoqildi: guruh oralig'i>=%ss, akkaunt pauzasi=%ss",
        _POLL_INTERVAL, _POLL_GAP,
    )
    while True:
        try:
            now = time.monotonic()
            online = {
                uid for uid, client in _clients.items()
                if _client_connected(client)
                and _poll_paused_until.get(uid, 0) <= now
            }
            watchers = get_active_chat_watchers()
            _poll_plan, _poll_assignee = _build_poll_plan(watchers, online)
            _poll_watchers = watchers
            for uid, chats in _poll_plan.items():
                worker = _poll_workers.get(uid)
                if chats and (worker is None or worker.done()):
                    _poll_workers[uid] = asyncio.create_task(_poll_worker(uid))
            _save_poll_state()
            _maybe_log_measure()
        except Exception:
            logger.exception("[POLL] supervisor xato")
        await asyncio.sleep(_POLL_PLAN_SECONDS)


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
    _tasks.append(asyncio.create_task(_session_health_loop()))
    _tasks.append(asyncio.create_task(_poll_supervisor()))


async def run():
    """Barcha sessiyalar managerini ishga tushiradi (main.py dan)."""
    start_background()
    if _tasks:
        await asyncio.gather(*_tasks)
