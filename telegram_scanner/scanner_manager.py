"""Ko'p foydalanuvchili skaner: har bir foydalanuvchi — alohida sessiya.

Har bir tasdiqlangan foydalanuvchining shifrlangan sessiyasidan alohida
Telethon client ko'tariladi. Client FAQAT egasining guruhlarini kuzatadi,
xabar topilsa FAQAT egasiga boradi. Kalitlar va shart — adminniki (global).
"""
import asyncio
import calendar
import datetime
import html
import logging
import time
from pathlib import Path

from telethon import TelegramClient, events, utils, errors
from telethon.sessions import StringSession
from telethon.tl.functions.messages import TranscribeAudioRequest
from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    UpdateTranscribedAudio,
)

from config import ADMIN_ID, API_HASH, API_ID, BASE_DIR
from database import (
    get_all_users_full,
    save_lead_review,
    get_owner_active_chat_ids,
    get_pending_user_groups,
    get_user_full,
    get_setting,
    set_setting,
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
import watch
from notifier import (
    build_feedback_row,
    build_message_link,
    build_notification_text,
    find_phone_text,
    send_to_bot_api,
    send_document_to_bot_api,
)

logger = logging.getLogger(__name__)

# Hozir ko'tarilayotgan sessiyalar (ikki marta ulanishning oldini oladi)
_starting: set = set()
# 👁 Kuzatuv kartalari (admin uchun) — fon vazifalari
_watch_tasks: set = set()

_clients: dict[int, TelegramClient] = {}
_tasks: list[asyncio.Task] = []

# Voice transcription is intentionally conservative: each Telegram message is
# requested once, pending results arrive as UpdateTranscribedAudio, and RPC
# limits are cached per owner+group in the existing settings table.
VOICE_TRANSCRIPT_BATCH_BYTES = 32 * 1024
VOICE_TRANSCRIPT_MAX_OWNER_BYTES = 64 * 1024
VOICE_TRANSCRIPT_MAX_TOTAL_BYTES = 1024 * 1024
VOICE_TRANSCRIPT_PENDING_TIMEOUT = 60
VOICE_TRANSCRIPT_RETRY_SECONDS = 300
VOICE_TRANSCRIPT_WEEK_SECONDS = 7 * 24 * 60 * 60
VOICE_TRANSCRIPT_DIR = Path(BASE_DIR) / "data" / "voice_transcripts"

_pending_transcriptions: dict[tuple[int, int, int], asyncio.Queue] = {}
_transcript_locks: dict[int, asyncio.Lock] = {}


def _voice_key(name: str, owner_id: int, chat_id: int) -> str:
    return f"voice_{name}:{owner_id}:{chat_id}"


def _transcript_collection_enabled() -> bool:
    return get_setting("voice_transcript_collection") == "1"


def _as_timestamp(value) -> int:
    if value is None:
        return 0
    try:
        if value.tzinfo is None:
            return int(calendar.timegm(value.utctimetuple()))
        return int(value.timestamp())
    except (AttributeError, OverflowError, OSError, TypeError, ValueError):
        return 0


def _is_voice_note(message) -> bool:
    """Faqat Telegram voice note (oddiy musiqa/audio fayli emas)."""
    if message is None:
        return False
    if getattr(message, "voice", None):
        return True
    document = getattr(getattr(message, "media", None), "document", None)
    return any(
        isinstance(attribute, DocumentAttributeAudio)
        and bool(getattr(attribute, "voice", False))
        for attribute in (getattr(document, "attributes", None) or [])
    )


def _voice_claim_message(owner_id: int, chat_id: int, message_id: int) -> bool:
    """Duplicate/update replay bo'lsa, bir xabarga ikkinchi API so'rovi yo'q."""
    key = _voice_key("last_message_id", owner_id, chat_id)
    try:
        previous = int(get_setting(key) or 0)
    except (TypeError, ValueError):
        previous = 0
    if message_id <= previous:
        return False
    set_setting(key, message_id)
    return True


async def _notify_voice_block(owner_id: int, chat_id: int, until: int, reason: str) -> None:
    """Bir owner/guruh holati uchun admin xabarini 6 soatda ko'pi bilan bir marta beradi."""
    key = _voice_key("notice", owner_id, chat_id)
    try:
        last_notice = int(get_setting(key) or 0)
    except (TypeError, ValueError):
        last_notice = 0
    now = int(time.time())
    if now - last_notice < 6 * 60 * 60:
        return
    set_setting(key, now)
    if not ADMIN_ID:
        return
    when = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime(until)) if until else "qo'lda qayta yoqilguncha"
    group_line = (
        "Guruh: barcha guruhlar (akkaunt cheklovi)\n"
        if chat_id == 0 else f"Guruh: <code>{chat_id}</code>\n"
    )
    await send_to_bot_api(
        "🎙 <b>Ovoz transkripsiyasi vaqtincha to'xtatildi</b>\n\n"
        f"Sessiya egasi: <code>{owner_id}</code>\n"
        f"{group_line}"
        f"Sabab: {html.escape(reason, quote=False)}\n"
        f"Keyingi tekshiruv: {when}.\n\n"
        "Yozma xabarlar skaneri davom etadi. Ovoz transkripsiyasi uchun "
        "qayta-qayta so'rov yuborilmaydi.",
        chat_id=ADMIN_ID,
    )


async def _set_voice_block(
    owner_id: int, chat_id: int, until: int, reason: str
) -> None:
    set_setting(_voice_key("block_until", owner_id, chat_id), max(0, int(until)))
    set_setting(_voice_key("block_reason", owner_id, chat_id), reason[:80])
    await _notify_voice_block(owner_id, chat_id, until, reason)


async def _transcribe_voice(owner_id: int, client: TelegramClient, event) -> str | None:
    """Telegram native STT; per-message once-only, quota/FloodWait aware."""
    chat_id, message_id = int(event.chat_id), int(event.id)
    if not _voice_claim_message(owner_id, chat_id, message_id):
        logger.info("[VOICE] takroriy xabar o'tkazildi owner=%s chat=%s", owner_id, chat_id)
        return None

    now = int(time.time())
    account_block_key = _voice_key("account_block_until", owner_id, 0)
    try:
        account_blocked_until = int(get_setting(account_block_key) or 0)
    except (TypeError, ValueError):
        account_blocked_until = 0
    if account_blocked_until > now:
        return None
    if account_blocked_until:
        set_setting(account_block_key, 0)

    block_key = _voice_key("block_until", owner_id, chat_id)
    try:
        blocked_until = int(get_setting(block_key) or 0)
    except (TypeError, ValueError):
        blocked_until = 0
    if blocked_until > now:
        return None
    if blocked_until:
        set_setting(block_key, 0)
        set_setting(_voice_key("block_reason", owner_id, chat_id), "")

    key = (owner_id, chat_id, message_id)
    updates: asyncio.Queue = asyncio.Queue(maxsize=8)
    _pending_transcriptions[key] = updates
    try:
        peer = getattr(event, "input_chat", None)
        if peer is None:
            peer = await client.get_input_entity(chat_id)
        result = await client(TranscribeAudioRequest(peer=peer, msg_id=message_id))

        reset_at = _as_timestamp(getattr(result, "trial_remains_until_date", None))
        remaining = getattr(result, "trial_remains_num", None)
        if reset_at:
            set_setting(_voice_key("trial_reset", owner_id, chat_id), reset_at)
        if remaining is not None:
            if int(remaining) <= 0:
                until = reset_at or now + VOICE_TRANSCRIPT_WEEK_SECONDS
                await _set_voice_block(
                    owner_id, chat_id, until,
                    "Telegram bepul transkripsiya limitini tugatdi",
                )
            else:
                set_setting(block_key, 0)
                set_setting(_voice_key("block_reason", owner_id, chat_id), "")

        if not getattr(result, "pending", False):
            return (getattr(result, "text", "") or "") or None

        transcription_id = getattr(result, "transcription_id", None)
        deadline = asyncio.get_running_loop().time() + VOICE_TRANSCRIPT_PENDING_TIMEOUT
        while True:
            remaining_time = deadline - asyncio.get_running_loop().time()
            if remaining_time <= 0:
                raise asyncio.TimeoutError("Telegram transkripsiyasi vaqtida tugamadi")
            update = await asyncio.wait_for(updates.get(), timeout=remaining_time)
            if getattr(update, "transcription_id", None) != transcription_id:
                continue
            if getattr(update, "pending", False):
                continue
            return (getattr(update, "text", "") or "") or None

    except errors.FloodWaitError as exc:
        until = int(time.time()) + max(1, int(getattr(exc, "seconds", 1))) + 5
        reason = f"Telegram FloodWait ({getattr(exc, 'seconds', '?')} soniya)"
        set_setting(account_block_key, until)
        set_setting(block_key, until)
        set_setting(_voice_key("block_reason", owner_id, chat_id), reason[:80])
        await _notify_voice_block(owner_id, 0, until, reason)
        return None
    except errors.RPCError as exc:
        message = str(getattr(exc, "message", "") or exc)
        upper = message.upper()
        quota_error = any(
            marker in upper
            for marker in (
                "PREMIUM_ACCOUNT_REQUIRED",
                "TRANSCRIPTION_LIMIT",
                "TRANSCRIBE_AUDIO_LIMIT",
                "TRIAL_LIMIT",
                "QUOTA_EXCEEDED",
            )
        )
        if quota_error:
            try:
                until = int(get_setting(_voice_key("trial_reset", owner_id, chat_id)) or 0)
            except (TypeError, ValueError):
                until = 0
            if until <= int(time.time()):
                until = int(time.time()) + VOICE_TRANSCRIPT_WEEK_SECONDS
            reason = "Telegram transkripsiya huquqi yoki bepul limiti yo'q"
            await _set_voice_block(owner_id, chat_id, until, reason)
        else:
            # Noma'lum RPC rad javobida ham butun akkaunt uchun cooldown:
            # boshqa guruhdan shu zahoti qayta so'rov yubormaymiz.
            until = int(time.time()) + VOICE_TRANSCRIPT_RETRY_SECONDS
            reason = f"Telegram RPC rad etdi: {message[:60]}"
            set_setting(account_block_key, until)
            set_setting(block_key, until)
            set_setting(_voice_key("block_reason", owner_id, chat_id), reason[:80])
            await _notify_voice_block(owner_id, 0, until, reason)
        logger.warning(
            "[VOICE] RPC rad javobi owner=%s chat=%s type=%s",
            owner_id, chat_id, type(exc).__name__,
        )
        return None
    except Exception as exc:
        # Tarmoq/pending xatosida shu xabar qayta so'ralmaydi; yangi xabarlar
        # uchun qisqa circuit-breaker ham qo'yiladi.
        until = int(time.time()) + 60
        reason = f"Transkripsiya vaqtinchalik xatosi: {type(exc).__name__}"
        set_setting(account_block_key, until)
        set_setting(block_key, until)
        set_setting(_voice_key("block_reason", owner_id, chat_id), reason[:80])
        await _notify_voice_block(owner_id, 0, until, reason)
        logger.warning(
            "[VOICE] transkripsiya xatosi owner=%s chat=%s type=%s",
            owner_id, chat_id, type(exc).__name__,
        )
        return None
    finally:
        _pending_transcriptions.pop(key, None)


def _voice_archive_paths() -> list[Path]:
    try:
        return sorted(VOICE_TRANSCRIPT_DIR.glob("*.txt"))
    except OSError:
        return []


def _voice_archive_total_bytes() -> int:
    total = 0
    for path in _voice_archive_paths():
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


async def _send_voice_archive_locked(owner_id: int, *, force: bool = False) -> bool:
    path = VOICE_TRANSCRIPT_DIR / f"{owner_id}.txt"
    try:
        size = path.stat().st_size
    except OSError:
        return True
    if not size or (not force and size < VOICE_TRANSCRIPT_BATCH_BYTES):
        return True

    now = int(time.time())
    retry_key = _voice_key("archive_send_attempt", owner_id, 0)
    try:
        last_attempt = int(get_setting(retry_key) or 0)
    except (TypeError, ValueError):
        last_attempt = 0
    if now - last_attempt < VOICE_TRANSCRIPT_RETRY_SECONDS:
        return False
    set_setting(retry_key, now)
    filename = f"ovoz-transkript-{owner_id}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(now))}.txt"
    sent = await send_document_to_bot_api(path, filename, chat_id=ADMIN_ID)
    if not sent:
        return False
    try:
        path.unlink()
    except OSError:
        logger.exception("[VOICE_ARCHIVE] yuborilgan nusxani o'chirib bo'lmadi owner=%s", owner_id)
        return False
    logger.info("[VOICE_ARCHIVE] yuborildi va lokal nusxa o'chirildi owner=%s bytes=%s", owner_id, size)
    return True


async def _notify_voice_archive_full(owner_id: int) -> None:
    key = _voice_key("archive_full_notice", owner_id, 0)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if get_setting(key) == day:
        return
    set_setting(key, day)
    if ADMIN_ID:
        await send_to_bot_api(
            "⚠️ <b>Ovoz transkriptlari vaqtinchalik yig'ilmayapti</b>\n\n"
            f"Sessiya <code>{owner_id}</code> uchun fayl limiti to'ldi yoki "
            "oldingi fayl yuborilmadi. Mijoz qidirish davom etadi. Admin "
            "yig'ishni o'chirib-yoqib, yuborishni qayta tekshirishi mumkin.",
            chat_id=ADMIN_ID,
        )


async def _append_voice_transcript(owner_id: int, transcript: str) -> bool:
    """Telegram qaytargan to'liq matnni, sanamasdan, vaqtinchalik faylga qo'shadi."""
    if not _transcript_collection_enabled() or not transcript:
        return False
    lock = _transcript_locks.setdefault(owner_id, asyncio.Lock())
    async with lock:
        try:
            VOICE_TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
            path = VOICE_TRANSCRIPT_DIR / f"{owner_id}.txt"
            payload = transcript.encode("utf-8") + b"\n\n"
            current = path.stat().st_size if path.exists() else 0
            total = _voice_archive_total_bytes()

            if current + len(payload) > VOICE_TRANSCRIPT_MAX_OWNER_BYTES:
                await _send_voice_archive_locked(owner_id, force=True)
                current = path.stat().st_size if path.exists() else 0
                total = _voice_archive_total_bytes()
            if (
                len(payload) > VOICE_TRANSCRIPT_MAX_OWNER_BYTES
                or current + len(payload) > VOICE_TRANSCRIPT_MAX_OWNER_BYTES
                or total + len(payload) > VOICE_TRANSCRIPT_MAX_TOTAL_BYTES
            ):
                await _notify_voice_archive_full(owner_id)
                return False

            with path.open("ab") as stream:
                stream.write(payload)
            current += len(payload)
            if current >= VOICE_TRANSCRIPT_BATCH_BYTES:
                await _send_voice_archive_locked(owner_id)
            return True
        except OSError:
            logger.exception("[VOICE_ARCHIVE] yozib bo'lmadi owner=%s", owner_id)
            return False


async def flush_voice_transcripts(*, force: bool = True) -> None:
    """Kutayotgan sessiya fayllarini admin'ga yuborishga bir marta urinadi."""
    owners = []
    for path in _voice_archive_paths():
        try:
            owner_id = int(path.stem)
        except ValueError:
            continue
        owners.append(owner_id)
    for owner_id in owners:
        lock = _transcript_locks.setdefault(owner_id, asyncio.Lock())
        async with lock:
            await _send_voice_archive_locked(owner_id, force=force)


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


async def list_user_dialogs(owner_id: int, limit: int = 300):
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
        _last_event[owner_id] = (
            int(time.time()), chat_id, (text or "")[:60]
        )


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


def _queue_watch_card(event, verdict, text: str | None = None) -> None:
    """👁 Kuzatuv kartasini adminga yuboradi (faqat o'z akkaunti)."""
    try:
        card = watch.card_text(
            text if text is not None else (getattr(event, "raw_text", "") or ""),
            verdict,
        )
        task = asyncio.create_task(send_to_bot_api(card, None, chat_id=ADMIN_ID))
        _watch_tasks.add(task)
        task.add_done_callback(_watch_tasks.discard)
    except Exception:
        logger.exception("[WATCH] karta yuborilmadi")


def _make_handler(owner_id: int, client: TelegramClient):
    async def _transcribed_update(update):
        try:
            chat_id = utils.get_peer_id(update.peer)
            key = (owner_id, int(chat_id), int(update.msg_id))
            queue = _pending_transcriptions.get(key)
            if queue is not None:
                # Partial update'lar ko'paysa ham oxirgi (yakuniy) natijani
                # saqlab qolamiz.
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(update)
        except Exception:
            logger.debug("[VOICE] transkripsiya update'i moslashtirilmadi", exc_info=True)

    client.add_event_handler(
        _transcribed_update, events.Raw(types=UpdateTranscribedAudio)
    )

    @client.on(events.NewMessage)
    async def _handler(event):
        chat_id = getattr(event, "chat_id", None)
        is_private = bool(getattr(event, "is_private", False))
        initial_text = event.raw_text or ""
        _note_event(owner_id, is_private, chat_id, initial_text)
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
        is_sticker = _has_sticker(message)
        is_voice = _is_voice_note(message)
        if not raw_text and not is_sticker and not is_voice:
            return

        if is_voice:
            # Avval arzon gate'lar: tizim/tarif/egasining skaneri/guruh.
            # Bo'sh matn kalit bosqichida to'xtashi kutilgan; boshqa bosqichdagi
            # rad javobida qimmat MTProto transkripsiya so'rovi yuborilmaydi.
            gate = evaluate(owner_id, "", chat_id=chat_id)
            if gate.stage != "keywords":
                _log_skip(owner_id, chat_id, gate)
                return
            transcript = await _transcribe_voice(owner_id, client, event)
            if not transcript:
                return
            if _transcript_collection_enabled():
                await _append_voice_transcript(owner_id, transcript)
            # Caption bo'lsa ham saqlab qolamiz; kalitlar ikkala matndan
            # tekshiriladi. Arxivga esa faqat Telegram transkripti yoziladi.
            raw_text = "\n".join(part for part in (initial_text, transcript) if part)

        # Matn va ovoz transkripti aynan bitta mavjud filtr zanjiridan o'tadi.
        verdict = evaluate(
            owner_id,
            raw_text,
            is_sticker=is_sticker,
            chat_id=chat_id,
        )
        if owner_id == ADMIN_ID and watch.is_active():
            _queue_watch_card(event, verdict, raw_text)
        if not verdict.ok:
            # O'tkazib yuborish sababi logga yoziladi: [SCAN] skip ...
            # Shu bilan birga: «tizim to'xtatilgan» holati HAR xabar uchun
            # yozilsa log 2 daqiqada 200 qatorga to'lib ketadi va undan
            # hech narsa ko'rinmaydi. Shuning uchun bunday takrorlar
            # daqiqada bir marta, hisob bilan yoziladi.
            _log_skip(owner_id, event.chat_id, verdict)
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

        phone = find_phone_text(raw_text, sender)
        chat = await event.get_chat()
        group_title = getattr(chat, "title", None) or "Noma'lum guruh"
        message_link = build_message_link(chat, event.chat_id, event.id)
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
        if user_id is not None:
            rows.append([{"text": "💬 Mijozga yozish (Lichka)", "url": f"tg://user?id={user_id}"}])
        if message_link:
            rows.append([{"text": "↗️ Guruhdagi asl xabarni ochish", "url": message_link}])
        # Fikr-mulohaza statistikasi; vaznni faqat admin baholashi o'zgartiradi.
        review_id = save_lead_review(owner_id, verdict.matched)
        if review_id:
            rows.append(build_feedback_row(review_id))
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
            _last_sync_ts = int(time.time())
            from database import set_setting as _ss
            _ss("userbot_last_seen", _last_sync_ts)
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
    # Oldingi ishga tushishda yuborilmay qolgan kichik transcript partiyalarini
    # qayta ko'radi; send helper o'z retry oynasini saqlaydi.
    _tasks.append(asyncio.create_task(flush_voice_transcripts(force=True)))


async def run():
    """Barcha sessiyalar managerini ishga tushiradi (main.py dan)."""
    start_background()
    if _tasks:
        await asyncio.gather(*_tasks)
