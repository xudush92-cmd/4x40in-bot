"""
AVTO BOT — Telegram avto-poster bot (yangi arxitektura).

Modullar:
- database.py    — SQLite storage (JSON o'rniga)
- client_pool.py — Telethon client pool (RAM tejash)
- worker_manager.py — Worker limit va graceful shutdown
- health.py      — HTTP /health endpoint
- rate_limiter.py — Anti-spam himoya

XAVFSIZLIK:
- Kod va parol DISK-ga saqlanmaydi (faqat StringSession)
- SQLite WAL mode — concurrent access xavfsiz
- Kod kiritish: inline numpad (Telegram anti-fraud bypass)
- Rate limiting (login, command, modify)
- Graceful shutdown (SIGTERM/SIGINT)

ISHLATISH:
    pip install -r requirements.txt
    cp .env.example .env  # va to'ldiring
    python avto_bot.py
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PasswordHashInvalidError,
    PeerIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    UserDeactivatedBanError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChatInviteAlready
from telethon.utils import get_peer_id
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBotCommand,
    Chat,
    Channel,
    MessageEntityCashtag,
    MessageEntityCode,
    MessageEntityCustomEmoji,
    MessageEntityEmail,
    MessageEntityHashtag,
    MessageEntityItalic,
    MessageEntityMention,
    MessageEntityMentionName,
    MessageEntityPhone,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    MessageEntityUrl,
)

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MessageEntity,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Ichki modullar
import database as db
from client_pool import ClientPool, PoolBusyError, SessionInvalidError
from worker_manager import WorkerManager, MAX_CONCURRENT_WORKERS
from health import HealthServer, format_status_message, START_TIME, _get_memory_info
from rate_limiter import RateLimiter
from chat_parser import extract_chat_targets

# ─────────────────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────────────────
load_dotenv()


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Environment variable '{name}' yo'q. .env faylini tekshiring."
        )
    return v


API_ID = int(_require_env("API_ID"))
API_HASH = _require_env("API_HASH")
BOT_TOKEN = _require_env("BOT_TOKEN")
SUPER_ADMIN = int(_require_env("ADMIN_ID"))

# ─────────────────────────────────────────────────────────────────────────
# KONSTANTALAR
# ─────────────────────────────────────────────────────────────────────────
# Tariflar: tariff raqami -> (nomi, max_chats, max_posts)
#   1-tarif 🟢 Start   → 5 chat / 10 post
#   2-tarif 🔵 Biznes  → 10 chat / 25 post
#   3-tarif 🟡 Pro     → 20 chat / 50 post
#   4-tarif 🔴 Premium → 50 chat / 100 post
TARIFFS = {
    1: ("🟢 Start", 5, 10),
    2: ("🔵 Biznes", 10, 25),
    3: ("🟡 Pro", 20, 50),
    4: ("🔴 Premium", 50, 100),
}
DEFAULT_TARIFF = 1

MIN_INTERVAL_MIN = 5
MAX_INTERVAL_MIN = 1440
LOGIN_TIMEOUT_S = 300
SEND_DELAY_S = 5
INTERVAL_JITTER_S = 30
START_JITTER_MAX_S = 60     # worker birinchi start: 0-60s tasodifiy kechikish (yukni yoyish)
MAX_CHAT_FAILS = 3          # 3 ketma-ket xatodan so'ng chat navbatga olinadi
TARIFF_DURATION_DAYS = 30   # default tarif muddati (kun)
TARIFF_WARN_DAYS = 3        # muddat tugashidan necha kun oldin ogohlantirish
ADMIN_ACTION_TIMEOUT_S = 600
ADMIN_USER_PAGE_SIZE = 8
ADMIN_ROSTER_PAGE_SIZE = 6
GROUP_SCAN_PAGE_SIZE = 7
GROUP_SCAN_MAX_DIALOGS = 1000
GROUP_SCAN_STATE_TTL_S = 15 * 60
MAX_ADMIN_TERM_DAYS = 3650
MAX_ADMIN_MESSAGE_LENGTH = 3500
SUSPENSION_CHECK_INTERVAL_S = 60
DAILY_MESSAGE_CHECK_INTERVAL_S = 60
DAILY_MESSAGE_TIMEZONE = ZoneInfo("Asia/Tashkent")

ADMIN_CONTACT_PHONE = "+998938670592"
# Referal link uchun bot username (postlarga qo'shilmaydi, faqat referal linkda).
# ENV orqali ham berish mumkin: BOT_USERNAME=avtoelon_el_uzbot
BOT_USERNAME = os.getenv("BOT_USERNAME", "avtoelon_el_uzbot").lstrip("@")

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

LOG_FILE = "avto_bot.log"


def tariff_limits(tariff: int) -> tuple[int, int]:
    """Tarif raqamidan (max_chats, max_posts) qaytaradi."""
    _, mc, mp = TARIFFS.get(int(tariff or DEFAULT_TARIFF), TARIFFS[DEFAULT_TARIFF])
    return mc, mp


def tariff_name(tariff: int) -> str:
    """Tarif nomi (masalan '🔵 Biznes')."""
    name, _, _ = TARIFFS.get(int(tariff or DEFAULT_TARIFF), TARIFFS[DEFAULT_TARIFF])
    return name


def tariff_label(tariff: int) -> str:
    """Tarifning inson o'qiydigan ko'rinishi."""
    t = int(tariff or DEFAULT_TARIFF)
    name, mc, mp = TARIFFS.get(t, TARIFFS[DEFAULT_TARIFF])
    return f"{t}-tarif {name} ({mc} chat / {mp} post)"


def calc_expiry(days: int = TARIFF_DURATION_DAYS) -> str:
    """Hozirdan {days} kun keyingi sanani ISO format string qaytaradi."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _days_until(expires_iso: str | None) -> int | None:
    """ISO sanadan hozirgacha nechа kun qolganini (floor) qaytaradi. None = noma'lum."""
    if not expires_iso:
        return None
    try:
        dt = datetime.strptime(expires_iso, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds() // 86400))
    except Exception:
        return None


def _waiting_mode_text(prefix: str = "") -> str:
    """Muddat tugaganda ko'rsatiladigan 'kutish rejimi' xabari."""
    head = prefix or "⏸ KUTISH REJIMI"
    return (
        f"{head}\n\n"
        "Tarifingiz muddati tugadi — posting AVTOMATIK to'xtatildi.\n"
        "Bot kutish rejimiga o'tdi va yangi post yubormaydi.\n\n"
        "Davom ettirish uchun tarifni uzaytiring:\n"
        f"📱 Admin: {ADMIN_CONTACT_PHONE}"
    )

# ─────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("AvtoBot")
logger.setLevel(logging.INFO)
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(_fh)
logger.addHandler(_sh)


def log(msg: str, level: str = "info") -> None:
    getattr(logger, level)(msg)


# ─────────────────────────────────────────────────────────────────────────
# ENTITY KONVERTOR (PTB → Telethon)
# ─────────────────────────────────────────────────────────────────────────
def entity_to_dict(e: MessageEntity) -> dict:
    d = {"type": e.type, "offset": e.offset, "length": e.length}
    if e.url:
        d["url"] = e.url
    if e.language:
        d["language"] = e.language
    if e.custom_emoji_id:
        d["custom_emoji_id"] = e.custom_emoji_id
    if e.user:
        d["user_id"] = e.user.id
    return d


def dicts_to_telethon_entities(items: list[dict]) -> list:
    out = []
    for d in items or []:
        t = d.get("type")
        off = int(d.get("offset", 0))
        ln = int(d.get("length", 0))
        if t == "bold":
            out.append(MessageEntityBold(off, ln))
        elif t == "italic":
            out.append(MessageEntityItalic(off, ln))
        elif t == "underline":
            out.append(MessageEntityUnderline(off, ln))
        elif t == "strikethrough":
            out.append(MessageEntityStrike(off, ln))
        elif t == "spoiler":
            out.append(MessageEntitySpoiler(off, ln))
        elif t == "code":
            out.append(MessageEntityCode(off, ln))
        elif t == "pre":
            out.append(MessageEntityPre(off, ln, language=d.get("language", "") or ""))
        elif t == "text_link":
            out.append(MessageEntityTextUrl(off, ln, url=d.get("url", "")))
        elif t == "text_mention":
            uid = d.get("user_id")
            if uid:
                out.append(MessageEntityMentionName(off, ln, user_id=int(uid)))
        elif t == "url":
            out.append(MessageEntityUrl(off, ln))
        elif t == "mention":
            out.append(MessageEntityMention(off, ln))
        elif t == "hashtag":
            out.append(MessageEntityHashtag(off, ln))
        elif t == "cashtag":
            out.append(MessageEntityCashtag(off, ln))
        elif t == "bot_command":
            out.append(MessageEntityBotCommand(off, ln))
        elif t == "email":
            out.append(MessageEntityEmail(off, ln))
        elif t == "phone_number":
            out.append(MessageEntityPhone(off, ln))
        elif t == "custom_emoji":
            cid = d.get("custom_emoji_id")
            if cid:
                out.append(MessageEntityCustomEmoji(off, ln, document_id=int(cid)))
    return out


# ─────────────────────────────────────────────────────────────────────────
# IN-MEMORY HOLAT
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class LoginCtx:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    started_at: float
    wrong_count: int = 0
    resend_count: int = 0


user_states: dict[int, dict] = {}
login_ctx: dict[int, LoginCtx] = {}
_user_control_locks: dict[int, asyncio.Lock] = {}


def _user_control_lock(uid: int) -> asyncio.Lock:
    """Serialize Start and admin suspension changes for each individual user."""
    lock = _user_control_locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _user_control_locks[uid] = lock
    return lock


# Global komponentlar (main() da ishga tushiriladi)
application: Application | None = None
client_pool: ClientPool | None = None
worker_manager: WorkerManager | None = None
health_server: HealthServer | None = None
rate_limiter: RateLimiter = RateLimiter()


def is_super(uid: int) -> bool:
    return uid == SUPER_ADMIN


async def user_limits(uid: int) -> tuple[int, int]:
    """Foydalanuvchining tarifiga ko'ra (max_chats, max_posts)."""
    return tariff_limits(await db.get_tariff(uid))


# ─────────────────────────────────────────────────────────────────────────
# MENYU
# ─────────────────────────────────────────────────────────────────────────
def kb_login() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔑 Login")]],
        resize_keyboard=True,
    )


def kb_pending() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏳ Tasdiq kutilmoqda...")]],
        resize_keyboard=True,
    )


def kb_main(interval: int, running: bool, super_admin: bool) -> ReplyKeyboardMarkup:
    on = "🟢 ON" if running else "🔴 OFF"
    rows = [
        [KeyboardButton("▶️ Start"), KeyboardButton("⛔ Stop")],
        [KeyboardButton(f"📊 Status ({on})"), KeyboardButton("💬 Chatlar")],
        [KeyboardButton("🔍 Guruhlarni skanerlash"), KeyboardButton("➖ Chat o'chir")],
        [KeyboardButton("📝 Post qo'sh"), KeyboardButton("🗑 Post o'chir")],
        [KeyboardButton(f"⏱ Interval: {interval} daq"), KeyboardButton("👥 Referal")],
    ]
    if super_admin:
        rows.append([KeyboardButton("👥 Adminlar"), KeyboardButton("🖥 Tizim")])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
    )


async def is_approved(uid: int) -> bool:
    if uid == SUPER_ADMIN:
        return True
    return await db.is_admin(uid)


async def menu_for(uid: int) -> ReplyKeyboardMarkup:
    """
    Foydalanuvchi uchun mos klaviaturani qaytaradi.

    Optimization: ilgari 5 ta DB query qilardi, hozir 1 ta `get_user`
    chaqiruvi orqali barcha kerakli ma'lumotni oladi.
    """
    user = await db.get_user(uid)
    super_flag = uid == SUPER_ADMIN
    is_admin_flag = bool(user and user.get("is_admin"))
    approved = super_flag or is_admin_flag
    pending = bool(user and user.get("pending_session")) if user else False
    awaiting = bool(user and user.get("awaiting_approval")) if user else False
    session = (user.get("session") if user else None)

    if not approved:
        if pending or awaiting:
            return kb_pending()
        return kb_login()
    if not session:
        return kb_login()

    interval = int(user.get("interval_min", MIN_INTERVAL_MIN)) if user else MIN_INTERVAL_MIN
    running = worker_manager.is_running(uid) if worker_manager else False
    return kb_main(interval, running, super_flag)


# ─────────────────────────────────────────────────────────────────────────
# LOGIN OQIMI YORDAMCHILARI
# ─────────────────────────────────────────────────────────────────────────
async def cleanup_login(uid: int) -> None:
    ctx = login_ctx.pop(uid, None)
    if ctx:
        with contextlib.suppress(Exception):
            await ctx.client.disconnect()
    user_states.pop(uid, None)


# ─────────────────────────────────────────────────────────────────────────
# NUMPAD
# ─────────────────────────────────────────────────────────────────────────
CODE_LENGTH = 5       # Telegram standart kod uzunligi
MAX_CODE_LENGTH = 6   # Ba'zi hollarda 6 raqam ham bo'ladi


def numpad_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(d, callback_data=f"np:{d}") for d in ("1", "2", "3")],
        [InlineKeyboardButton(d, callback_data=f"np:{d}") for d in ("4", "5", "6")],
        [InlineKeyboardButton(d, callback_data=f"np:{d}") for d in ("7", "8", "9")],
        [
            InlineKeyboardButton("⬅️ O'chir", callback_data="np:back"),
            InlineKeyboardButton("0", callback_data="np:0"),
            InlineKeyboardButton("✅ Tasdiq", callback_data="np:ok"),
        ],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="np:cancel")],
    ]
    return InlineKeyboardMarkup(rows)


def numpad_display(buffer: str, total: int = CODE_LENGTH) -> str:
    n = max(total, len(buffer))
    parts = [(buffer[i] if i < len(buffer) else "▪") for i in range(n)]
    return " ".join(parts)


def numpad_message(buffer: str, hint: str = "") -> str:
    base = (
        "🔑 KIRISH — TASDIQ KODI\n\n"
        "📩 Telegramdan kelgan kodni quyidagi tugmalar orqali kiriting.\n\n"
        "👉 Telegram ilovangizni oching → \"Telegram\" rasmiy chati →\n"
        "    kodni KO'RING va shu yerga tugmalar orqali kiriting.\n\n"
        f"🔢 Kod:  {numpad_display(buffer)}\n"
    )
    if hint:
        base += f"\n{hint}\n"
    base += (
        "\n💡 Sababi: agar matnda yozsangiz, Telegram kodni\n"
        "    himoya tizimi avtomatik bekor qiladi. Tugma — xavfsiz!"
    )
    return base


async def _send_numpad(uid: int, buffer: str = "", hint: str = "") -> None:
    """
    Numpad xabarini yangilaydi yoki yangi yuboradi.

    Agar mavjud numpad_msg_id bo'lsa — uni edit qiladi (yangi xabar
    yuborilmaydi). Bu tufayli foydalanuvchi eski xabarda bosa olmaydi
    va chat tartibli qoladi.
    """
    text = numpad_message(buffer, hint)
    state = user_states.get(uid, {})
    msg_id = state.get("numpad_msg_id")

    if msg_id:
        try:
            await application.bot.edit_message_text(
                chat_id=uid,
                message_id=msg_id,
                text=text,
                reply_markup=numpad_kb(),
            )
            state["ts"] = time.time()
            user_states[uid] = state
            return
        except Exception:
            # Xabar topilmadi yoki o'zgarmadi — yangi yuboramiz
            pass

    msg = await application.bot.send_message(
        uid, text, reply_markup=numpad_kb()
    )
    state["numpad_msg_id"] = msg.message_id
    state["ts"] = time.time()
    user_states[uid] = state


async def _attempt_signin(uid: int, code: str) -> None:
    ctx = login_ctx.get(uid)
    if not ctx:
        await cleanup_login(uid)
        await application.bot.send_message(
            uid,
            "❌ Login jarayoni buzildi. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
        return

    try:
        if not ctx.client.is_connected():
            await asyncio.wait_for(ctx.client.connect(), timeout=20)
        await ctx.client.sign_in(
            phone=ctx.phone, code=code, phone_code_hash=ctx.phone_code_hash
        )
        await _finalize_login_uid(uid)
        return

    except SessionPasswordNeededError:
        user_states[uid] = {"step": "password", "ts": time.time()}
        await application.bot.send_message(
            uid,
            "🔐 Hisobingizda 2FA (ikki bosqichli himoya) yoqilgan.\n\n"
            "Iltimos, 2FA parolingizni MATN ko'rinishida yuboring.\n\n"
            "✅ Parol DISK-ga saqlanmaydi.\n"
            f"❓ Yordam kerak bo'lsa: {ADMIN_CONTACT_PHONE}",
        )

    except PhoneCodeInvalidError:
        ctx.wrong_count += 1
        if ctx.wrong_count >= 5:
            await cleanup_login(uid)
            await application.bot.send_message(
                uid,
                "❌ 5 marta noto'g'ri kod kiritildi.\n"
                "Qaytadan 🔑 Login bosing.\n\n"
                f"❓ Muammo bo'lsa: {ADMIN_CONTACT_PHONE}",
                reply_markup=await menu_for(uid),
            )
            return
        state = user_states.get(uid, {})
        state["code_buffer"] = ""
        state["ts"] = time.time()
        user_states[uid] = state
        await _send_numpad(
            uid, "", hint=f"❌ Noto'g'ri kod ({ctx.wrong_count}/5). Qaytadan kiriting:"
        )

    except PhoneCodeExpiredError:
        ctx.resend_count += 1
        if ctx.resend_count > 1:
            await cleanup_login(uid)
            await application.bot.send_message(
                uid,
                "⏰ Kod muddati tugadi.\n\n"
                "Bir necha daqiqa kuting va qaytadan 🔑 Login bosing.\n"
                f"❓ Muammo: {ADMIN_CONTACT_PHONE}",
                reply_markup=await menu_for(uid),
            )
            return
        try:
            result = await asyncio.wait_for(
                ctx.client.send_code_request(ctx.phone), timeout=20
            )
            ctx.phone_code_hash = result.phone_code_hash
            ctx.wrong_count = 0
            state = user_states.get(uid, {})
            state["code_buffer"] = ""
            state["ts"] = time.time()
            user_states[uid] = state
            await _send_numpad(
                uid,
                "",
                hint=(
                    "⏰ Eski kod yaroqsiz — YANGI kod yuborildi!\n"
                    "Telegram ilovangizdan ENG SO'NGGI kodni qarang."
                ),
            )
        except FloodWaitError as e:
            await cleanup_login(uid)
            await application.bot.send_message(
                uid,
                f"⏳ Telegram juda ko'p urinishni sezdi.\n"
                f"{e.seconds} soniya kutib, qaytadan 🔑 Login bosing.",
                reply_markup=await menu_for(uid),
            )
        except Exception as e:
            log(f"❌ resend code {uid}: {type(e).__name__}: {e}", "error")
            await cleanup_login(uid)
            await application.bot.send_message(
                uid,
                "❌ Yangi kod yuborib bo'lmadi. Qaytadan 🔑 Login bosing.\n"
                f"❓ {ADMIN_CONTACT_PHONE}",
                reply_markup=await menu_for(uid),
            )

    except FloodWaitError as e:
        await cleanup_login(uid)
        await application.bot.send_message(
            uid,
            f"⏳ {e.seconds} soniya kuting va qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )

    except Exception as e:
        log(f"❌ sign_in {uid}: {type(e).__name__}: {e}", "error")
        await cleanup_login(uid)
        await application.bot.send_message(
            uid,
            f"❌ Xato: {type(e).__name__}\nQaytadan 🔑 Login bosing.\n"
            f"❓ {ADMIN_CONTACT_PHONE}",
            reply_markup=await menu_for(uid),
        )


async def _finalize_login_uid(uid: int) -> None:
    ctx = login_ctx.get(uid)
    if not ctx:
        return
    sess_str = ctx.client.session.save()
    with contextlib.suppress(Exception):
        await ctx.client.disconnect()
    login_ctx.pop(uid, None)
    user_states.pop(uid, None)

    # Ism ro'yxatdan o'tishda kiritilgan — uni saqlab qolamiz, faqat
    # username'ni (agar bor bo'lsa) yangilaymiz.
    try:
        info = await db.get_user_info(uid)
        entered_name = (info.get("name") or "").strip()
        chat = await application.bot.get_chat(uid)
        tg_name = (chat.first_name or "") + (
            f" {chat.last_name}" if chat.last_name else ""
        )
        name = entered_name or tg_name or "Noma'lum"
        username = chat.username or info.get("username", "") or ""
        await db.set_user_info(uid, name, username)
    except Exception:
        pass

    if uid == SUPER_ADMIN:
        await db.set_session(uid, sess_str)
        await db.del_pending(uid)
        await db.add_admin(uid)
        log(f"✅ Super admin login: {uid}")
        await application.bot.send_message(
            uid,
            "✅ Super admin sifatida tizimga kirdingiz!",
            reply_markup=await menu_for(uid),
        )
        return

    # YANGI OQIM: foydalanuvchi allaqachon TASDIQLANGAN (admin tasdiq bergan),
    # endi kod kiritib login qildi → sessiya darrov faollashadi.
    if await db.is_admin(uid):
        await db.set_session(uid, sess_str)
        await db.del_pending(uid)
        await db.set_awaiting_approval(uid, False)
        log(f"✅ Tasdiqlangan user login qildi: {uid}")
        with contextlib.suppress(Exception):
            info = await db.get_user_info(uid)
            name = info.get("name", "Foydalanuvchi")
            await application.bot.send_message(
                uid,
                f"✅ {name}, tizimga muvaffaqiyatli kirdingiz!\n\n"
                "Endi chat va post qo'shib, ▶️ Start bosishingiz mumkin.",
                reply_markup=await menu_for(uid),
            )
        return

    # ESKI OQIM (moslik uchun): tasdiqlanmagan — pending'ga qo'yib admin so'raymiz
    await db.set_pending(uid, sess_str)
    log(f"⏳ Tasdiq kutilmoqda: {uid}")
    await notify_super_for_approval(uid)
    await application.bot.send_message(
        uid,
        "✅ Login muvaffaqiyatli!\n\n"
        "⏳ Hisobingiz admin tasdiqlashini kutmoqda.\n\n"
        "📞 Tezroq tasdiqlanish va tarif tanlash uchun admin bilan bog'laning:\n"
        f"📱 {ADMIN_CONTACT_PHONE}\n\n"
        "Tasdiqlanganingizdan so'ng menyu avtomatik ochiladi.",
        reply_markup=await menu_for(uid),
    )


async def notify_super_for_approval(uid: int) -> None:
    info = await db.get_user_info(uid)
    name = info.get("name", "Noma'lum")
    username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
    phone = await db.get_phone(uid)
    phone_line = f"📱 Telefon: {phone}\n" if phone else ""
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 1-Start (5/10)", callback_data=f"app:t1:{uid}"),
                InlineKeyboardButton("🔵 2-Biznes (10/25)", callback_data=f"app:t2:{uid}"),
            ],
            [
                InlineKeyboardButton("🟡 3-Pro (20/50)", callback_data=f"app:t3:{uid}"),
                InlineKeyboardButton("🔴 4-Premium (50/100)", callback_data=f"app:t4:{uid}"),
            ],
            [
                InlineKeyboardButton("⛔ Rad etish", callback_data=f"app:off:{uid}"),
            ],
        ]
    )
    text = (
        "🔔 Yangi foydalanuvchi tasdiq so'ramoqda\n\n"
        f"👤 Ism: {name}\n"
        f"{phone_line}"
        f"📎 {username}\n"
        f"🆔 ID: {uid}\n\n"
        "Tarif tanlab tasdiqlang (chat/post limiti):\n"
        "• 🟢 1-Start → 5 chat / 10 post\n"
        "• 🔵 2-Biznes → 10 chat / 25 post\n"
        "• 🟡 3-Pro → 20 chat / 50 post\n"
        "• 🔴 4-Premium → 50 chat / 100 post\n\n"
        "⛔ Rad etish — so'rov bekor qilinadi."
    )
    with contextlib.suppress(Exception):
        await application.bot.send_message(SUPER_ADMIN, text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────
# POSTING WORKER
# ─────────────────────────────────────────────────────────────────────────
async def _resolve_chat(client: TelegramClient, chat: str):
    """Chat manzilini Telethon entity'ga aylantiradi.

    Private invite link foydalanuvchi akkaunti guruhga oldindan a'zo
    bo'lgan bo'lsagina qabul qilinadi; bot akkauntni o'zi guruhga qo'shmaydi.
    """
    s = chat.strip()
    if s.startswith("invite:"):
        invite_hash = s.split(":", 1)[1]
        result = await client(CheckChatInviteRequest(invite_hash))
        if isinstance(result, ChatInviteAlready):
            return result.chat
        raise ValueError("Avval Telegram akkauntingiz bilan guruhga qo'shiling")
    if s.startswith("@"):
        return await client.get_entity(s)
    if s.lstrip("-").isdigit():
        return await client.get_entity(int(s))
    if s.startswith("https://t.me/") or s.startswith("t.me/"):
        return await client.get_entity(s)
    return await client.get_entity(s)


async def _send_post(client: TelegramClient, chat: str, post: dict) -> None:
    text = post.get("text", "")
    entities = dicts_to_telethon_entities(post.get("entities", []))
    target = await _resolve_chat(client, chat)

    final_text = text

    photo_path = post.get("photo")
    if photo_path and os.path.exists(photo_path):
        await client.send_file(
            entity=target,
            file=photo_path,
            caption=final_text,
            formatting_entities=entities or None,
        )
    else:
        await client.send_message(
            entity=target,
            message=final_text,
            formatting_entities=entities or None,
            link_preview=bool(post.get("link_preview", True)),
        )


def _user_media_dir(uid: int) -> str:
    p = os.path.join(MEDIA_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    with contextlib.suppress(Exception):
        if os.path.exists(path):
            os.remove(path)


def _wipe_user_media(uid: int) -> None:
    p = os.path.join(MEDIA_DIR, str(uid))
    with contextlib.suppress(Exception):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def posting_loop(uid: int, stop: asyncio.Event) -> None:
    """Asosiy posting siklini ishlatadi (ClientPool orqali)."""
    log(f"🟢 Worker:{uid} ishga tushdi")

    # ── O'ZGARISH 1: START JITTER ──────────────────────────────────────
    # Worker birinchi marta ishga tushganda 0-START_JITTER_MAX_S oralig'ida
    # tasodifiy kutadi. Bu — ko'p worker (restart yoki bir paytda Start)
    # bir lahzada yuborishni boshlamasligi uchun. Yuk vaqtga yoyiladi,
    # CPU/tarmoq cho'qqisi (spike) yo'qoladi. Interval BUZILMAYDI — bu faqat
    # birinchi turdan oldingi bir martalik siljish.
    first_delay = random.randint(0, START_JITTER_MAX_S)
    log(f"⏳ Worker:{uid} start jitter {first_delay}s")
    if await _sleep_or_stop(stop, first_delay):
        return

    # ── O'ZGARISH 4: POST ROTATION ─────────────────────────────────────
    # random.choice o'rniga navbat (rotation): A→B→C→A. Har post teng
    # chiqadi, hech biri o'tkazib yuborilmaydi. Indeks worker xotirasida.
    post_index = 0

    # Ketma-ket xatolar bazada saqlanadi; 3 martadan so'ng chat o'chirilmaydi,
    # balki qo'lda qayta skanerlashni kutuvchi holatga o'tadi.

    try:
        while not stop.is_set():
            if await db.is_suspended(uid):
                await db.set_running(uid, False)
                log(f"⏸ Worker:{uid} admin tomonidan to'xtatilgan", "warning")
                break
            sess = await db.get_session(uid)
            if not sess:
                log(f"❌ Worker:{uid} sessiya yo'q — to'xtaydi", "warning")
                break

            chats = await db.get_active_chats(uid)
            posts = await db.get_posts(uid)
            interval = await db.get_interval(uid)

            if not chats or not posts:
                await _sleep_or_stop(stop, 30)
                continue

            try:
                client = await client_pool.acquire(uid, sess)
            except SessionInvalidError:
                # Sessiya HAQIQATAN bekor qilingan — o'chirib, login'ga yo'naltiramiz
                log(f"🚫 Worker:{uid} — sessiya bekor qilingan", "warning")
                await db.del_session(uid)
                await db.set_running(uid, False)
                await client_pool.remove(uid)
                with contextlib.suppress(Exception):
                    await application.bot.send_message(
                        uid,
                        "🚫 Sessiyangiz Telegram tomonidan bekor qilindi.\n"
                        "Qaytadan 🔑 Login qiling.",
                    )
                break
            except PoolBusyError:
                # Vaqtinchalik (pool to'la / tarmoq) — sessiyaga TEGMAYMIZ,
                # 30s kutib qayta urinadi.
                log(f"⏳ Worker:{uid} — tizim band/tarmoq, 30s kutadi", "warning")
                if await _sleep_or_stop(stop, 30):
                    break
                continue

            try:
                # O'ZGARISH 4: navbatdagi postni olamiz (rotation, random emas)
                post_index %= len(posts)
                post = posts[post_index]
                post_index += 1

                ok, fail = 0, 0
                waiting_chats: list[tuple[str, int, str]] = []
                for chat in chats:
                    if stop.is_set():
                        break
                    if await db.is_suspended(uid):
                        await db.set_running(uid, False)
                        stop.set()
                        break
                    try:
                        await asyncio.wait_for(
                            _send_post(client, chat, post), timeout=20
                        )
                        ok += 1
                        await db.record_chat_success(uid, chat)
                        log(f"✅ {uid} → {chat}")
                    except FloodWaitError as e:
                        # FloodWait — umumiy Telegram tezlik limiti; chatning
                        # ruxsati yo'qligini bildirmaydi va xato sanagichga kirmaydi.
                        wait_s = int(getattr(e, "seconds", 30)) + 5
                        log(f"⏳ {uid} → {chat} FloodWait {wait_s}s", "warning")
                        if await _sleep_or_stop(stop, wait_s):
                            break
                    except (
                        ChatWriteForbiddenError,
                        ChannelPrivateError,
                        PeerIdInvalidError,
                        UsernameNotOccupiedError,
                        UsernameInvalidError,
                        ValueError,
                    ) as e:
                        fail += 1
                        count, moved = await db.record_chat_failure(
                            uid, chat, f"{type(e).__name__}: {e}", threshold=MAX_CHAT_FAILS
                        )
                        log(
                            f"❌ {uid} → {chat}: {type(e).__name__} "
                            f"({count}/{MAX_CHAT_FAILS})",
                            "warning",
                        )
                        if moved:
                            waiting_chats.append((chat, count, type(e).__name__))
                    except asyncio.TimeoutError:
                        fail += 1
                        count, moved = await db.record_chat_failure(
                            uid, chat, "Yuborish vaqti tugadi", threshold=MAX_CHAT_FAILS
                        )
                        log(
                            f"⏱ {uid} → {chat} timeout "
                            f"({count}/{MAX_CHAT_FAILS})",
                            "warning",
                        )
                        if moved:
                            waiting_chats.append((chat, count, "Timeout"))
                    except (AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
                        log(f"🚫 {uid} sessiya yaroqsiz: {type(e).__name__}", "error")
                        await db.del_session(uid)
                        await db.set_running(uid, False)
                        await client_pool.remove(uid)
                        with contextlib.suppress(Exception):
                            await application.bot.send_message(
                                uid,
                                "🚫 Sessiyangiz bekor qilindi. Qaytadan 🔑 Login qiling.",
                            )
                        return
                    except Exception as e:
                        fail += 1
                        count, moved = await db.record_chat_failure(
                            uid, chat, f"{type(e).__name__}: {e}", threshold=MAX_CHAT_FAILS
                        )
                        log(
                            f"❌ {uid} → {chat}: {type(e).__name__}: {e} "
                            f"({count}/{MAX_CHAT_FAILS})",
                            "error",
                        )
                        if moved:
                            waiting_chats.append((chat, count, type(e).__name__))
                    if not stop.is_set():
                        await _sleep_or_stop(stop, SEND_DELAY_S)

                # Uch ketma-ket xatoda chat saqlanadi, lekin worker yuborishni
                # to'xtatib, faqat foydalanuvchining qo'lda skanerlashini kutadi.
                for waiting_chat, count, reason in waiting_chats:
                    log(f"⏳ {uid} chat kutish holatiga o'tdi: {waiting_chat}")
                    with contextlib.suppress(Exception):
                        await application.bot.send_message(
                            uid,
                            f"⚠️ {waiting_chat} guruhiga {MAX_CHAT_FAILS} marta ketma-ket "
                            "xabar yuborilmadi. Guruh o'chirilmadi — kutish holatiga o'tkazildi.\n\n"
                            "Qayta tekshirish uchun 🔍 Guruhlarni skanerlash tugmasini bosing; "
                            "yozish huquqi tiklangan bo'lsa, natijani tasdiqlang.\n"
                            f"Oxirgi xato: {reason} ({count} ta urinish).",
                        )

                log(f"📊 {uid} ✅{ok} ❌{fail} / {len(chats)}")
            finally:
                await client_pool.release(uid)

            delay = interval * 60 + random.randint(-INTERVAL_JITTER_S, INTERVAL_JITTER_S)
            delay = max(MIN_INTERVAL_MIN * 60, delay)
            log(f"⏳ {uid} keyingi tur {delay}s ({interval} daq)")
            if await _sleep_or_stop(stop, delay):
                break

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log(f"💥 Worker:{uid} kutilmagan xato: {type(e).__name__}: {e}", "error")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                SUPER_ADMIN, f"⚠️ Worker xato\nUID: {uid}\n{type(e).__name__}: {e}"
            )
    finally:
        await client_pool.release(uid)
        log(f"🔴 Worker:{uid} to'xtadi")


# ─────────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id

    if not rate_limiter.is_allowed(uid, "command"):
        wait = rate_limiter.get_wait_time(uid, "command")
        await update.message.reply_text(f"⏳ Juda ko'p so'rov. {wait} soniya kuting.")
        return

    if not is_super(uid) and await db.is_suspended(uid):
        user = await db.get_user(uid)
        until = user.get("suspended_until") if user else None
        detail = f"\nQayta faollashish: {until} UTC" if until else "\nAdmin qayta faollashtirguncha."
        await update.message.reply_text("⏸ Hisobingiz vaqtincha to'xtatilgan." + detail)
        return

    # ── REFERAL: /start ref_<uid> orqali kelganni biriktiramiz ──────────
    # Faqat hali tasdiqlanmagan (yangi) userlar uchun. Hisoblash esa
    # admin tasdiqlaganda amalga oshadi (try_count_referral).
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref_part = arg[4:]
            if ref_part.isdigit() and not await is_approved(uid):
                with contextlib.suppress(Exception):
                    await db.set_referrer(uid, int(ref_part))

    if (await db.get_pending(uid) or await db.is_awaiting_approval(uid)) and not await is_approved(uid):
        await update.message.reply_text(
            "⏳ Sizning so'rovingiz ko'rib chiqilmoqda.\nAdmin tasdiqlashini kuting.",
            reply_markup=await menu_for(uid),
        )
        return

    if await is_approved(uid) and await db.get_session(uid):
        user = await db.get_user(uid)
        name = user.get("name", "Foydalanuvchi") if user else "Foydalanuvchi"
        tariff = int(user.get("tariff", 1)) if user else 1
        max_chats, max_posts = tariff_limits(tariff)
        expires = user.get("tariff_expires_at") if user else None
        exp_line = f"📅 Muddat: {expires[:10]}" if expires else "📅 Muddat: cheksiz"
        chats_n = await db.count_chats(uid)
        active_chats_n = len(await db.get_active_chats(uid))
        waiting_chats_n = await db.count_waiting_chats(uid)
        posts_n = await db.count_posts(uid)
        interval = await db.get_interval(uid)
        active = worker_manager.is_running(uid) if worker_manager else False
        expired = await db.is_tariff_expired(uid)
        if expired:
            status = "⏸ Kutish rejimi (muddat tugagan)"
        else:
            status = "🟢 ON" if active else "🔴 OFF"
        await update.message.reply_text(
            "🤖 AVTO BOT\n\n"
            f"👤 {name}\n"
            f"🎫 {tariff_label(tariff)}\n"
            f"{exp_line}\n\n"
            f"📊 Holat: {status}\n"
            f"💬 Guruhlar: {chats_n}/{max_chats} (faol {active_chats_n}, kutishda {waiting_chats_n})\n"
            f"📝 Postlar: {posts_n}/{max_posts}\n"
            f"⏱ Interval: {interval} daqiqa",
            reply_markup=await menu_for(uid),
        )
        return

    await update.message.reply_text(
        "🤖 AVTO BOT — Telegram avto-poster\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 BOT NIMA QILADI?\n\n"
        "Bot sizning Telegram hisobingiz orqali tanlangan chatlarga\n"
        "siz tayyorlagan postlarni belgilangan vaqt oraliqlarida\n"
        "AVTOMATIK tarzda joylashtiradi.\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "👥 KIMLAR UCHUN?\n\n"
        "✅ Reklama agentliklari va SMM mutaxassislari\n"
        "✅ O'z biznesini reklama qiluvchi tadbirkorlar\n"
        "✅ Onlayn-do'kon egalari\n"
        "✅ Xizmat ko'rsatuvchilar\n"
        "✅ Telegram-kanal va guruh egalari\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💼 NIMALAR UCHUN?\n\n"
        "📢 Tovar va xizmatlaringizni reklama qilish\n"
        "📢 Aksiya va chegirmalarni e'lon qilish\n"
        "📢 Yangi mahsulot/yangiliklar haqida xabar berish\n"
        "📢 Auditoriyani kengaytirish\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ IMKONIYATLAR (TARIFLAR)\n\n"
        "• 🟢 1-Start → 5 chat / 10 post\n"
        "• 🔵 2-Biznes → 10 chat / 25 post\n"
        "• 🟡 3-Pro → 20 chat / 50 post\n"
        "• 🔴 4-Premium → 50 chat / 100 post\n"
        f"• Interval: {MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} daqiqa\n"
        "• Bold, italic, link va barcha formatlash saqlanadi\n"
        "• 24/7 ishlaydi, restart-dan keyin avtomatik tiklanadi\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📋 BOSHLASH\n\n"
        "1️⃣ '🔑 Login' tugmasini bosing\n"
        "2️⃣ Ismingizni kiriting (admin tanishi uchun)\n"
        "3️⃣ Telefon raqamingizni kiriting (+998XXXXXXXXX)\n"
        "4️⃣ Admin tasdiqlashini kuting (tarif beriladi)\n"
        "5️⃣ Tasdiqdan keyin '🔑 Login' → Telegramdan kelgan\n"
        "    kodni RAQAMLI TUGMALAR orqali kiriting\n"
        "6️⃣ 2FA bo'lsa — parolni kiriting\n\n"
        f"📱 Admin: {ADMIN_CONTACT_PHONE}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🛡 XAVFSIZLIK\n\n"
        "✅ Kod va parol HECH QAYERDA saqlanmaydi\n"
        "✅ Faqat session token saqlanadi\n"
        "✅ Ma'lumotlaringiz boshqalarga ko'rinmaydi\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📞 FOYDALANISH BO'YICHA YORDAM\n\n"
        "Ro'yxatdan o'tishda muammo, savol yoki taklif bo'lsa:\n\n"
        f"📱 {ADMIN_CONTACT_PHONE}\n\n"
        "Quyidagi 🔑 Login tugmasini bosib, ro'yxatdan o'ting!",
        reply_markup=await menu_for(uid),
    )


# ─────────────────────────────────────────────────────────────────────────
# CALLBACK
# ─────────────────────────────────────────────────────────────────────────
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""
    if data.startswith("gscan:info:"):
        if not is_super(uid) and await db.is_suspended(uid):
            await q.answer("Hisobingiz vaqtincha to'xtatilgan.", show_alert=True)
            return
        state = user_states.get(uid, {})
        if state.get("step") != "group_scan_review":
            await q.answer("Skanerlash holati topilmadi. Qaytadan skanerlang.", show_alert=True)
            return
        if time.time() - state.get("ts", 0) > GROUP_SCAN_STATE_TTL_S:
            user_states.pop(uid, None)
            await q.answer("Skanerlash natijasi eskirdi. Qayta skanerlang.", show_alert=True)
            return
        groups = state.get("groups", [])
        try:
            index = int(data.rsplit(":", 1)[1])
            if not 0 <= index < len(groups):
                raise IndexError
            group = groups[index]
        except (ValueError, IndexError):
            await q.answer("Guruh ma'lumoti topilmadi.", show_alert=True)
            return
        title = str(group.get("title") or group.get("chat_id") or "Guruh")
        if group.get("writable") is True:
            permission = "✅ Yozish mumkin"
        elif group.get("writable") is False:
            permission = "⛔ Yozish huquqi yo'q"
        else:
            permission = "❔ Yozish huquqi aniqlanmadi"
        existing = group.get("existing_status")
        status = {
            "active": "🟢 Allaqachon faol",
            "waiting": "⏳ Kutish holatida",
        }.get(existing, "🆕 Yangi guruh")
        selected = "Tanlangan" if index in state.get("selected", set()) else "Tanlanmagan"
        details = f"{title[:100]}\n{permission} · {status}\n{selected}. O'ngdagi tugma bilan tanlang."
        await q.answer(details[:200], show_alert=True)
        return
    await q.answer()

    if not is_super(uid) and await db.is_suspended(uid):
        user = await db.get_user(uid)
        until = user.get("suspended_until") if user else None
        detail = f"\nQayta faollashish: {until} UTC" if until else "\nAdmin qayta faollashtirguncha."
        with contextlib.suppress(Exception):
            await q.edit_message_text("⏸ Hisobingiz vaqtincha to'xtatilgan." + detail)
        return

    if data.startswith("gscan:"):
        state = user_states.get(uid, {})
        if state.get("step") != "group_scan_review":
            with contextlib.suppress(Exception):
                await q.edit_message_text("⚠️ Skanerlash holati topilmadi. Qaytadan qo'lda skanerlang.")
            return
        if time.time() - state.get("ts", 0) > GROUP_SCAN_STATE_TTL_S:
            user_states.pop(uid, None)
            with contextlib.suppress(Exception):
                await q.edit_message_text("⏰ Skanerlash natijasi eskirdi. Qayta tekshirish uchun tugmani bosing.")
            return

        action = data.split(":", 1)[1]
        if action == "cancel":
            user_states.pop(uid, None)
            await q.edit_message_text("❌ Skanerlash natijasi bekor qilindi. Hech bir guruh o'zgartirilmadi.")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
                )
            return
        if action == "confirm":
            await _confirm_group_scan(uid, q)
            return
        if action == "select:writable":
            state["selected"] = {
                index for index, group in enumerate(state.get("groups", []))
                if group.get("writable") is True and group.get("existing_status") != "active"
            }
        elif action.startswith("toggle:"):
            try:
                index = int(action.split(":", 1)[1])
            except ValueError:
                return
            groups = state.get("groups", [])
            if not (0 <= index < len(groups)) or groups[index].get("existing_status") == "active":
                return
            selected = set(state.get("selected", set()))
            if index in selected:
                selected.remove(index)
            else:
                selected.add(index)
            state["selected"] = selected
        elif action.startswith("page:"):
            try:
                state["page"] = max(0, int(action.split(":", 1)[1]))
            except ValueError:
                return
        else:
            return
        user_states[uid] = state
        text, markup = await _build_group_scan_message(uid)
        await q.edit_message_text(text, reply_markup=markup)
        return

    # NUMPAD
    if data.startswith("np:"):
        state = user_states.get(uid, {})
        if state.get("step") != "code":
            with contextlib.suppress(Exception):
                await q.edit_message_text("⚠️ Login jarayonida emassiz.")
            return

        if time.time() - state.get("ts", 0) > LOGIN_TIMEOUT_S:
            await cleanup_login(uid)
            with contextlib.suppress(Exception):
                await q.edit_message_text(
                    f"⏰ Vaqt tugadi ({LOGIN_TIMEOUT_S // 60} daqiqa).\n"
                    "Qaytadan 🔑 Login bosing."
                )
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
            return

        action = data.split(":", 1)[1]
        buffer = state.get("code_buffer", "")

        if action == "cancel":
            await cleanup_login(uid)
            with contextlib.suppress(Exception):
                await q.edit_message_text("❌ Login bekor qilindi.")
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
            return

        if action == "back":
            buffer = buffer[:-1]

        elif action == "ok":
            if len(buffer) < CODE_LENGTH:
                await q.answer(
                    f"Kamida {CODE_LENGTH} ta raqam kiriting!", show_alert=True
                )
                return
            with contextlib.suppress(Exception):
                await q.edit_message_text(
                    f"⏳ Kod tekshirilmoqda...\n\n🔢 {numpad_display(buffer)}"
                )
            await _attempt_signin(uid, buffer)
            return

        else:
            if not action.isdigit():
                return
            if len(buffer) >= MAX_CODE_LENGTH:
                await q.answer(
                    f"Maksimal {MAX_CODE_LENGTH} ta raqam!", show_alert=True
                )
                return
            buffer += action

        state["code_buffer"] = buffer
        state["ts"] = time.time()
        user_states[uid] = state
        with contextlib.suppress(Exception):
            await q.edit_message_text(
                numpad_message(buffer), reply_markup=numpad_kb()
            )
        return

    # Yangi user tasdiqlash — tarif bilan (app:t1..t4:uid) yoki rad (app:off:uid)
    if data.startswith("app:t") or data.startswith("app:off:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        action = parts[1]  # "t1" | "t2" | "t3" | "t4" | "off"
        target = int(parts[2])
        sess = await db.get_pending(target)
        if action in ("t1", "t2", "t3", "t4"):
            # Yangi oqim: tasdiqda sessiya BO'LMAYDI (kod hali so'ralmagan).
            # Admin tasdiqlaydi → user keyin 🔑 Login bosib kod kiritadi.
            awaiting = await db.is_awaiting_approval(target)
            if not sess and not awaiting:
                await q.edit_message_text(f"⚠️ {target} so'rovi topilmadi.")
                return
            tariff = int(action[1])  # t1->1 ... t4->4
            await db.add_admin(target)
            approval_expiry = calc_expiry()
            await db.set_tariff_and_expiry(target, tariff, approval_expiry)
            await db.set_awaiting_approval(target, False)
            await db.record_admin_action(
                uid, target, "approve_user",
                f"tariff={tariff}; expires={approval_expiry}",
            )
            # Eski oqim bilan moslik: agar pending sessiya bo'lsa, uni faollashtiraman
            if sess:
                await db.set_session(target, sess)
                await db.del_pending(target)
            log(f"✅ Tasdiqlandi: {target} ({tariff_label(tariff)}, {TARIFF_DURATION_DAYS} kun)")
            await q.edit_message_text(
                f"✅ Tasdiqlandi: {target}\n🎫 {tariff_label(tariff)}"
            )
            with contextlib.suppress(Exception):
                info = await db.get_user_info(target)
                name = info.get("name", "Foydalanuvchi")
                tmc, tmp = tariff_limits(tariff)
                if sess:
                    # Eski oqim — sessiya allaqachon bor, to'g'ridan-to'g'ri ishlaydi
                    await application.bot.send_message(
                        target,
                        f"✅ {name}, hisobingiz tasdiqlandi!\n\n"
                        f"🎫 Sizning tarifingiz: {tariff_label(tariff)}\n"
                        f"📅 Muddat: {TARIFF_DURATION_DAYS} kun\n\n"
                        "Endi:\n"
                        f"1️⃣ 🔍 Guruhlarni skanerlang va keraklilarini tasdiqlang (max {tmc})\n"
                        f"2️⃣ 📝 Post qo'shing (max {tmp})\n"
                        "3️⃣ ⏱ Interval sozlang\n"
                        "4️⃣ ▶️ Start bosing",
                        reply_markup=await menu_for(target),
                    )
                else:
                    # Yangi oqim — user endi Login bosib kodni kiritishi kerak
                    await application.bot.send_message(
                        target,
                        f"✅ {name}, hisobingiz tasdiqlandi!\n\n"
                        f"🎫 Sizning tarifingiz: {tariff_label(tariff)}\n"
                        f"📅 Muddat: {TARIFF_DURATION_DAYS} kun\n\n"
                        "🔑 Endi \"🔑 Login\" tugmasini bosing.\n"
                        "Telegramdan kod keladi — uni kiritsangiz, tayyor!",
                        reply_markup=await menu_for(target),
                    )
            # ── REFERAL HISOBLASH ───────────────────────────────────────
            # Tasdiqlangan user kimdir tomonidan taklif qilingan bo'lsa —
            # BIR MARTA hisoblaymiz va taklif qilganga xabar beramiz.
            with contextlib.suppress(Exception):
                referrer = await db.try_count_referral(target)
                if referrer:
                    total = await db.count_referrals(referrer)
                    rinfo = await db.get_user_info(target)
                    rname = rinfo.get("name", "Yangi foydalanuvchi")
                    await application.bot.send_message(
                        referrer,
                        f"🎉 Sizning referalingiz faollashdi!\n\n"
                        f"👤 {rname} ro'yxatdan o'tib, tasdiqlandi.\n"
                        f"👥 Jami faol referallaringiz: {total} ta",
                    )
        else:  # off — rad etish
            # Pending bekor qilinadi. session bu yerda yo'q (faqat pending),
            # shu sababli del_session chaqirilmaydi.
            await db.del_pending(target)
            await db.set_awaiting_approval(target, False)
            await db.record_admin_action(uid, target, "reject_user", "approval request rejected")
            log(f"❌ Rad etildi: {target}")
            await q.edit_message_text(f"⛔ Rad etildi: {target}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    target,
                    "❌ Sizning so'rovingiz rad etildi.\n\n"
                    f"📞 Savollar uchun admin bilan bog'laning: {ADMIN_CONTACT_PHONE}\n"
                    "Qayta urinib ko'rishingiz mumkin.",
                    reply_markup=await menu_for(target),
                )
        return

    if data == "rmadm:cancel":
        if not is_super(uid):
            return
        await q.edit_message_text("❌ Bekor qilindi. Foydalanuvchi va ma'lumotlari saqlab qolindi.")
        return

    if data.startswith("rmadm:confirm:"):
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        user = await db.get_user(target)
        if target == SUPER_ADMIN or not user or not user.get("is_admin"):
            await q.edit_message_text("❌ Foydalanuvchi topilmadi yoki o'chirish mumkin emas.")
            return
        if worker_manager:
            await worker_manager.stop_worker(target)
        await db.record_admin_action(
            uid, target, "user_removed", "user record and data deleted by confirmed admin action"
        )
        if client_pool:
            await client_pool.remove(target)
        await db.delete_user(target)
        _wipe_user_media(target)
        log(f"🗑 Admin o'chirildi: {target}")
        await q.edit_message_text(f"🗑 Foydalanuvchi butunlay o'chirildi: {target}")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                target,
                "❌ Hisobingiz va botdagi ma'lumotlaringiz admin tomonidan o'chirildi.",
            )
        return

    if data.startswith("rmadm:"):
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        user = await db.get_user(target)
        if target == SUPER_ADMIN or not user or not user.get("is_admin"):
            await q.edit_message_text("❌ Bu foydalanuvchini o'chirib bo'lmaydi.")
            return
        info = await db.get_user_info(target)
        name = _admin_display_name(info.get("name"))
        await q.edit_message_text(
            f"⚠️ {name} ({target}) foydalanuvchisini butunlay o'chirmoqchimisiz?\n\n"
            "Bu amal sessiya, chatlar, postlar va saqlangan fayllarni o'chiradi. "
            "Keyin tiklab bo'lmaydi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 Ha, butunlay o'chirish", callback_data=f"rmadm:confirm:{target}"),
                    InlineKeyboardButton("❌ Bekor", callback_data="rmadm:cancel"),
                ]
            ]),
        )
        return

    if data == "stop:yes":
        if worker_manager:
            await worker_manager.stop_worker(uid)
        await db.set_running(uid, False)
        await q.edit_message_text("⛔ Posting to'xtatildi.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
        return
    if data == "stop:no":
        await q.edit_message_text("✅ Posting davom etmoqda.")
        return

    # Start tasdiq
    if data == "go:no":
        await q.edit_message_text("❌ Bekor qilindi.")
        return
    if data == "go:yes":
        async with _user_control_lock(uid):
            # Recheck under the same lock used by admin suspension: an older
            # confirmation must not start posting after the account is paused.
            if await db.is_suspended(uid):
                user = await db.get_user(uid)
                until = user.get("suspended_until") if user else None
                detail = f"\nQayta faollashish: {until} UTC" if until else "\nAdmin qayta faollashtirguncha."
                await q.edit_message_text("⏸ Hisobingiz vaqtincha to'xtatilgan." + detail)
                return
            if worker_manager and worker_manager.is_running(uid):
                await q.edit_message_text("⚠️ Allaqachon ishlamoqda.")
                return
            if await db.is_tariff_expired(uid):
                await q.edit_message_text(_waiting_mode_text())
                return
            chats = await db.get_active_chats(uid)
            posts = await db.get_posts(uid)
            if not posts:
                await q.edit_message_text("❌ Avval 📝 Post qo'shing.")
                return
            if not chats:
                waiting = await db.count_waiting_chats(uid)
                if waiting:
                    await q.edit_message_text(
                        "⏳ Hozir yuborish mumkin bo'lgan faol guruh yo'q. "
                        "Huquqlarni qayta tekshirish uchun 🔍 Guruhlarni skanerlashni bosing."
                    )
                else:
                    await q.edit_message_text(
                        "❌ Avval 🔍 Guruhlarni skanerlang va kerakli guruhlarni tasdiqlang."
                    )
                return
            started = await worker_manager.start_worker(uid) if worker_manager else False
            if not started:
                await q.edit_message_text(
                    "⚠️ Hozir tizim band. Bir oz kuting va qaytadan urinib ko'ring."
                )
                return
            await db.set_running(uid, True)
            interval = await db.get_interval(uid)
            log(f"▶️ Start: {uid}")
        await q.edit_message_text(
            f"✅ Posting boshlandi!\n"
            f"💬 {len(chats)} ta chat\n"
            f"📝 {len(posts)} ta post\n"
            f"⏱ Har {interval} daqiqada"
        )
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
        return

    if data == "clr:yes":
        old = await db.clear_posts(uid)
        for p in old:
            _safe_unlink(p.get("photo"))
        log(f"🧹 Postlar tozalandi: {uid}")
        await q.edit_message_text("🧹 Barcha postlar tozalandi.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
        return
    if data == "clr:no":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    if data == "out:yes":
        if worker_manager:
            await worker_manager.stop_worker(uid)
        await client_pool.remove(uid)
        await db.del_session(uid)
        await db.set_running(uid, False)
        user_states.pop(uid, None)
        log(f"🚪 Logout: {uid}")
        await q.edit_message_text("🚪 Tizimdan chiqdingiz.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                "Qaytadan kirish uchun 🔑 Login bosing.",
                reply_markup=await menu_for(uid),
            )
        return
    if data == "out:no":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    if data == "delp:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return
    if data.startswith("delp:"):
        try:
            i = int(data.split(":")[1])
        except Exception:
            return
        removed = await db.remove_post(uid, i)
        if removed:
            _safe_unlink(removed.get("photo"))
            preview = (removed.get("text") or "(faqat rasm)")[:80]
            log(f"🗑 Post {i+1} o'chirildi: {uid}")
            await q.edit_message_text(f"🗑 O'chirildi:\n{preview}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
                )
        else:
            await q.edit_message_text("❌ Post topilmadi.")
        return

    # Post tahrirlash — postni tanlash
    if data == "editp:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return
    if data.startswith("editp:"):
        try:
            i = int(data.split(":")[1])
        except Exception:
            return
        posts = await db.get_posts(uid)
        if not (0 <= i < len(posts)):
            await q.edit_message_text("❌ Post topilmadi.")
            return
        target_post = posts[i]
        user_states[uid] = {
            "step": "edit_post",
            "ts": time.time(),
            "edit_post_id": target_post["id"],
            "edit_old_photo": target_post.get("photo"),
        }
        preview = (target_post.get("text") or "(faqat rasm)")[:80]
        await q.edit_message_text(f"✏️ Tanlandi:\n{preview}")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                "✍️ Yangi mazmunni yuboring (matn, rasm yoki rasm+matn).\n\n"
                "⚠️ Eski post yangi mazmun bilan TO'LIQ almashtiriladi.",
            )
        return

    if data == "delc:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return
    if data.startswith("delc:"):
        try:
            i = int(data.split(":")[1])
        except Exception:
            return
        removed = await db.remove_chat(uid, i)
        if removed:
            log(f"🗑 Chat {removed} o'chirildi: {uid}")
            await q.edit_message_text(f"🗑 O'chirildi: {removed}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
                )
        else:
            await q.edit_message_text("❌ Chat topilmadi.")
        return

    if data == "adm:list" or data.startswith("adm:list:page:") or data.startswith("adm:list:filter:"):
        if not is_super(uid):
            return
        segment = "all"
        offset = 0
        if data.startswith("adm:list:filter:"):
            segment = data.rsplit(":", 1)[1]
            if segment not in {"all", "active", "expired"}:
                return
        elif data.startswith("adm:list:page:"):
            parts = data.split(":")
            try:
                if len(parts) == 5:
                    segment = parts[3]
                    offset = max(0, int(parts[4]))
                    if segment not in {"all", "active", "expired"}:
                        return
                else:  # old callback format: adm:list:page:<offset>
                    offset = max(0, int(parts[3]))
            except (ValueError, IndexError):
                return
        text, markup = await format_admin_list(offset, segment)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data == "adm:daily":
        if not is_super(uid):
            return
        user_states.pop(uid, None)
        text, markup = await _build_daily_message_settings()
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data in {"adm:daily:start", "adm:daily:stop"}:
        if not is_super(uid):
            return
        enabled = data == "adm:daily:start"
        await db.set_daily_messages_enabled(enabled)
        await db.record_admin_action(
            uid, None, "daily_messages_started" if enabled else "daily_messages_stopped",
            "scheduled messages enabled" if enabled else "scheduled messages paused",
        )
        text, markup = await _build_daily_message_settings()
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data == "adm:daily:save":
        if not is_super(uid):
            return
        state = user_states.get(uid, {})
        if state.get("step") != "admin_daily_message_confirm" or time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
            user_states.pop(uid, None)
            await q.edit_message_text("⚠️ Saqlash holati topilmadi yoki vaqti o'tdi. Qaytadan boshlang.")
            return
        segment = state.get("segment")
        message_text = state.get("text", "")
        if segment not in {"active", "expired"} or not message_text:
            user_states.pop(uid, None)
            await q.edit_message_text("❌ Xabar ma'lumoti noto'g'ri. Qaytadan kiriting.")
            return
        await db.set_daily_message_text(segment, message_text)
        await db.record_admin_action(
            uid, None, "daily_message_updated", f"segment={segment}; chars={len(message_text)}"
        )
        user_states.pop(uid, None)
        text, markup = await _build_daily_message_settings()
        await q.edit_message_text("✅ Kunlik xabar saqlandi.\n\n" + text, reply_markup=markup)
        return

    if data.startswith("adm:daily:edit:"):
        if not is_super(uid):
            return
        segment = data.rsplit(":", 1)[1]
        if segment == "cancel":
            user_states.pop(uid, None)
            text, markup = await _build_daily_message_settings()
            await q.edit_message_text(text, reply_markup=markup)
            return
        if segment not in {"active", "expired"}:
            return
        config = await db.get_daily_message_config()
        current_text = config.get(f"{segment}_text", "")
        label = "faol tarif" if segment == "active" else "muddati tugagan"
        user_states[uid] = {
            "step": f"admin_daily_message_{segment}",
            "segment": segment,
            "ts": time.time(),
        }
        hint = (
            "\n\nFaol xabarda {referral_link} yozing; yozilmasa shaxsiy havola avtomatik qo'shiladi."
            if segment == "active"
            else "\n\nAdmin telefoni uchun {admin_phone} yozishingiz mumkin."
        )
        await q.edit_message_text(
            f"✏️ {label} foydalanuvchilar uchun kunlik matnni yuboring "
            f"({MAX_ADMIN_MESSAGE_LENGTH} belgigacha).\n"
            f"Hozirgi matn:\n\n{current_text}{hint}\n\n"
            "Bekor qilish: /cancel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Bekor", callback_data="adm:daily:edit:cancel")]
            ]),
        )
        return

    # Oldingi bir martalik broadcast menyusi yangilanishdan keyin yaroqsiz.
    if data == "adm:broadcast" or data.startswith("adm:broadcast:"):
        if is_super(uid):
            await q.edit_message_text(
                "📅 Bir martalik umumiy xabar bo'limi kunlik xabarlar bilan almashtirildi.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Kunlik xabarlar", callback_data="adm:daily")]
                ]),
            )
        return

    if data in ("adm:users", "adm:tariff"):
        if not is_super(uid):
            return
        text, markup = await _build_user_list(0)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("adm:users:filter:"):
        if not is_super(uid):
            return
        segment = data.rsplit(":", 1)[1]
        if segment not in {"all", "active", "expired"}:
            return
        text, markup = await _build_user_list(0, segment)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("adm:users:page:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        try:
            if len(parts) == 5:
                segment = parts[3]
                offset = max(0, int(parts[4]))
                if segment not in {"all", "active", "expired"}:
                    return
            else:  # old callback format: adm:users:page:<offset>
                segment = "all"
                offset = max(0, int(parts[3]))
        except (ValueError, IndexError):
            return
        text, markup = await _build_user_list(offset, segment)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data == "adm:users:back":
        if not is_super(uid):
            return
        text, markup = await _build_user_list(0)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("adm:refs:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        try:
            if len(parts) != 5 or parts[3] != "page":
                return
            target = int(parts[2])
            offset = max(0, int(parts[4]))
        except ValueError:
            return
        text, markup = await _build_admin_referrals(target, offset)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("adm:ucard:"):
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        text, markup = await _build_user_card(target)
        await q.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("adm:suspend:") and data not in {"adm:suspend:confirm", "adm:suspend:cancel"}:
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        if target == SUPER_ADMIN or not await db.get_user(target):
            await q.edit_message_text("❌ Bu foydalanuvchini to'xtatib bo'lmaydi.")
            return
        user_states[uid] = {
            "step": "admin_suspend_days",
            "target": target,
            "ts": time.time(),
        }
        await q.edit_message_text(
            f"⏸ {target} uchun to'xtatish muddatini kun bilan kiriting.\n"
            "1–3650 = shu kunlarga to'xtatish, 0 = admin qo'lda yoqmaguncha.\n"
            "Bekor qilish: /cancel"
        )
        return

    if data == "adm:suspend:cancel":
        if not is_super(uid):
            return
        user_states.pop(uid, None)
        await q.edit_message_text("❌ To'xtatish bekor qilindi.")
        return

    if data == "adm:suspend:confirm":
        if not is_super(uid):
            return
        state = user_states.get(uid, {})
        if state.get("step") != "admin_suspend_confirm" or time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
            user_states.pop(uid, None)
            await q.edit_message_text("⚠️ Tasdiqlash vaqti o'tgan. Qaytadan boshlang.")
            return
        target = int(state["target"])
        days = int(state["days"])
        until = calc_expiry(days) if days > 0 else None
        if target == SUPER_ADMIN or not await db.get_user(target):
            user_states.pop(uid, None)
            await q.edit_message_text("❌ Foydalanuvchi topilmadi yoki bu amal mumkin emas.")
            return
        async with _user_control_lock(target):
            await db.set_user_suspended(target, suspended_until=until)
            if target in login_ctx:
                await cleanup_login(target)
            if worker_manager:
                await worker_manager.stop_worker(target)
            await db.set_running(target, False)
        await db.record_admin_action(
            uid, target, "suspend", f"days={days}; until={until or 'manual'}"
        )
        user_states.pop(uid, None)
        log(f"⏸ Admin {uid} foydalanuvchini to'xtatdi: {target}, days={days}")
        until_line = f"\n⏰ Tugash vaqti: {until} UTC" if until else "\nMuddat: qo'lda faollashtirilguncha"
        await q.edit_message_text(f"✅ {target} vaqtincha to'xtatildi.{until_line}")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                target,
                "⏸ Hisobingiz admin tomonidan vaqtincha to'xtatildi."
                + until_line
                + "\nSavollar uchun admin bilan bog'laning.",
            )
        return

    if data.startswith("adm:resume:") and data not in {"adm:resume:yes", "adm:resume:no"}:
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        if target == SUPER_ADMIN or not await db.get_user(target):
            await q.edit_message_text("❌ Bu foydalanuvchini faollashtirib bo'lmaydi.")
            return
        user_states[uid] = {
            "step": "admin_resume_confirm",
            "target": target,
            "ts": time.time(),
        }
        await q.edit_message_text(
            f"▶️ {target} hisobini qayta faollashtirasizmi? Posting o'z-o'zidan boshlanmaydi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Faollashtirish", callback_data="adm:resume:yes"),
                    InlineKeyboardButton("❌ Bekor", callback_data="adm:resume:no"),
                ]
            ]),
        )
        return

    if data == "adm:resume:no":
        if not is_super(uid):
            return
        user_states.pop(uid, None)
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    if data == "adm:resume:yes":
        if not is_super(uid):
            return
        state = user_states.get(uid, {})
        if state.get("step") != "admin_resume_confirm" or time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
            user_states.pop(uid, None)
            await q.edit_message_text("⚠️ Tasdiqlash vaqti o'tgan. Qaytadan boshlang.")
            return
        target = int(state["target"])
        if target == SUPER_ADMIN or not await db.get_user(target):
            user_states.pop(uid, None)
            await q.edit_message_text("❌ Foydalanuvchi topilmadi.")
            return
        async with _user_control_lock(target):
            await db.resume_user(target)
            await db.record_admin_action(uid, target, "resume", "posting remains stopped")
        user_states.pop(uid, None)
        log(f"▶️ Admin {uid} foydalanuvchini faollashtirdi: {target}")
        await q.edit_message_text(f"✅ {target} qayta faollashtirildi. Posting avtomatik boshlanmadi.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                target,
                "✅ Hisobingiz qayta faollashtirildi. Postingni davom ettirish uchun ▶️ Start bosing.",
                reply_markup=await menu_for(target),
            )
        return

    if data.startswith("adm:plan:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        try:
            target = int(parts[2])
        except (ValueError, IndexError):
            return
        if target == SUPER_ADMIN or not await db.get_user(target):
            await q.edit_message_text("❌ Tarifni o'zgartirib bo'lmaydi.")
            return
        if len(parts) == 3:
            info = await db.get_user_info(target)
            name = info.get("name") or str(target)
            cur_t = await db.get_tariff(target)
            rows = [
                [
                    InlineKeyboardButton("🟢 1-Start (5/10)", callback_data=f"adm:plan:{target}:1"),
                    InlineKeyboardButton("🔵 2-Biznes (10/25)", callback_data=f"adm:plan:{target}:2"),
                ],
                [
                    InlineKeyboardButton("🟡 3-Pro (20/50)", callback_data=f"adm:plan:{target}:3"),
                    InlineKeyboardButton("🔴 4-Premium (50/100)", callback_data=f"adm:plan:{target}:4"),
                ],
                [InlineKeyboardButton("❌ Bekor", callback_data="adm:term:cancel")],
            ]
            await q.edit_message_text(
                f"🎫 {name} — hozirgi tarif: {cur_t}. Yangi tarifni tanlang:",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return
        try:
            tariff = int(parts[3])
        except (ValueError, IndexError):
            return
        if tariff not in TARIFFS:
            await q.edit_message_text("❌ Noto'g'ri tarif.")
            return
        user_states[uid] = {
            "step": "admin_term_days",
            "target": target,
            "tariff": tariff,
            "ts": time.time(),
        }
        await q.edit_message_text(
            f"🎫 {target} uchun {tariff_label(tariff)} tanlandi.\n"
            f"Yangi muddatni kun bilan kiriting (1–{MAX_ADMIN_TERM_DAYS}).\n"
            "Eski muddat qo'shilmaydi — yangi sana bugundan hisoblanadi.\n"
            "Bekor qilish: /cancel"
        )
        return

    # Old admin paneldan qolgan inline tugmalar ham custom muddat oqimiga o'tadi.
    if data == "tariff:cancel":
        user_states.pop(uid, None)
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    if data.startswith("tariff:") or data.startswith("settar:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        try:
            target = int(parts[1])
        except (ValueError, IndexError):
            return
        if data.startswith("tariff:"):
            if target == SUPER_ADMIN or not await db.get_user(target):
                await q.edit_message_text("❌ Foydalanuvchi topilmadi.")
                return
            cur_t = await db.get_tariff(target)
            rows = [
                [
                    InlineKeyboardButton("🟢 Start", callback_data=f"adm:plan:{target}:1"),
                    InlineKeyboardButton("🔵 Biznes", callback_data=f"adm:plan:{target}:2"),
                ],
                [
                    InlineKeyboardButton("🟡 Pro", callback_data=f"adm:plan:{target}:3"),
                    InlineKeyboardButton("🔴 Premium", callback_data=f"adm:plan:{target}:4"),
                ],
                [InlineKeyboardButton("❌ Bekor", callback_data="adm:term:cancel")],
            ]
            await q.edit_message_text(
                f"🎫 Foydalanuvchi {target}, hozirgi tarif: {cur_t}.\nYangi tarifni tanlang:",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return
        try:
            tariff = int(parts[2])
        except (ValueError, IndexError):
            return
        if target == SUPER_ADMIN or tariff not in TARIFFS or not await db.get_user(target):
            await q.edit_message_text("❌ Tarif tanlovi yaroqsiz.")
            return
        user_states[uid] = {
            "step": "admin_term_days",
            "target": target,
            "tariff": tariff,
            "ts": time.time(),
        }
        await q.edit_message_text(
            f"🎫 {target} uchun {tariff_label(tariff)} tanlandi.\n"
            f"Yangi muddatni kun bilan kiriting (1–{MAX_ADMIN_TERM_DAYS}).\n"
            "Oldingi muddat almashtiriladi, ustiga qo'shilmaydi."
        )
        return

    if data == "adm:term:cancel":
        if not is_super(uid):
            return
        user_states.pop(uid, None)
        await q.edit_message_text("❌ Tarif/muddat o'zgartirish bekor qilindi.")
        return

    if data == "adm:term:confirm":
        if not is_super(uid):
            return
        state = user_states.get(uid, {})
        if state.get("step") != "admin_term_confirm" or time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
            user_states.pop(uid, None)
            await q.edit_message_text("⚠️ Tasdiqlash vaqti o'tgan. Qaytadan boshlang.")
            return
        target = int(state["target"])
        tariff = int(state["tariff"])
        days = int(state["days"])
        expires = state["expires_at"]
        if target == SUPER_ADMIN or not await db.get_user(target):
            user_states.pop(uid, None)
            await q.edit_message_text("❌ Foydalanuvchi topilmadi.")
            return
        old_expiry = await db.get_tariff_expires(target)
        # One atomic update replaces the old date (no stacking) and resets warnings.
        await db.set_tariff_and_expiry(target, tariff, expires)
        await db.record_admin_action(
            uid, target, "set_tariff_term",
            f"tariff={tariff}; days={days}; old={old_expiry or 'none'}; new={expires}",
        )
        user_states.pop(uid, None)
        log(f"🎫 Admin {uid}: {target} → tariff={tariff}, {days} kun, expires={expires}")
        await q.edit_message_text(
            f"✅ {target} uchun tarif yangilandi: {tariff_label(tariff)}\n"
            f"📅 Yangi tugash: {expires} UTC\n"
            "Eski muddat almashtirildi; qolgan kunlar qo'shilmadi."
        )
        with contextlib.suppress(Exception):
            max_chats, max_posts = tariff_limits(tariff)
            await application.bot.send_message(
                target,
                f"🎫 Tarifingiz yangilandi: {tariff_label(tariff)}\n"
                f"📅 Yangi muddat: {days} kun (tugash: {expires} UTC).\n"
                f"Endi {max_chats} ta chat va {max_posts} ta post qo'sha olasiz.",
                reply_markup=await menu_for(target),
            )
        return

    if data.startswith("adm:dm:") and data not in {"adm:dm:cancel", "adm:dm:send"}:
        if not is_super(uid):
            return
        try:
            target = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        if not await db.get_user(target):
            await q.edit_message_text("❌ Foydalanuvchi topilmadi.")
            return
        user_states[uid] = {
            "step": "admin_dm_text",
            "target": target,
            "ts": time.time(),
        }
        await q.edit_message_text(
            f"✉️ {target} ga yuboriladigan matnni kiriting ({MAX_ADMIN_MESSAGE_LENGTH} belgigacha).\n"
            "Bekor qilish: /cancel"
        )
        return

    if data == "adm:dm:cancel":
        if not is_super(uid):
            return
        user_states.pop(uid, None)
        await q.edit_message_text("❌ Xabar yuborish bekor qilindi.")
        return

    if data == "adm:dm:send":
        if not is_super(uid):
            return
        state = user_states.get(uid, {})
        if state.get("step") != "admin_dm_confirm" or time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
            user_states.pop(uid, None)
            await q.edit_message_text("⚠️ Xabar yuborish holati topilmadi yoki vaqti o'tdi. Qaytadan boshlang.")
            return
        target = int(state["target"])
        text = state["text"]
        try:
            await application.bot.send_message(target, text)
            result = "✅ Xabar yuborildi."
            action = "direct_message_sent"
        except Exception as e:
            result = "❌ Xabar yuborilmadi (foydalanuvchi botni bloklagan yoki xatolik)."
            action = "direct_message_failed"
            log(f"⚠️ Admin xabari yetmadi {target}: {type(e).__name__}", "warning")
        await db.record_admin_action(uid, target, action, f"chars={len(text)}")
        user_states.pop(uid, None)
        await q.edit_message_text(result)
        return

    if data == "adm:remove":
        if not is_super(uid):
            return
        admins = await db.get_admins()
        admins = [a for a in admins if a != SUPER_ADMIN]
        if not admins:
            await q.edit_message_text("❌ O'chirish uchun admin yo'q.")
            return
        rows = []
        for a in admins:
            info = await db.get_user_info(a)
            name = info.get("name", str(a))
            rows.append([InlineKeyboardButton(f"🗑 {name} ({a})", callback_data=f"rmadm:{a}")])
        rows.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="rmadm:cancel")])
        await q.edit_message_text(
            "➖ O'chirish uchun adminni tanlang:", reply_markup=InlineKeyboardMarkup(rows)
        )
        return



def _admin_display_name(value: str | None) -> str:
    """Normalize legacy names and mark records that only contain a Login label."""
    name = " ".join((value or "").split())
    if not name or name.casefold() in {"login", "🔑 login"}:
        return "Ism/familiya kiritilmagan"
    return name


def _admin_phone(phone: str | None) -> str:
    return " ".join((phone or "").split()) or "telefon yo'q"


def admin_panel_kb(
    offset: int = 0, total: int = 0, segment: str = "all"
) -> InlineKeyboardMarkup:
    filter_buttons = [
        InlineKeyboardButton(
            ("✅ " if segment == "all" else "") + "Barchasi",
            callback_data="adm:list:filter:all",
        ),
        InlineKeyboardButton(
            ("🟢 " if segment == "active" else "") + "Muddat bor",
            callback_data="adm:list:filter:active",
        ),
        InlineKeyboardButton(
            ("⌛ " if segment == "expired" else "") + "Muddati tugagan",
            callback_data="adm:list:filter:expired",
        ),
    ]
    rows = [
        filter_buttons,
        [
            InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm:users"),
            InlineKeyboardButton("📅 Kunlik xabarlar", callback_data="adm:daily"),
        ],
        [
            InlineKeyboardButton("🎫 Tarif / muddat", callback_data="adm:tariff"),
            InlineKeyboardButton("➖ Admin o'chir", callback_data="adm:remove"),
        ],
    ]
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Oldingi",
            callback_data=f"adm:list:page:{segment}:{max(0, offset - ADMIN_ROSTER_PAGE_SIZE)}",
        ))
    if offset + ADMIN_ROSTER_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(
            "Keyingi ➡️",
            callback_data=f"adm:list:page:{segment}:{offset + ADMIN_ROSTER_PAGE_SIZE}",
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("🔄 Yangilash", callback_data=f"adm:list:page:{segment}:{offset}")
    ])
    return InlineKeyboardMarkup(rows)


def _daily_template_preview(value: str, limit: int = 500) -> str:
    preview = (value or "").strip()
    if len(preview) > limit:
        preview = preview[:limit - 1].rstrip() + "…"
    return preview or "(xabar kiritilmagan)"


async def _build_daily_message_settings():
    config = await db.get_daily_message_config()
    enabled = bool(config.get("enabled"))
    status = "🟢 Yoqilgan" if enabled else "⏸ To'xtatilgan"
    active_preview = _daily_template_preview(config.get("active_text", ""))
    expired_preview = _daily_template_preview(config.get("expired_text", ""))
    text = (
        "📅 KUNLIK XABARLAR\n\n"
        f"Holat: {status}\n"
        f"Yuborish vaqti: har kuni {config.get('send_time', '10:00')} (Toshkent vaqti).\n\n"
        "✅ Muddati tugamagan, tarif muddati belgilangan foydalanuvchilar:\n"
        f"{active_preview}\n\n"
        "⌛ Muddati tugagan foydalanuvchilar:\n"
        f"{expired_preview}\n\n"
        "Faol xabardagi {referral_link} foydalanuvchining shaxsiy havolasiga almashtiriladi. "
        "Agar joy qoldirilmasa, havola xabar oxiriga qo'shiladi.\n"
        "Muddati tugagan xabarda {admin_phone} admin telefoniga almashtiriladi."
    )
    toggle_label = "⏸ Kunlik xabarni to'xtatish" if enabled else "▶️ Kunlik xabarni ishga tushirish"
    toggle_action = "stop" if enabled else "start"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Faol tarif xabarini o'zgartirish", callback_data="adm:daily:edit:active")],
        [InlineKeyboardButton("✏️ Muddati tugagan xabarni o'zgartirish", callback_data="adm:daily:edit:expired")],
        [InlineKeyboardButton(toggle_label, callback_data=f"adm:daily:{toggle_action}")],
        [
            InlineKeyboardButton("🔄 Yangilash", callback_data="adm:daily"),
            InlineKeyboardButton("⬅️ Adminlar", callback_data="adm:list"),
        ],
    ])
    return text, keyboard


async def _build_user_list(offset: int = 0, segment: str = "all"):
    if segment not in {"all", "active", "expired"}:
        segment = "all"
    if segment == "all":
        total = await db.count_search_users("*", exclude_uid=SUPER_ADMIN)
    else:
        total = await db.count_users_by_tariff_segment(segment, exclude_uid=SUPER_ADMIN)

    max_offset = ((total - 1) // ADMIN_USER_PAGE_SIZE) * ADMIN_USER_PAGE_SIZE if total else 0
    offset = min(max_offset, max(0, (int(offset) // ADMIN_USER_PAGE_SIZE) * ADMIN_USER_PAGE_SIZE))
    if segment == "all":
        users = await db.search_users(
            "*", limit=ADMIN_USER_PAGE_SIZE, offset=offset, exclude_uid=SUPER_ADMIN
        )
    else:
        users = await db.get_users_by_tariff_segment(
            segment, limit=ADMIN_USER_PAGE_SIZE, offset=offset, exclude_uid=SUPER_ADMIN
        )
    rows = [[
        InlineKeyboardButton(
            ("✅ " if segment == "all" else "") + "Barchasi",
            callback_data="adm:users:filter:all",
        ),
        InlineKeyboardButton(
            ("🟢 " if segment == "active" else "") + "Muddat bor",
            callback_data="adm:users:filter:active",
        ),
        InlineKeyboardButton(
            ("⌛ " if segment == "expired" else "") + "Muddati tugagan",
            callback_data="adm:users:filter:expired",
        ),
    ]]
    for user in users:
        target = int(user["uid"])
        name = _admin_display_name(user.get("name"))
        if name == "Ism/familiya kiritilmagan":
            label = f"⚠️ {name} · {target}"
        else:
            label = f"👤 {name[:56]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"adm:ucard:{target}")])

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Oldingi",
            callback_data=f"adm:users:page:{segment}:{max(0, offset - ADMIN_USER_PAGE_SIZE)}",
        ))
    if offset + ADMIN_USER_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(
            "Keyingi ➡️",
            callback_data=f"adm:users:page:{segment}:{offset + ADMIN_USER_PAGE_SIZE}",
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("🔄 Yangilash", callback_data=f"adm:users:page:{segment}:0"),
        InlineKeyboardButton("⬅️ Adminlar", callback_data="adm:list"),
    ])

    first = offset + 1 if users else 0
    last = min(offset + len(users), total)
    if segment == "active":
        heading = "🟢 FAOL TARIFI BOR FOYDALANUVCHILAR"
    elif segment == "expired":
        heading = "⌛ MUDDATI TUGAGAN FOYDALANUVCHILAR"
    else:
        heading = "👥 FOYDALANUVCHILAR RO'YXATI"
    text = (
        f"{heading}\n"
        "Ism bo'yicha A–Z · kartani ochish uchun foydalanuvchi ismini bosing.\n"
        f"Natija: {first}–{last} / {total}"
    )
    if segment == "all":
        active_count = await db.count_users_by_tariff_segment("active", exclude_uid=SUPER_ADMIN)
        expired_count = await db.count_users_by_tariff_segment("expired", exclude_uid=SUPER_ADMIN)
        text += f"\nMuddati bor: {active_count} · Muddati tugagan: {expired_count}"
    if not users:
        if segment == "expired":
            empty = "Muddati tugagan foydalanuvchilar topilmadi."
        elif segment == "active":
            empty = "Muddati hali bor foydalanuvchilar topilmadi."
        else:
            empty = "Foydalanuvchilar topilmadi."
        text += "\n\n❌ " + empty
    return text, InlineKeyboardMarkup(rows)


async def format_admin_list(offset: int = 0, segment: str = "all"):
    """Confirmed-user roster with separate valid-term and expired-term views."""
    if segment not in {"all", "active", "expired"}:
        segment = "all"
    admins = await db.get_admins()
    non_super = [target for target in admins if target != SUPER_ADMIN]
    total_all = len(non_super)
    active_total = await db.count_users_by_tariff_segment("active", exclude_uid=SUPER_ADMIN)
    expired_total = await db.count_users_by_tariff_segment("expired", exclude_uid=SUPER_ADMIN)

    if segment == "all":
        total = total_all
        targets = non_super
    else:
        total = await db.count_users_by_tariff_segment(segment, exclude_uid=SUPER_ADMIN)
        targets = []

    max_offset = ((total - 1) // ADMIN_ROSTER_PAGE_SIZE) * ADMIN_ROSTER_PAGE_SIZE if total else 0
    offset = min(max_offset, max(0, (int(offset) // ADMIN_ROSTER_PAGE_SIZE) * ADMIN_ROSTER_PAGE_SIZE))
    if segment == "all":
        page = targets[offset:offset + ADMIN_ROSTER_PAGE_SIZE]
    else:
        page_rows = await db.get_users_by_tariff_segment(
            segment, limit=ADMIN_ROSTER_PAGE_SIZE, offset=offset, exclude_uid=SUPER_ADMIN
        )
        page = [int(user["uid"]) for user in page_rows]
    page_count = max(1, (total + ADMIN_ROSTER_PAGE_SIZE - 1) // ADMIN_ROSTER_PAGE_SIZE)
    page_number = offset // ADMIN_ROSTER_PAGE_SIZE + 1

    if segment == "active":
        heading = f"🟢 FAOL TARIFI BOR FOYDALANUVCHILAR ({total} ta)"
    elif segment == "expired":
        heading = f"⌛ MUDDATI TUGAGAN FOYDALANUVCHILAR ({total} ta)"
    else:
        heading = f"👥 ADMINLAR ({len(admins)} ta — 1 super + {total} oddiy)"
    lines = [
        heading,
        f"👑 Super admin: {SUPER_ADMIN}",
        f"📊 Muddati bor: {active_total} · Muddati tugagan: {expired_total}",
        f"📄 Sahifa: {page_number}/{page_count} · ism bo'yicha A–Z",
    ]
    for target in page:
        info = await db.get_user_info(target)
        user = await db.get_user(target) or {}
        name = _admin_display_name(info.get("name"))
        username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
        phone = _admin_phone(user.get("phone"))
        session = "✅" if user.get("session") else "❌"
        running = "🟢" if (worker_manager and worker_manager.is_running(target)) else "🔴"
        interval = await db.get_interval(target)
        tariff = await db.get_tariff(target)
        expires = await db.get_tariff_expires(target)
        expiry = expires[:10] if expires else "cheksiz"
        chats = await db.count_chats(target)
        posts = await db.count_posts(target)
        lines.extend([
            "",
            f"👤 {name}",
            f"   {username} | ID: {target}",
            f"   📱 {phone}",
            f"   Sessiya: {session} | Posting: {running}",
            f"   🎫 {tariff_label(tariff)}",
            f"   📅 Muddat: {expiry}",
            f"   💬 {chats} | 📝 {posts} | ⏱ {interval} daq",
        ])
    if not page:
        if segment == "expired":
            empty = "Muddati tugagan foydalanuvchi yo'q."
        elif segment == "active":
            empty = "Muddati hali bor foydalanuvchi yo'q."
        else:
            empty = "Hozircha tasdiqlangan foydalanuvchi yo'q."
        lines.extend(["", empty])
    lines.extend(["", "ℹ️ Muddatli foydalanuvchilar yuqoridagi alohida bo'limlardan ko'riladi."])
    return "\n".join(lines), admin_panel_kb(offset, total, segment)


async def _build_admin_referrals(target: int, offset: int = 0):
    user = await db.get_user(target)
    if not user:
        return "❌ Foydalanuvchi topilmadi.", InlineKeyboardMarkup([])
    referrals = await db.get_referrals(target)
    total = len(referrals)
    active = sum(bool(row.get("counted")) for row in referrals)
    pending = total - active
    max_offset = ((total - 1) // ADMIN_USER_PAGE_SIZE) * ADMIN_USER_PAGE_SIZE if total else 0
    offset = min(max_offset, max(0, (int(offset) // ADMIN_USER_PAGE_SIZE) * ADMIN_USER_PAGE_SIZE))
    page = referrals[offset:offset + ADMIN_USER_PAGE_SIZE]
    name = _admin_display_name(user.get("name"))
    lines = [
        f"👥 {name} taklif qilgan referallar",
        f"Jami: {total} · ✅ Faol: {active} · ⏳ Kutilmoqda: {pending}",
        "",
    ]
    rows = []
    for referral in page:
        status = "✅ Faol" if referral.get("counted") else "⏳ Kutilmoqda"
        referral_name = _admin_display_name(referral.get("name"))
        lines.append(f"• {referral_name} · ID: {referral['uid']} · {status}")
        rows.append([
            InlineKeyboardButton(
                f"👤 {referral_name[:38]} · {status}",
                callback_data=f"adm:ucard:{int(referral['uid'])}",
            )
        ])
    if not referrals:
        lines.append("Hozircha ushbu foydalanuvchining referallari yo'q.")
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Oldingi", callback_data=f"adm:refs:{target}:page:{offset - ADMIN_USER_PAGE_SIZE}"
        ))
    if offset + ADMIN_USER_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(
            "Keyingi ➡️", callback_data=f"adm:refs:{target}:page:{offset + ADMIN_USER_PAGE_SIZE}"
        ))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Foydalanuvchi kartasi", callback_data=f"adm:ucard:{target}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_user_card(target: int):
    user = await db.get_user(target)
    if not user:
        return "❌ Foydalanuvchi topilmadi.", InlineKeyboardMarkup([])

    info = await db.get_user_info(target)
    name = _admin_display_name(info.get("name"))
    username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
    suspended = await db.is_suspended(target)
    expired = await db.is_tariff_expired(target)
    is_approved = bool(user.get("is_admin")) or target == SUPER_ADMIN
    pending = bool(user.get("awaiting_approval") or user.get("pending_session"))
    if suspended:
        status = "⏸ Vaqtincha to'xtatilgan"
    elif not is_approved:
        status = "⏳ Tasdiq kutilmoqda" if pending else "⚪ Tasdiqlanmagan"
    elif expired:
        status = "⌛ Tarif muddati tugagan"
    else:
        status = "✅ Faol"

    expires = user.get("tariff_expires_at")
    expiry_line = expires or "Muddatsiz"
    if expires and not expired:
        remaining = _days_until(expires)
        if remaining is not None:
            expiry_line += f" ({remaining} kun qoldi)"
    tariff = int(user.get("tariff") or DEFAULT_TARIFF)
    max_chats, max_posts = tariff_limits(tariff)
    worker = worker_manager.is_running(target) if worker_manager else False
    session_status = "ha" if user.get("session") else "yo'q"
    worker_status = "🟢 ishlayapti" if worker else "🔴 to'xtagan"
    chat_records = await db.get_chat_records(target)
    active_chats = sum(record.get("status") == "active" for record in chat_records)
    waiting_chats = len(chat_records) - active_chats
    lines = [
        "🪪 FOYDALANUVCHI KARTASI",
        "",
        f"👤 {name}",
        f"🔗 {username} | ID: {target}",
        f"📱 Telefon: {_admin_phone(user.get('phone'))}",
        "",
        f"📌 Hisob: {status}",
        f"🔐 Sessiya saqlangan: {session_status}",
        f"⚙️ Posting worker: {worker_status}",
        "",
        f"🎫 Tarif: {tariff_label(tariff)}",
        f"📅 Tugash: {expiry_line}",
        f"💬 Guruhlar: {len(chat_records)}/{max_chats} (faol {active_chats}, kutishda {waiting_chats})",
        f"📝 Postlar: {await db.count_posts(target)}/{max_posts}",
    ]
    suspended_until = user.get("suspended_until")
    if suspended and suspended_until:
        lines.append(f"⏰ To'xtatish tugaydi: {suspended_until} UTC")
    if user.get("suspend_reason"):
        lines.append(f"📝 Sabab: {user['suspend_reason'][:200]}")

    referrals = await db.get_referrals(target)
    active_referrals = sum(bool(referral.get("counted")) for referral in referrals)
    pending_referrals = len(referrals) - active_referrals
    lines.extend([
        "",
        f"👥 Taklif qilganlari: {len(referrals)} ta "
        f"(faol {active_referrals}, kutilmoqda {pending_referrals})",
    ])
    referrer_uid = await db.get_referrer(target)
    if referrer_uid:
        referrer_info = await db.get_user_info(referrer_uid)
        lines.append(
            f"🔗 O'zi { _admin_display_name(referrer_info.get('name')) } "
            f"(ID: {referrer_uid}) tomonidan taklif qilingan."
        )

    actions = await db.get_admin_actions(target, limit=3)
    if actions:
        lines.extend(["", "🧾 Oxirgi admin amallari:"])
        for action in actions:
            lines.append(
                f"• {action['created_at']} — {action['action']} "
                f"(admin {action['admin_uid']})"
            )

    rows = []
    if target != SUPER_ADMIN:
        if suspended:
            rows.append([InlineKeyboardButton("▶️ Faollashtirish", callback_data=f"adm:resume:{target}")])
        else:
            rows.append([InlineKeyboardButton("⏸ Vaqtincha to'xtatish", callback_data=f"adm:suspend:{target}")])
        rows.append([
            InlineKeyboardButton("🎫 Tarif / muddat", callback_data=f"adm:plan:{target}"),
            InlineKeyboardButton("✉️ Xabar", callback_data=f"adm:dm:{target}"),
        ])
    rows.append([
        InlineKeyboardButton(
            f"👥 Referallarni ko'rish ({len(referrals)})",
            callback_data=f"adm:refs:{target}:page:0",
        )
    ])
    rows.append([InlineKeyboardButton("⬅️ Foydalanuvchilar", callback_data="adm:users:back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the current text-entry flow."""
    uid = update.effective_user.id
    state = user_states.get(uid)
    if not state:
        await update.message.reply_text("Faol jarayon yo'q.")
        return
    if state.get("step") in ("name", "phone", "phone_login", "code", "password"):
        await cleanup_login(uid)
    else:
        user_states.pop(uid, None)
    await update.message.reply_text("❌ Jarayon bekor qilindi.", reply_markup=await menu_for(uid))


async def _handle_admin_input(update: Update, state: dict) -> None:
    """Handle super-admin text entry steps (search, duration, and messages)."""
    uid = update.effective_user.id
    msg = update.message
    step = state.get("step")
    if not is_super(uid):
        user_states.pop(uid, None)
        return
    if time.time() - state.get("ts", 0) > ADMIN_ACTION_TIMEOUT_S:
        user_states.pop(uid, None)
        await msg.reply_text("⏰ Admin amali vaqti tugadi. Qaytadan boshlang.")
        return

    if step == "admin_suspend_days":
        raw = (msg.text or "").strip().lower()
        if raw in {"0", "muddatsiz", "manual", "∞"}:
            days = 0
        else:
            try:
                days = int(raw)
            except ValueError:
                await msg.reply_text("❌ Kun sonini raqam bilan kiriting: 1–3650 yoki 0 (qo'lda faollashtirish).")
                return
            if not 1 <= days <= MAX_ADMIN_TERM_DAYS:
                await msg.reply_text(f"❌ Muddat 1–{MAX_ADMIN_TERM_DAYS} kun yoki 0 bo'lishi kerak.")
                return
        target = int(state["target"])
        if not await db.get_user(target) or target == SUPER_ADMIN:
            user_states.pop(uid, None)
            await msg.reply_text("❌ Foydalanuvchi topilmadi yoki bu amal mumkin emas.")
            return
        state.update({"step": "admin_suspend_confirm", "days": days, "ts": time.time()})
        user_states[uid] = state
        until = calc_expiry(days) if days else None
        period = f"{days} kun — {until} UTC gacha" if until else "qo'lda qayta faollashtirilguncha"
        await msg.reply_text(
            f"⏸ {target} ni {period} to'xtatamizmi?\n"
            "Posting darhol to'xtaydi; sessiya, chat va postlar saqlanadi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ To'xtatish", callback_data="adm:suspend:confirm"),
                    InlineKeyboardButton("❌ Bekor", callback_data="adm:suspend:cancel"),
                ]
            ]),
        )
        return

    if step == "admin_term_days":
        raw = (msg.text or "").strip()
        try:
            days = int(raw)
        except ValueError:
            await msg.reply_text(f"❌ Kun sonini raqam bilan kiriting (1–{MAX_ADMIN_TERM_DAYS}).")
            return
        if not 1 <= days <= MAX_ADMIN_TERM_DAYS:
            await msg.reply_text(f"❌ Muddat 1–{MAX_ADMIN_TERM_DAYS} kun bo'lishi kerak.")
            return
        target = int(state["target"])
        tariff = int(state["tariff"])
        if target == SUPER_ADMIN or tariff not in TARIFFS or not await db.get_user(target):
            user_states.pop(uid, None)
            await msg.reply_text("❌ Foydalanuvchi yoki tarif topilmadi.")
            return
        old_expiry = await db.get_tariff_expires(target)
        expires = calc_expiry(days)
        state.update({
            "step": "admin_term_confirm",
            "days": days,
            "old_expiry": old_expiry,
            "expires_at": expires,
            "ts": time.time(),
        })
        user_states[uid] = state
        old_label = old_expiry or "muddatsiz / avval belgilanmagan"
        await msg.reply_text(
            f"🎫 Foydalanuvchi: {target}\n"
            f"Tarif: {tariff_label(tariff)}\n"
            f"Eski tugash: {old_label}\n"
            f"Yangi muddat: {days} kun — {expires} UTC\n\n"
            "⚠️ Tasdiqlansa, eski muddat almashtiriladi; qolgan kunlar qo'shilmaydi.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Muddatni almashtirish", callback_data="adm:term:confirm"),
                    InlineKeyboardButton("❌ Bekor", callback_data="adm:term:cancel"),
                ]
            ]),
        )
        return

    if step in {"admin_dm_text", "admin_daily_message_active", "admin_daily_message_expired"}:
        if msg.photo or not msg.text:
            await msg.reply_text("❌ Hozircha faqat matnli xabar yuborish mumkin.")
            return
        message_text = msg.text.strip()
        if not message_text:
            await msg.reply_text("❌ Bo'sh xabar yuborib bo'lmaydi.")
            return
        if len(message_text.encode("utf-16-le")) // 2 > MAX_ADMIN_MESSAGE_LENGTH:
            await msg.reply_text(f"❌ Xabar {MAX_ADMIN_MESSAGE_LENGTH} belgidan oshmasin.")
            return
        state["text"] = message_text
        state["ts"] = time.time()
        if step == "admin_dm_text":
            state["step"] = "admin_dm_confirm"
            user_states[uid] = state
            preview = (
                f"✉️ Shaxsiy xabar — {state['target']} ga yuboriladi:\n\n"
                f"{message_text}"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yuborish", callback_data="adm:dm:send"),
                    InlineKeyboardButton("❌ Bekor", callback_data="adm:dm:cancel"),
                ]
            ])
        else:
            segment = "active" if step.endswith("active") else "expired"
            state.update({
                "step": "admin_daily_message_confirm",
                "segment": segment,
                "ts": time.time(),
            })
            user_states[uid] = state
            label = "faol tarif" if segment == "active" else "muddati tugagan"
            preview = f"📝 Yangi {label} kunlik xabari saqlansinmi?\n\n{message_text}"
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Saqlash", callback_data="adm:daily:save"),
                    InlineKeyboardButton("❌ Bekor", callback_data="adm:daily:edit:cancel"),
                ]
            ])
        await msg.reply_text(preview, reply_markup=markup)
        return

    if step in {
        "admin_suspend_confirm", "admin_resume_confirm", "admin_term_confirm",
        "admin_dm_confirm", "admin_daily_message_confirm",
    }:
        await msg.reply_text("Tasdiqlash yoki bekor qilish uchun xabardagi tugmalardan foydalaning. Bekor qilish: /cancel")
        return


# ─────────────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────────────────
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    msg = update.message
    text = (msg.text or "").strip()
    state = user_states.get(uid, {})
    step = state.get("step")

    if not rate_limiter.is_allowed(uid, "message"):
        wait = rate_limiter.get_wait_time(uid, "message")
        await msg.reply_text(f"⏳ Juda ko'p xabar. {wait} soniya kuting.")
        return

    if not is_super(uid) and await db.is_suspended(uid):
        user_states.pop(uid, None)
        user = await db.get_user(uid)
        until = user.get("suspended_until") if user else None
        detail = f"\n⏰ Qayta faollashish: {until} UTC" if until else "\nAdmin qayta faollashtirguncha."
        await msg.reply_text("⏸ Hisobingiz vaqtincha to'xtatilgan." + detail)
        return

    # LOGIN BOSQICHLARI
    if step in ("name", "phone", "phone_login", "code", "password"):
        if time.time() - state.get("ts", 0) > LOGIN_TIMEOUT_S:
            await cleanup_login(uid)
            await msg.reply_text(
                f"⏰ Vaqt tugadi ({LOGIN_TIMEOUT_S // 60} daqiqa). Eski urinish o'chirildi.\n"
                "Qaytadan 🔑 Login bosib boshlang.",
                reply_markup=await menu_for(uid),
            )
            return

        if step == "name":
            await _handle_name(update, text)
            return
        if step == "phone":
            await _handle_phone(update, text)
            return
        if step == "phone_login":
            await _handle_phone_login(update, text)
            return
        if step == "code":
            await _handle_code(update, text)
            return
        if step == "password":
            await _handle_password(update, text)
            return

    # PENDING
    if not await is_approved(uid):
        if await db.get_pending(uid) or await db.is_awaiting_approval(uid):
            await msg.reply_text(
                "⏳ So'rovingiz ko'rib chiqilmoqda. Admin tasdiqlashini kuting.",
                reply_markup=kb_pending(),
            )
            return
        if text == "🔑 Login":
            if not rate_limiter.is_allowed(uid, "login"):
                wait = rate_limiter.get_wait_time(uid, "login")
                await msg.reply_text(f"⏳ Juda ko'p login urinishi. {wait} soniya kuting.")
                return
            await _begin_login(update)
            return
        await msg.reply_text(
            "⚠️ Avval 🔑 Login qiling va admin tasdiqlashini kuting.",
            reply_markup=kb_login(),
        )
        return

    # FSM — menyu tugmasi bosilsa holatni bekor qilib, tugma buyrug'iga o'tkazamiz
    _MENU_BUTTONS = (
        "🔑 Login", "▶️ Start", "⛔ Stop", "💬 Chatlar",
        "➖ Chat o'chir", "🔍 Guruhlarni skanerlash",
        "📝 Post qo'sh", "🗑 Post o'chir", "👥 Referal",
        "👥 Adminlar", "🖥 Tizim",
    )
    _is_menu = text in _MENU_BUTTONS or text.startswith("⏱ Interval") or text.startswith("📊 Status")

    if step and step.startswith("admin_"):
        if _is_menu:
            user_states.pop(uid, None)
            step = None
        else:
            await _handle_admin_input(update, state)
            return

    if step in ("add_post", "set_interval"):
        if _is_menu:
            # Menyu tugmasi bosildi — holatni bekor qilib, pastdagi handlerga o'tkazamiz
            user_states.pop(uid, None)
        else:
            # Oddiy matn — avvalgidek FSM davom etadi
            if step == "add_post":
                await _handle_add_post(update)
                return
            if step == "set_interval":
                await _handle_set_interval(update, text)
                return

    # MENYU
    sess = await db.get_session(uid)
    if not sess:
        if text == "🔑 Login":
            if not rate_limiter.is_allowed(uid, "login"):
                wait = rate_limiter.get_wait_time(uid, "login")
                await msg.reply_text(f"⏳ Juda ko'p login urinishi. {wait} soniya kuting.")
                return
            await _begin_login(update)
            return
        await msg.reply_text("⚠️ Avval 🔑 Login qiling.", reply_markup=kb_login())
        return

    if text == "🔑 Login":
        await msg.reply_text("✅ Siz allaqachon kirgansiz.", reply_markup=await menu_for(uid))
        return

    if text == "👥 Referal":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
        total = await db.count_referrals(uid)
        refs = await db.get_referrals(uid)
        lines = [
            "👥 SIZNING REFERALLARINGIZ\n",
            "🔗 Sizning taklif havolangiz:",
            link,
            "",
            f"✅ Faol referallar: {total} ta",
            "(ro'yxatdan o'tib, tasdiqlangan)",
        ]
        if refs:
            lines.append("")
            lines.append("📋 Ro'yxat:")
            for i, r in enumerate(refs, 1):
                mark = "✅" if r["counted"] else "⏳"
                lines.append(f"{i}. {r['name']} — {mark}")
        else:
            lines.append("")
            lines.append("Hozircha referal yo'q. Havolani do'stlaringizga ulashing!")
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    if text == "▶️ Start":
        if worker_manager and worker_manager.is_running(uid):
            await msg.reply_text("⚠️ Allaqachon ishlamoqda.", reply_markup=await menu_for(uid))
            return
        # Muddat tugagan bo'lsa — kutish rejimi, admin uzaytirmaguncha boshlab bo'lmaydi
        if await db.is_tariff_expired(uid):
            await msg.reply_text(_waiting_mode_text(), reply_markup=await menu_for(uid))
            return
        chats = await db.get_active_chats(uid)
        posts = await db.get_posts(uid)
        if not chats:
            waiting = await db.count_waiting_chats(uid)
            if waiting:
                message = (
                    "⏳ Hozir yuborish mumkin bo'lgan faol guruh yo'q. "
                    "Qayta tekshirish uchun 🔍 Guruhlarni skanerlashni bosing."
                )
            else:
                message = "❌ Avval 🔍 Guruhlarni skanerlang va kerakli guruhlarni tasdiqlang."
            await msg.reply_text(message, reply_markup=await menu_for(uid))
            return
        if not posts:
            await msg.reply_text("❌ Avval 📝 Post qo'shing.", reply_markup=await menu_for(uid))
            return
        interval = await db.get_interval(uid)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha, boshlash", callback_data="go:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="go:no"),
                ]
            ]
        )
        await msg.reply_text(
            "▶️ Postingni boshlaymizmi?\n\n"
            f"💬 {len(chats)} ta chatga\n"
            f"📝 {len(posts)} ta postdan navbatma-navbat\n"
            f"⏱ Har {interval} daqiqada yuboriladi.",
            reply_markup=kb,
        )
        return

    if text == "⛔ Stop":
        if not (worker_manager and worker_manager.is_running(uid)):
            await msg.reply_text("⚠️ Hozir ishlamayapti.", reply_markup=await menu_for(uid))
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="stop:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="stop:no"),
                ]
            ]
        )
        await msg.reply_text("⛔ Postingni to'xtatasizmi?", reply_markup=kb)
        return

    if text.startswith("📊 Status"):
        chats = await db.get_chats(uid)
        active_chats = await db.get_active_chats(uid)
        waiting_chats = await db.count_waiting_chats(uid)
        posts = await db.get_posts(uid)
        interval = await db.get_interval(uid)
        tariff = await db.get_tariff(uid)
        max_chats, max_posts = tariff_limits(tariff)
        expires = await db.get_tariff_expires(uid)
        active = worker_manager.is_running(uid) if worker_manager else False
        expired = await db.is_tariff_expired(uid)
        if expired:
            status = "⏸ Kutish rejimi (muddat tugagan)"
        else:
            status = "🟢 ON" if active else "🔴 OFF"
        exp_line = f"📅 Muddat: {expires[:10]}" if expires else "📅 Muddat: cheksiz"
        await msg.reply_text(
            "📊 STATUS\n\n"
            f"Holat: {status}\n"
            f"Sessiya: ✅\n"
            f"Tarif: {tariff_label(tariff)}\n"
            f"{exp_line}\n"
            f"Guruhlar: {len(chats)}/{max_chats} (faol {len(active_chats)}, kutishda {waiting_chats})\n"
            f"Postlar: {len(posts)}/{max_posts}\n"
            f"Interval: {interval} daqiqa",
            reply_markup=await menu_for(uid),
        )
        return

    if text == "💬 Chatlar":
        records = await db.get_chat_records(uid)
        if not records:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        max_chats, _ = await user_limits(uid)
        active_count = sum(row.get("status") == "active" for row in records)
        waiting_count = len(records) - active_count
        header = [
            f"💬 GURUHLAR ({len(records)}/{max_chats})",
            f"🟢 Faol: {active_count} · ⏳ Kutishda: {waiting_count}",
            "",
        ]
        items = []
        for i, record in enumerate(records, 1):
            title = (record.get("title") or record["chat_id"]).replace("\n", " ")[:60]
            status = "🟢 Faol" if record.get("status") == "active" else "⏳ Kutishda"
            suffix = (
                f" · xatolar: {record.get('fail_count', 0)}"
                if record.get("status") == "waiting" and record.get("fail_count")
                else ""
            )
            items.append(f"{i}. {title}\n   {status}{suffix}\n   {record['chat_id']}")
        menu = await menu_for(uid)
        chunk_size = 15
        for start in range(0, len(items), chunk_size):
            lines = header + items[start:start + chunk_size] if start == 0 else items[start:start + chunk_size]
            final_chunk = start + chunk_size >= len(items)
            await msg.reply_text(
                "\n".join(lines),
                reply_markup=menu if final_chunk else None,
            )
        return

    if text == "🔍 Guruhlarni skanerlash":
        await _handle_group_scan_button(update)
        return

    if text == "➖ Chat o'chir":
        records = await db.get_chat_records(uid)
        if not records:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        rows = []
        for i, record in enumerate(records):
            title = record.get("title") or record["chat_id"]
            status = "🟢" if record.get("status") == "active" else "⏳"
            rows.append([
                InlineKeyboardButton(
                    f"🗑 {i + 1}. {status} {title[:35]}", callback_data=f"delc:{i}"
                )
            ])
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="delc:cancel")])
        await msg.reply_text(
            f"➖ O'chirish uchun guruhni tanlang ({len(records)} ta):",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text == "📝 Post qo'sh":
        if not rate_limiter.is_allowed(uid, "modify"):
            wait = rate_limiter.get_wait_time(uid, "modify")
            await msg.reply_text(f"⏳ {wait} soniya kuting.")
            return
        posts = await db.get_posts(uid)
        _, max_posts = await user_limits(uid)
        if len(posts) >= max_posts:
            await msg.reply_text(
                f"❌ Maksimal {max_posts} ta post (sizning tarifingiz).",
                reply_markup=await menu_for(uid),
            )
            return
        user_states[uid] = {"step": "add_post", "ts": time.time()}
        await msg.reply_text(
            "✍️ Reklama yuboring:\n\n"
            "• Faqat matn (formatlash bilan)\n"
            "• Rasm + caption (formatlash bilan)\n"
            "• Faqat rasm\n\n"
            "Bold, italic, link va barcha formatlash saqlanadi.\n"
            f"📝 Hozir: {len(posts)}/{max_posts}"
        )
        return

    if text == "🗑 Post o'chir":
        posts = await db.get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        rows = []
        for i, p in enumerate(posts):
            icon = "🖼" if p.get("photo") else "📝"
            preview = (p.get("text") or "(rasm)")[:25]
            rows.append([InlineKeyboardButton(f"🗑 {i+1}. {icon} {preview}", callback_data=f"delp:{i}")])
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="delp:cancel")])
        await msg.reply_text(
            f"🗑 O'chirish uchun postni tanlang ({len(posts)} ta):",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text.startswith("⏱ Interval"):
        interval = await db.get_interval(uid)
        user_states[uid] = {"step": "set_interval", "ts": time.time()}
        await msg.reply_text(
            f"⏱ INTERVAL\n\n"
            f"Hozir: {interval} daqiqa\n"
            f"Yangi qiymatni kiriting ({MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} daq):"
        )
        return

    if text == "👥 Adminlar" and is_super(uid):
        overview_text, overview_markup = await format_admin_list()
        await msg.reply_text(overview_text, reply_markup=overview_markup)
        return

    if text == "🖥 Tizim" and is_super(uid):
        uptime = int(time.time() - START_TIME)
        worker_stats = worker_manager.stats() if worker_manager else None
        pool_stats = client_pool.stats() if client_pool else None
        memory = _get_memory_info()
        rl_stats = rate_limiter.stats()

        lines = [
            format_status_message(uptime, worker_stats, pool_stats, memory),
            "",
            f"🛡 Rate limiter: {rl_stats['tracked_users']} kuzatilmoqda, "
            f"{rl_stats['currently_blocked']} bloklangan",
        ]
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    await msg.reply_text(
        "⚠️ Iltimos, menyudagi tugmalardan foydalaning.",
        reply_markup=await menu_for(uid),
    )


# ─────────────────────────────────────────────────────────────────────────
# LOGIN HANDLERS
# ─────────────────────────────────────────────────────────────────────────
async def _begin_login(update: Update) -> None:
    uid = update.effective_user.id
    await cleanup_login(uid)

    # TASDIQLANGAN foydalanuvchi (admin) — ro'yxatdan o'tish kerak emas.
    # To'g'ridan-to'g'ri kod so'rovi (login fazasi).
    if await is_approved(uid):
        phone = await db.get_phone(uid)
        if phone:
            await update.message.reply_text(
                f"📱 {phone} raqamiga kod yuborilmoqda...\n"
                "Telegram ilovangizdagi \"Telegram\" rasmiy chatini tekshiring."
            )
            await _request_code(uid, phone)
            return
        # Tasdiqlangan, lekin telefon saqlanmagan (super admin yoki eski user)
        user_states[uid] = {"step": "phone_login", "ts": time.time()}
        await update.message.reply_text(
            "📱 Telefon raqamingizni yuboring (kod keladi):\n\n"
            "Format: +998XXXXXXXXX"
        )
        return

    # YANGI foydalanuvchi — ro'yxatdan o'tish (kod so'rovi YO'Q, avval admin tasdiqlaydi)
    user_states[uid] = {"step": "name", "ts": time.time()}
    await update.message.reply_text(
        "📋 RO'YXATDAN O'TISH (1/3)\n\n"
        "👤 Ism va familiyangizni kiriting (kamida 2 so'z):\n\n"
        "Bu ism admin sizni tasdiqlashi uchun kerak.\n\n"
        "Masalan: Akmal Karimov\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 Keyingi qadamlar:\n"
        "2️⃣ Telefon raqam\n"
        "3️⃣ Admin tasdiqlashi\n"
        "    (tasdiqdan keyingina kod keladi)\n\n"
        f"❓ Yordam: {ADMIN_CONTACT_PHONE}"
    )


def _has_first_and_last_name(value: str) -> bool:
    """Require two name parts; Unicode letters, apostrophes, and hyphens are accepted."""
    parts = value.split()
    if len(parts) < 2:
        return False
    return all(any(char.isalpha() for char in part) for part in parts[:2])


async def _handle_name(update: Update, text: str) -> None:
    uid = update.effective_user.id
    name = " ".join(text.split())[:64].strip()
    if not _has_first_and_last_name(name):
        state = user_states.get(uid)
        if state and state.get("step") == "name":
            state["ts"] = time.time()
            user_states[uid] = state
        await update.message.reply_text(
            "❌ Iltimos, ism va familiyangizni kamida ikki so'z bilan kiriting.\n"
            "Masalan: Akmal Karimov. Raqam yoki faqat 'Login' qabul qilinmaydi."
        )
        return
    username = update.effective_user.username or ""
    # Ismni darhol saqlaymiz — admin tasdiq xabarida ko'rinadi
    await db.set_user_info(uid, name, username)
    user_states[uid] = {"step": "phone", "ts": time.time()}
    await update.message.reply_text(
        f"✅ Rahmat, {name}!\n\n"
        "📋 RO'YXATDAN O'TISH (2/3)\n\n"
        "📱 Telefon raqamingizni yuboring:\n\n"
        "Format: +998XXXXXXXXX\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 Keyingi qadam:\n"
        "3️⃣ Admin tasdiqlashi\n"
        "    (tasdiqdan keyingina kod keladi)\n\n"
        f"❓ Yordam: {ADMIN_CONTACT_PHONE}"
    )


async def _handle_phone(update: Update, text: str) -> None:
    uid = update.effective_user.id
    phone = text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 7:
        await update.message.reply_text(
            "❌ Telefon + bilan, faqat raqamlardan iborat bo'lishi kerak.\nMasalan: +998901234567"
        )
        return

    # Telefonni saqlaymiz (tasdiqdan keyin login uchun ishlatiladi)
    await db.set_phone(uid, phone)
    user_states.pop(uid, None)

    # KOD SO'RALMAYDI — avval admin tasdiqlashi kerak.
    # Bu Telegram'ga keraksiz kod so'rovlarini (flood ban sababi) oldini oladi.
    await db.set_awaiting_approval(uid, True)
    log(f"⏳ Ro'yxatdan o'tish so'rovi: {uid} ({phone})")
    await notify_super_for_approval(uid)
    await update.message.reply_text(
        "✅ So'rovingiz qabul qilindi!\n\n"
        "📋 RO'YXATDAN O'TISH (3/3)\n\n"
        "⏳ Endi admin tasdiqlashini kuting.\n"
        "Tasdiqlangach, 🔑 Login bosib kodni kiritasiz.\n\n"
        f"📞 Tezroq tasdiqlanish uchun: {ADMIN_CONTACT_PHONE}",
        reply_markup=kb_pending(),
    )


async def _request_code(uid: int, phone: str) -> None:
    """Telegram'ga kod so'rovi yuboradi (FAQAT tasdiqlangan user uchun, login fazasi)."""
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        result = await client.send_code_request(phone)
        login_ctx[uid] = LoginCtx(
            client=client,
            phone=phone,
            phone_code_hash=result.phone_code_hash,
            started_at=time.time(),
        )
        user_states[uid] = {
            "step": "code",
            "ts": time.time(),
            "code_buffer": "",
        }
        await _send_numpad(
            uid,
            "",
            hint=(
                "📩 Kod yuborildi!\n"
                "Telegram ilovangizdagi \"Telegram\" rasmiy chatidan kodni "
                "KO'RING (kopiyalamasdan!) va tugmalar orqali kiriting."
            ),
        )
    except PhoneNumberInvalidError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await application.bot.send_message(
            uid,
            "❌ Noto'g'ri raqam. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
    except PhoneNumberBannedError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await application.bot.send_message(
            uid, "🚫 Bu raqam bloklangan.", reply_markup=await menu_for(uid)
        )
    except FloodWaitError as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await application.bot.send_message(
            uid,
            f"⏳ Juda ko'p urinish. {e.seconds} soniya kuting.",
            reply_markup=await menu_for(uid),
        )
    except Exception as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        log(f"❌ request_code {uid}: {type(e).__name__}: {e}", "error")
        await application.bot.send_message(
            uid,
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


async def _handle_phone_login(update: Update, text: str) -> None:
    """Tasdiqlangan user telefonini kiritadi (telefoni saqlanmagan holatda) → kod so'rovi."""
    uid = update.effective_user.id
    phone = text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 7:
        await update.message.reply_text(
            "❌ Telefon + bilan, faqat raqamlardan iborat bo'lishi kerak.\nMasalan: +998901234567"
        )
        return
    await db.set_phone(uid, phone)
    user_states.pop(uid, None)
    await _request_code(uid, phone)


async def _handle_code(update: Update, text: str) -> None:
    """Code bosqichida MATN qabul qilinmaydi — numpad'ga yo'naltiramiz."""
    uid = update.effective_user.id
    await update.message.reply_text(
        "⚠️ Iltimos, kodni MATN sifatida yozmang!\n\n"
        "Telegram xavfsizlik tizimi matnli kodni darhol bekor qiladi.\n"
        "Faqat pastdagi RAQAMLI TUGMALAR orqali kiriting:",
    )
    state = user_states.get(uid, {})
    state.setdefault("code_buffer", "")
    state["ts"] = time.time()
    user_states[uid] = state
    await _send_numpad(uid, state["code_buffer"])


async def _handle_password(update: Update, text: str) -> None:
    uid = update.effective_user.id
    ctx = login_ctx.get(uid)
    if not ctx:
        await cleanup_login(uid)
        await update.message.reply_text(
            "❌ Jarayon buzildi. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
        return
    try:
        if not ctx.client.is_connected():
            await asyncio.wait_for(ctx.client.connect(), timeout=20)
        await ctx.client.sign_in(password=text)
        await _finalize_login_uid(uid)
    except PasswordHashInvalidError:
        await update.message.reply_text("❌ Noto'g'ri parol. Qaytadan kiriting:")
    except FloodWaitError as e:
        await cleanup_login(uid)
        await update.message.reply_text(
            f"⏳ {e.seconds} soniya kuting.", reply_markup=await menu_for(uid)
        )
    except Exception as e:
        await cleanup_login(uid)
        log(f"❌ password {uid}: {type(e).__name__}: {e}", "error")
        await update.message.reply_text(
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


# ─────────────────────────────────────────────────────────────────────────
# CHAT / POST / INTERVAL / SCHEDULE INPUT
# ─────────────────────────────────────────────────────────────────────────
def _normalized_chat_key(value: str) -> str:
    """Legacy link, @username and parsed target aliases to one comparison key."""
    parsed = extract_chat_targets(value)
    if parsed:
        target = parsed[0]
        return target.lower() if target.startswith("@") else target
    stripped = value.strip()
    return stripped.lower() if stripped.startswith("invite:") else stripped


def _canonical_chat_storage(entity, fallback: str) -> str:
    """Store public chats as @username and private chats as marked peer IDs."""
    username = getattr(entity, "username", None)
    if username:
        return "@" + username.lower()
    try:
        return str(get_peer_id(entity))
    except Exception:
        return fallback


def _is_group_entity(entity) -> bool:
    """Only basic groups and Telegram supergroups qualify; broadcast channels do not."""
    if isinstance(entity, Chat):
        return not bool(getattr(entity, "left", False)) and not bool(
            getattr(entity, "migrated_to", None)
        )
    if isinstance(entity, Channel):
        return bool(getattr(entity, "megagroup", False)) and not bool(
            getattr(entity, "broadcast", False)
        ) and not bool(getattr(entity, "left", False))
    return False


async def _group_can_send(client, entity, me) -> bool | None:
    """Check the logged-in account's text-send permission in a group.

    ``None`` means Telegram did not provide enough information to classify it;
    callers can still include it as a waiting group after explicit confirmation.
    """
    permissions = await client.get_permissions(entity, me)
    if permissions is None:
        return None
    if permissions.is_admin or permissions.is_creator:
        return True
    if permissions.has_left:
        return False

    participant = getattr(permissions, "participant", None)
    member_rights = getattr(participant, "banned_rights", None)
    if permissions.is_banned:
        if bool(getattr(participant, "left", False)):
            return False
        if member_rights is not None and bool(getattr(member_rights, "send_messages", False)):
            return False

    if not (permissions.has_default_permissions or permissions.is_banned):
        return None

    default_rights = getattr(entity, "default_banned_rights", None)
    if default_rights is None:
        default_rights = await client.get_permissions(entity)
    if default_rights is not None and bool(getattr(default_rights, "send_messages", False)):
        return False
    if permissions.is_banned and member_rights is None:
        return None
    if permissions.is_banned and bool(getattr(member_rights, "send_messages", False)):
        return False
    return True


async def _scan_user_groups(client, uid: int):
    """Scan the user's joined groups only; never adds or changes chats."""
    existing_records = await db.get_chat_records(uid)
    known = {
        _normalized_chat_key(row["chat_id"]): row
        for row in existing_records
    }
    groups: list[dict] = []
    seen: set[str] = set()
    note = ""
    dialog_count = 0
    truncated = False
    try:
        me = await client.get_me(input_peer=True)
        async for dialog in client.iter_dialogs(
            limit=GROUP_SCAN_MAX_DIALOGS, ignore_migrated=True
        ):
            dialog_count += 1
            entity = getattr(dialog, "entity", None)
            if not _is_group_entity(entity):
                continue
            try:
                peer_id = str(get_peer_id(entity))
            except Exception:
                peer_id = str(getattr(entity, "id", ""))
            chat_id = _canonical_chat_storage(entity, peer_id)
            key = _normalized_chat_key(chat_id)
            peer_key = _normalized_chat_key(peer_id)
            if not chat_id or key in seen or peer_key in seen:
                continue
            seen.add(key)
            seen.add(peer_key)
            saved = known.get(key) or known.get(peer_key)
            if saved:
                # Keep the existing storage key so a rescan updates, not duplicates, it.
                chat_id = saved["chat_id"]
            title = " ".join(
                str(getattr(dialog, "name", None) or getattr(entity, "title", None) or chat_id).split()
            )[:200]
            try:
                writable = await _group_can_send(client, entity, me)
                error = ""
            except FloodWaitError as exc:
                writable = None
                error = f"Telegram kutish cheklovi ({int(getattr(exc, 'seconds', 0))} soniya)"
                note = error + "; skanerlash qisman bajarildi."
                groups.append({
                    "chat_id": chat_id,
                    "peer_id": peer_id,
                    "title": title,
                    "writable": writable,
                    "error": error,
                    "existing_status": saved.get("status") if saved else None,
                })
                break
            except Exception as exc:
                writable = None
                error = type(exc).__name__
                log(
                    f"⚠️ Guruh huquqini tekshirib bo'lmadi {uid} → {chat_id}: {error}",
                    "warning",
                )
            groups.append({
                "chat_id": chat_id,
                "peer_id": peer_id,
                "title": title,
                "writable": writable,
                "error": error,
                "existing_status": saved.get("status") if saved else None,
            })
        if dialog_count >= GROUP_SCAN_MAX_DIALOGS:
            truncated = True
            note = (note + " " if note else "") + (
                f"Telegramdagi dastlabki {GROUP_SCAN_MAX_DIALOGS} ta dialog tekshirildi."
            )
    except FloodWaitError as exc:
        note = f"Telegram kutish cheklovi ({int(getattr(exc, 'seconds', 0))} soniya); skanerlash qisman bajarildi."
    except Exception as exc:
        note = f"Skanerlashda xatolik: {type(exc).__name__}."
        log(f"⚠️ Guruh skaneri xatosi {uid}: {type(exc).__name__}: {exc}", "warning")
    return groups, note, truncated, dialog_count


def _utf16_units(value: str) -> int:
    """Telegram button labels are limited by UTF-16 code units."""
    return len(value.encode("utf-16-le")) // 2


def _truncate_utf16(value: str, max_units: int) -> str:
    result: list[str] = []
    units = 0
    for char in str(value):
        char_units = 2 if ord(char) > 0xFFFF else 1
        if units + char_units > max_units:
            break
        result.append(char)
        units += char_units
    truncated = "".join(result)
    if len(truncated) < len(str(value)) and max_units > 0:
        while result and _utf16_units("".join(result) + "…") > max_units:
            result.pop()
        truncated = "".join(result) + "…"
    return truncated


def _group_scan_info_label(group: dict, index: int) -> str:
    """Keep the group name and statuses together in the left button of its row."""
    existing = group.get("existing_status")
    if existing == "active":
        existing_label = "🟢 faol"
    elif existing == "waiting":
        existing_label = "⏳ kutishda"
    else:
        existing_label = "🆕 yangi"

    if group.get("writable") is True:
        permission = "✅ yozish mumkin"
    elif group.get("writable") is False:
        permission = "⛔ yozish yo'q"
    else:
        error = group.get("error")
        permission = f"❔ {str(error)[:16]}" if error else "❔ tekshirilmagan"

    prefix = f"{index + 1}. "
    suffix = f" · {permission} · {existing_label}"
    title = " ".join(str(group.get("title") or group.get("chat_id") or "Guruh").split())
    title_budget = max(1, 60 - _utf16_units(prefix) - _utf16_units(suffix))
    return prefix + _truncate_utf16(title, title_budget) + suffix


async def _build_group_scan_message(uid: int):
    state = user_states.get(uid, {})
    groups = state.get("groups", [])
    selected = state.get("selected", set())
    page = max(0, int(state.get("page", 0)))
    total_pages = max(1, (len(groups) + GROUP_SCAN_PAGE_SIZE - 1) // GROUP_SCAN_PAGE_SIZE)
    page = min(page, total_pages - 1)
    state["page"] = page

    writable_count = sum(group.get("writable") is True for group in groups)
    blocked_count = sum(group.get("writable") is False for group in groups)
    unknown_count = sum(group.get("writable") is None for group in groups)
    active_count = sum(group.get("existing_status") == "active" for group in groups)
    waiting_count = sum(group.get("existing_status") == "waiting" for group in groups)
    new_count = sum(group.get("existing_status") is None for group in groups)
    selected_new = sum(
        i in selected and groups[i].get("existing_status") is None
        for i in range(len(groups))
    )
    selected_waiting = sum(
        i in selected and groups[i].get("existing_status") == "waiting"
        for i in range(len(groups))
    )
    max_chats, _ = await user_limits(uid)
    registered = await db.count_chats(uid)
    available = max(0, max_chats - registered)

    lines = [
        "🔍 GURUHLARNI SKANERLASH NATIJASI",
        "",
        f"Topildi: {len(groups)} ta guruh (kanallar skanerlanmadi)",
        f"✅ Yozish mumkin: {writable_count} · ⛔ Huquq yo'q: {blocked_count} · ❔ Aniqlanmadi: {unknown_count}",
        f"Ro'yxatda: 🟢 faol {active_count} · ⏳ kutishda {waiting_count} · 🆕 yangi {new_count}",
        f"Tanlangan: {len(selected)} (yangi {selected_new}, kutishdagi qayta tekshiruv {selected_waiting})",
        f"Tarif bo'yicha yangi guruhlar uchun joy: {available}/{max_chats}",
    ]
    if state.get("note"):
        lines.extend(["", "ℹ️ " + state["note"]])
    if groups:
        start = page * GROUP_SCAN_PAGE_SIZE
        end = min(start + GROUP_SCAN_PAGE_SIZE, len(groups))
        lines.extend([
            "",
            f"Guruhlar ({start + 1}–{end}/{len(groups)}): chap tugmada nom/yozish huquqi/holat, o'ng tomonda tanlash.",
        ])
    else:
        lines.extend(["", "Telegram dialoglaridan guruh topilmadi."])

    rows = []
    if groups:
        start = page * GROUP_SCAN_PAGE_SIZE
        end = min(start + GROUP_SCAN_PAGE_SIZE, len(groups))
        for index in range(start, end):
            group = groups[index]
            is_active = group.get("existing_status") == "active"
            selection_label = (
                "🟢 Faol"
                if is_active
                else "☑️ Tanlangan" if index in selected else "◻️ Tanlash"
            )
            selection_callback = (
                f"gscan:info:{index}" if is_active else f"gscan:toggle:{index}"
            )
            rows.append([
                InlineKeyboardButton(
                    _group_scan_info_label(group, index),
                    callback_data=f"gscan:info:{index}",
                ),
                InlineKeyboardButton(
                    selection_label,
                    callback_data=selection_callback,
                ),
            ])
        rows.append([InlineKeyboardButton("✅ Yozish mumkin bo'lganlarni tanlash", callback_data="gscan:select:writable")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"gscan:page:{page - 1}"))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"gscan:page:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([
            InlineKeyboardButton(
                "✅ Tanlanganlarni tasdiqlash",
                callback_data="gscan:confirm",
                style="success",
            ),
            InlineKeyboardButton(
                "❌ Bekor",
                callback_data="gscan:cancel",
                style="danger",
            ),
        ])
    else:
        rows.append([InlineKeyboardButton("❌ Yopish", callback_data="gscan:cancel")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _confirm_group_scan(uid: int, query) -> None:
    state = user_states.get(uid, {})
    selected = state.get("selected", set())
    groups = state.get("groups", [])
    if not await is_approved(uid):
        user_states.pop(uid, None)
        await query.edit_message_text("❌ Hisob tasdiqlanmagan. Skanerlash yakunlandi.")
        return
    if not selected:
        user_states.pop(uid, None)
        await query.edit_message_text("ℹ️ Hech bir guruh tanlanmadi — o'zgarish kiritilmadi.")
        return

    max_chats, _ = await user_limits(uid)
    latest_records = await db.get_chat_records(uid)
    existing = {
        _normalized_chat_key(row["chat_id"]): row
        for row in latest_records
    }
    added_active = 0
    added_waiting = 0
    reactivated = 0
    still_waiting = 0
    duplicates = 0
    limit_reached = 0

    for index, group in enumerate(groups):
        if index not in selected:
            continue
        chat_id = group["chat_id"]
        key = _normalized_chat_key(chat_id)
        peer_key = _normalized_chat_key(group.get("peer_id", chat_id))
        current = existing.get(key) or existing.get(peer_key)
        title = group.get("title", "")
        if current and current.get("status") == "active":
            duplicates += 1
            continue
        if current and current.get("status") == "waiting":
            if group.get("writable") is True:
                if await db.update_chat_status(uid, current["chat_id"], "active", title=title):
                    reactivated += 1
                    current["status"] = "active"
            else:
                still_waiting += 1
            continue

        status = "active" if group.get("writable") is True else "waiting"
        ok, reason = await db.add_chat(
            uid, chat_id, max_chats=max_chats, status=status, title=title
        )
        if ok:
            saved_record = {"chat_id": chat_id, "status": status, "title": title}
            existing[key] = saved_record
            existing[peer_key] = saved_record
            if status == "active":
                added_active += 1
            else:
                added_waiting += 1
        elif reason == "limit":
            limit_reached += 1
        elif reason == "duplicate":
            duplicates += 1

    user_states.pop(uid, None)
    lines = [
        "✅ Guruh skaneri bo'yicha tanlov saqlandi.",
        f"🟢 Faol qo'shildi: {added_active}",
        f"⏳ Kutish holatida qo'shildi (yozish huquqi yo'q/aniqlanmadi): {added_waiting}",
        f"🔄 Kutishdan faol holatga qaytdi: {reactivated}",
    ]
    if still_waiting:
        lines.append(f"⏳ Huquq tiklanmagani uchun kutishda qoldi: {still_waiting}")
    if duplicates:
        lines.append(f"ℹ️ Avvaldan faol: {duplicates}")
    if limit_reached:
        lines.append(f"⛔ Tarif limiti sabab qo'shilmadi: {limit_reached}")
    lines.append("\nYozish huquqi tiklangan kutishdagi guruh faqat qo'lda skanerlash va tasdiqlashdan keyin faollashadi.")
    await query.edit_message_text("\n".join(lines))
    with contextlib.suppress(Exception):
        await application.bot.send_message(
            uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
        )


async def _handle_group_scan_button(update: Update) -> None:
    """Run the user's explicit manual group scan and present a confirmation draft."""
    uid = update.effective_user.id
    msg = update.message
    user_states.pop(uid, None)
    if not rate_limiter.is_allowed(uid, "modify"):
        wait = rate_limiter.get_wait_time(uid, "modify")
        await msg.reply_text(f"⏳ {wait} soniya kuting.")
        return
    if not await is_approved(uid):
        await msg.reply_text("❌ Avval admin tasdig'idan o'ting.", reply_markup=await menu_for(uid))
        return
    session = await db.get_session(uid)
    if not session or client_pool is None:
        await msg.reply_text(
            "❌ Telegram sessiyasi topilmadi. Qaytadan 🔑 Login qiling.",
            reply_markup=await menu_for(uid),
        )
        return

    progress = await msg.reply_text("🔍 Telegram guruhlari qo'lda skanerlanmoqda. Bu biroz vaqt olishi mumkin…")
    try:
        client = await client_pool.acquire(uid, session)
    except SessionInvalidError:
        await db.del_session(uid)
        await db.set_running(uid, False)
        await client_pool.remove(uid)
        await progress.edit_text("🚫 Telegram sessiyasi yaroqsiz. Qaytadan 🔑 Login qiling.")
        return
    except PoolBusyError:
        await progress.edit_text("⏳ Telegram ulanishi hozir band. Birozdan keyin qayta urinib ko'ring.")
        return
    except Exception as exc:
        log(f"⚠️ Guruh skaneri uchun ulanib bo'lmadi {uid}: {type(exc).__name__}", "warning")
        await progress.edit_text("❌ Telegram akkauntiga ulanib bo'lmadi. Keyinroq qayta urinib ko'ring.")
        return

    try:
        groups, note, truncated, dialog_count = await _scan_user_groups(client, uid)
    except Exception as exc:
        log(f"⚠️ Guruh skaneri xatosi {uid}: {type(exc).__name__}: {exc}", "warning")
        await progress.edit_text("❌ Guruhlarni skanerlashda kutilmagan xatolik yuz berdi. Keyinroq qayta urinib ko'ring.")
        return
    finally:
        await client_pool.release(uid)

    selected = {
        index for index, group in enumerate(groups)
        if group.get("existing_status") == "waiting"
        or (group.get("writable") is True and group.get("existing_status") is None)
    }
    user_states[uid] = {
        "step": "group_scan_review",
        "ts": time.time(),
        "groups": groups,
        "selected": selected,
        "page": 0,
        "note": note,
        "truncated": truncated,
        "dialogs_scanned": dialog_count,
    }
    text, markup = await _build_group_scan_message(uid)
    await progress.edit_text(text, reply_markup=markup)


async def _handle_add_post(update: Update) -> None:
    uid = update.effective_user.id
    user_states.pop(uid, None)
    msg = update.message

    text = msg.text or msg.caption or ""
    entities_src = list(msg.entities or []) + list(msg.caption_entities or [])

    _, max_posts = await user_limits(uid)
    # Limitni rasm yuklashdan oldin tekshiramiz (rasm yuklab keyin
    # tashlab yuborish — vaqt va trafik isrofi)
    pre_count = await db.count_posts(uid)
    if pre_count >= max_posts:
        await msg.reply_text(
            f"❌ Maksimal {max_posts} ta post (sizning tarifingiz).",
            reply_markup=await menu_for(uid),
        )
        return

    photo_path: str | None = None
    if msg.photo:
        try:
            photo = msg.photo[-1]
            tg_file = await photo.get_file()
            user_dir = _user_media_dir(uid)
            photo_path = os.path.join(user_dir, f"{uuid.uuid4().hex}.jpg")
            await tg_file.download_to_drive(custom_path=photo_path)
        except Exception as e:
            log(f"❌ Rasm yuklashda xato {uid}: {type(e).__name__}: {e}", "error")
            await msg.reply_text(
                "❌ Rasmni saqlab bo'lmadi. Qaytadan urinib ko'ring.",
                reply_markup=await menu_for(uid),
            )
            return

    if not text.strip() and not photo_path:
        await msg.reply_text(
            "❌ Bo'sh post qabul qilinmaydi.\nMatn yoki rasm yuboring.",
            reply_markup=await menu_for(uid),
        )
        return

    entities_dict = [entity_to_dict(e) for e in entities_src]
    # Atomic check + insert (race-safe)
    ok, reason, _ = await db.add_post(
        uid, text, entities_dict, photo_path, max_posts=max_posts
    )
    if not ok:
        _safe_unlink(photo_path)
        if reason == "limit":
            await msg.reply_text(
                f"❌ Maksimal {max_posts} ta post (sizning tarifingiz).",
                reply_markup=await menu_for(uid),
            )
        else:
            await msg.reply_text(
                "❌ Saqlab bo'lmadi.", reply_markup=await menu_for(uid)
            )
        return

    new_count = await db.count_posts(uid)
    log(f"📝 Post qo'shildi: {uid} (#{new_count}) {'+rasm' if photo_path else ''}")
    preview = (text or "(faqat rasm)")[:100]
    kind = "🖼 Rasm + matn" if photo_path else "📝 Matn"
    await msg.reply_text(
        f"✅ Saqlandi (#{new_count})\n{kind}\n\n{preview}",
        reply_markup=await menu_for(uid),
    )


async def _handle_edit_post(update: Update) -> None:
    uid = update.effective_user.id
    state = user_states.get(uid, {})
    post_id = state.get("edit_post_id")
    old_photo = state.get("edit_old_photo")
    user_states.pop(uid, None)
    msg = update.message

    if post_id is None:
        await msg.reply_text(
            "❌ Tahrir jarayoni buzildi. Qaytadan urinib ko'ring.",
            reply_markup=await menu_for(uid),
        )
        return

    # Post hali ham mavjudmi? (tahrir paytida o'chirilgan bo'lishi mumkin)
    current = await db.get_post(post_id)
    if not current:
        await msg.reply_text(
            "❌ Post topilmadi (o'chirilgan bo'lishi mumkin).",
            reply_markup=await menu_for(uid),
        )
        return

    text = msg.text or msg.caption or ""
    entities_src = list(msg.entities or []) + list(msg.caption_entities or [])

    photo_path: str | None = None
    if msg.photo:
        try:
            photo = msg.photo[-1]
            tg_file = await photo.get_file()
            user_dir = _user_media_dir(uid)
            photo_path = os.path.join(user_dir, f"{uuid.uuid4().hex}.jpg")
            await tg_file.download_to_drive(custom_path=photo_path)
        except Exception as e:
            log(f"❌ Rasm yuklashda xato {uid}: {type(e).__name__}: {e}", "error")
            await msg.reply_text(
                "❌ Rasmni saqlab bo'lmadi. Qaytadan urinib ko'ring.",
                reply_markup=await menu_for(uid),
            )
            return

    if not text.strip() and not photo_path:
        await msg.reply_text(
            "❌ Bo'sh post qabul qilinmaydi.\nMatn yoki rasm yuboring.",
            reply_markup=await menu_for(uid),
        )
        return

    entities_dict = [entity_to_dict(e) for e in entities_src]
    await db.update_post(post_id, text, entities_dict, photo_path)
    # Eski rasmni o'chiramiz (agar boshqa fayl bilan almashtirilgan bo'lsa)
    if old_photo and old_photo != photo_path:
        _safe_unlink(old_photo)
    log(f"✏️ Post tahrirlandi: {uid} (#{post_id})")
    preview = (text or "(faqat rasm)")[:100]
    kind = "🖼 Rasm + matn" if photo_path else "📝 Matn"
    await msg.reply_text(
        f"✅ Post yangilandi!\n{kind}\n\n{preview}",
        reply_markup=await menu_for(uid),
    )


async def _handle_set_interval(update: Update, text: str) -> None:
    uid = update.effective_user.id
    try:
        m = int(text.strip())
    except Exception:
        await update.message.reply_text(
            f"❌ Faqat butun son ({MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN}). Qaytadan kiriting:"
        )
        return
    if m < MIN_INTERVAL_MIN or m > MAX_INTERVAL_MIN:
        await update.message.reply_text(
            f"❌ {MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} oralig'ida bo'lishi kerak."
        )
        return
    user_states.pop(uid, None)
    await db.set_interval(uid, m)
    log(f"⏱ Interval: {uid} → {m}")
    await update.message.reply_text(
        f"✅ Interval: {m} daqiqa", reply_markup=await menu_for(uid)
    )


# ─────────────────────────────────────────────────────────────────────────
# STALE LOGIN JANITOR — tashlangan login_ctx va user_states tozalovchi
# ─────────────────────────────────────────────────────────────────────────
JANITOR_INTERVAL_S = 60  # har daqiqada tekshiramiz


async def _expire_stale_logins() -> int:
    """
    LOGIN_TIMEOUT_S muddati o'tgan login_ctx va user_states entrylarini
    tozalaydi. Telethon clientlar disconnect qilinadi.

    Returns: tozalangan entry soni
    """
    now = time.time()
    expired_uids: set[int] = set()

    # 1) login_ctx — phone yuborilgan, lekin code hech tasdiqlanmagan
    for uid, ctx in list(login_ctx.items()):
        if now - ctx.started_at > LOGIN_TIMEOUT_S:
            expired_uids.add(uid)

    # 2) user_states — login bosqichida turib qolganlar (name/phone/code/password)
    #    + edit_post (tahrirlash uchun mazmun kutilmoqda)
    for uid, state in list(user_states.items()):
        step = state.get("step")
        if step in ("name", "phone", "code", "password", "edit_post"):
            ts = state.get("ts", 0)
            if now - ts > LOGIN_TIMEOUT_S:
                expired_uids.add(uid)

    if not expired_uids:
        return 0

    for uid in expired_uids:
        with contextlib.suppress(Exception):
            await cleanup_login(uid)
        # Foydalanuvchini xabardor qilamiz (eng kichik harakat)
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                f"⏰ Login muddati tugadi ({LOGIN_TIMEOUT_S // 60} daqiqa).\n"
                "Qaytadan 🔑 Login bosing.",
                reply_markup=await menu_for(uid),
            )

    log(f"🧹 Stale login janitor: {len(expired_uids)} ta tozalandi")
    return len(expired_uids)


async def login_janitor_loop(stop: asyncio.Event) -> None:
    """
    Davriy janitor — har JANITOR_INTERVAL_S soniyada ishlaydi.
    Shutdown signali kelguncha aylanadi.
    """
    log(f"🧹 Login janitor boshlandi (har {JANITOR_INTERVAL_S}s)")
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=JANITOR_INTERVAL_S)
                break  # stop set bo'ldi
            except asyncio.TimeoutError:
                pass
            with contextlib.suppress(Exception):
                await _expire_stale_logins()
    except asyncio.CancelledError:
        pass
    log("🧹 Login janitor to'xtadi")


# ─────────────────────────────────────────────────────────────────────────
# TARIF MUDDATI JANITOR — muddati o'tganlarni to'xtatadi va xabar beradi
# ─────────────────────────────────────────────────────────────────────────
TARIFF_CHECK_INTERVAL_S = 3600  # har soatda tekshirish


async def _check_tariff_expiry() -> int:
    """Muddati tugagan foydalanuvchilarni to'xtatadi. Qaytaradi: to'xtatilganlar soni."""
    expired = await db.get_expired_users()
    if not expired:
        return 0

    stopped = 0
    for uid in expired:
        # Workerni to'xtatamiz
        if worker_manager and worker_manager.is_running(uid):
            await worker_manager.stop_worker(uid)
        await db.set_running(uid, False)
        stopped += 1

        # Yoqilgan bo'lsa, admin tahrirlagan kunlik expired xabarini yuboramiz.
        # Kunlik delivery kaliti hourly janitor va rejalashtiruvchi orasida dublikatni to'xtatadi.
        with contextlib.suppress(Exception):
            await _send_expired_user_message(uid)

        # Adminga xabar
        with contextlib.suppress(Exception):
            info = await db.get_user_info(uid)
            name = info.get("name", str(uid))
            await application.bot.send_message(
                SUPER_ADMIN,
                f"⏰ Tarif muddati tugadi\n\n"
                f"👤 {name} ({uid})\n"
                "Posting to'xtatildi. Uzaytirish uchun admin paneldan tarif yangilang.",
            )

    if stopped:
        log(f"⏰ Tarif expiry: {stopped} ta foydalanuvchi to'xtatildi")
    return stopped


async def _warn_expiring_users() -> None:
    """Muddati {TARIFF_WARN_DAYS} kun ichida tugaydigan foydalanuvchilarga BIR MARTA ogohlantirish.

    Takror oldini olish: xabar muvaffaqiyatli yuborilgach db.mark_expiry_warned()
    chaqiriladi — shunda har soatlik sikl bir xil userga qayta xabar yubormaydi.
    Tarif uzaytirilganda (set_tariff_expires) flag reset bo'ladi.
    """
    warn_uids = await db.get_expiring_users(TARIFF_WARN_DAYS)
    for uid in warn_uids:
        expires = await db.get_tariff_expires(uid)
        days_left = _days_until(expires)
        if days_left is None:
            left_line = ""
        elif days_left >= 1:
            left_line = f"⏳ Taxminan {days_left} kun qoldi\n"
        else:
            left_line = "⏳ 1 kundan kam vaqt qoldi\n"

        sent = False
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                "⚠️ Diqqat! Tarifingiz muddati tugamoqda.\n\n"
                f"📅 Tugash sanasi: {expires[:10] if expires else '-'}\n"
                f"{left_line}\n"
                "Muddat tugaganda posting avtomatik to'xtaydi.\n\n"
                "Uzaytirish uchun admin bilan bog'laning:\n"
                f"📱 {ADMIN_CONTACT_PHONE}",
            )
            sent = True  # faqat yuborish muvaffaqiyatli bo'lsa bu qatorga yetadi

        # Faqat yuborilgan bo'lsa belgilaymiz — aks holda keyingi siklda qayta urinadi
        if sent:
            with contextlib.suppress(Exception):
                await db.mark_expiry_warned(uid)


async def tariff_expiry_loop(stop: asyncio.Event) -> None:
    """Har soatda tarif muddatini tekshiradi va ogohlantirish yuboradi."""
    log(f"⏰ Tariff expiry janitor boshlandi (har {TARIFF_CHECK_INTERVAL_S}s)")
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=TARIFF_CHECK_INTERVAL_S)
                break
            except asyncio.TimeoutError:
                pass
            with contextlib.suppress(Exception):
                await _check_tariff_expiry()
            with contextlib.suppress(Exception):
                await _warn_expiring_users()
    except asyncio.CancelledError:
        pass
    log("⏰ Tariff expiry janitor to'xtadi")


def _render_daily_message(template: str, uid: int, segment: str) -> str:
    message = (template or "").replace("{admin_phone}", ADMIN_CONTACT_PHONE)
    if segment == "active":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
        if "{referral_link}" in message:
            message = message.replace("{referral_link}", link)
        else:
            message = message.rstrip() + f"\n\n🔗 Shaxsiy referal havolangiz:\n{link}"
    return message


async def _send_expired_user_message(uid: int) -> None:
    """Avoid double-notifying a user on expiry when daily messages are enabled."""
    if application is None:
        return
    config = await db.get_daily_message_config()
    if not config or not bool(config.get("enabled")):
        await application.bot.send_message(
            uid,
            _waiting_mode_text(),
            reply_markup=await menu_for(uid),
        )
        return

    delivery_date = datetime.now(DAILY_MESSAGE_TIMEZONE).date().isoformat()
    if not await db.claim_daily_message_delivery(uid, "expired", delivery_date):
        return
    status = "failed"
    detail = ""
    try:
        await application.bot.send_message(
            uid, _render_daily_message(config.get("expired_text", ""), uid, "expired")
        )
        status = "sent"
    except Exception as e:
        detail = type(e).__name__
        log(f"⚠️ Tarif tugashi xabari yetmadi {uid}: {detail}", "warning")
    await db.finish_daily_message_delivery(uid, "expired", delivery_date, status, detail)


async def _send_daily_messages_if_due(
    now: datetime | None = None,
    stop: asyncio.Event | None = None,
) -> dict[str, int]:
    """Send each enabled daily template at most once per user and local date."""
    counts = {"sent": 0, "failed": 0}
    config = await db.get_daily_message_config()
    if not config or not bool(config.get("enabled")) or application is None:
        return counts

    local_now = now or datetime.now(DAILY_MESSAGE_TIMEZONE)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=DAILY_MESSAGE_TIMEZONE)
    else:
        local_now = local_now.astimezone(DAILY_MESSAGE_TIMEZONE)
    try:
        send_time = datetime.strptime(config.get("send_time") or "10:00", "%H:%M").time()
    except ValueError:
        send_time = datetime.strptime("10:00", "%H:%M").time()
    if local_now.time().replace(tzinfo=None) < send_time:
        return counts

    delivery_date = local_now.date().isoformat()
    for segment in ("active", "expired"):
        if stop and stop.is_set():
            break
        template = (config.get(f"{segment}_text") or "").strip()
        if not template:
            continue
        targets = await db.get_daily_message_targets(
            segment, exclude_uid=SUPER_ADMIN, delivery_date=delivery_date
        )
        for target in targets:
            if stop and stop.is_set():
                return counts
            # Re-read the switch while sending so a pause takes effect promptly.
            current = await db.get_daily_message_config()
            if not current or not bool(current.get("enabled")):
                log("⏸ Kunlik xabar yuborish admin tomonidan to'xtatildi")
                return counts
            if not await db.claim_daily_message_delivery(target, segment, delivery_date):
                continue

            status = "failed"
            detail = ""
            try:
                try:
                    await application.bot.send_message(
                        target, _render_daily_message(template, target, segment)
                    )
                except RetryAfter as e:
                    retry_after = getattr(e, "retry_after", 1)
                    delay = (
                        retry_after.total_seconds()
                        if hasattr(retry_after, "total_seconds")
                        else float(retry_after)
                    )
                    if stop and await _sleep_or_stop(stop, max(1.0, delay)):
                        detail = "stopped during Telegram rate limit wait"
                    else:
                        latest = await db.get_daily_message_config()
                        if latest and bool(latest.get("enabled")):
                            await application.bot.send_message(
                                target, _render_daily_message(template, target, segment)
                            )
                        else:
                            detail = "paused during Telegram rate limit wait"
                if not detail:
                    status = "sent"
                    counts["sent"] += 1
            except Exception as e:
                detail = type(e).__name__
                counts["failed"] += 1
                log(
                    f"⚠️ Kunlik xabar yetmadi ({segment}) {target}: {detail}",
                    "warning",
                )
            await db.finish_daily_message_delivery(
                target, segment, delivery_date, status, detail
            )
            if stop and stop.is_set():
                return counts
            await asyncio.sleep(0.05)

    if counts["sent"] or counts["failed"]:
        log(
            f"📅 Kunlik xabar yakunlandi ({delivery_date}): "
            f"✅ {counts['sent']} | ❌ {counts['failed']}"
        )
    return counts


async def daily_message_loop(stop: asyncio.Event) -> None:
    """Check once per minute; delivery records make daily sends restart-safe."""
    log("📅 Kunlik xabar rejalashtiruvchisi boshlandi (har kuni 10:00, Toshkent)")
    try:
        while not stop.is_set():
            try:
                await _send_daily_messages_if_due(stop=stop)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log(f"💥 Kunlik xabar xatosi: {type(e).__name__}: {e}", "error")
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=DAILY_MESSAGE_CHECK_INTERVAL_S
                )
                break
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        pass
    log("📅 Kunlik xabar rejalashtiruvchisi to'xtadi")


async def suspension_expiry_loop(stop: asyncio.Event) -> None:
    """Muddatli admin to'xtatishlarini ochadi; postingni avtomatik boshlamaydi."""
    log("⏸ Suspension expiry janitor boshlandi")
    try:
        while not stop.is_set():
            with contextlib.suppress(Exception):
                expired_uids = await db.release_expired_suspensions()
                for target in expired_uids:
                    with contextlib.suppress(Exception):
                        await db.record_admin_action(
                            0, target, "suspension_expired", "automatic resume; posting remains stopped"
                        )
                    with contextlib.suppress(Exception):
                        await application.bot.send_message(
                            target,
                            "✅ Vaqtincha to'xtatish muddati tugadi. Hisobingiz faollashdi.\n"
                            "Postingni davom ettirish uchun ▶️ Start bosing.",
                            reply_markup=await menu_for(target),
                        )
            try:
                await asyncio.wait_for(stop.wait(), timeout=SUSPENSION_CHECK_INTERVAL_S)
                break
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        pass
    log("⏸ Suspension expiry janitor to'xtadi")


# ─────────────────────────────────────────────────────────────────────────
# RESTART-DAN KEYIN AVTO-TIKLASH
# ─────────────────────────────────────────────────────────────────────────
async def restore_running_workers() -> None:
    running_uids = await db.get_all_running()
    restored = 0
    for uid in running_uids:
        async with _user_control_lock(uid):
            if await db.is_suspended(uid):
                await db.set_running(uid, False)
                log(f"⏸ Tiklanmadi (admin to'xtatgan): {uid}")
                continue
            chats = await db.get_chats(uid)
            posts = await db.get_posts(uid)
            if not chats or not posts:
                await db.set_running(uid, False)
                continue
            # Muddati tugagan bo'lsa — tiklamaymiz (kutish rejimida qoladi)
            if await db.is_tariff_expired(uid):
                await db.set_running(uid, False)
                log(f"⏸ Tiklanmadi (muddat tugagan): {uid}")
                continue
            if await worker_manager.start_worker(uid):
                restored += 1
                log(f"🔁 Tiklandi: {uid}")
    log(f"✅ {restored} ta worker tiklandi")


# ─────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log(f"💥 Handler xato: {context.error}", "error")


async def main() -> None:
    global application, client_pool, worker_manager, health_server
    log("🚀 AVTO BOT ishga tushmoqda")

    # 1. Bazani sozlash
    await db.init_db()

    # 2. JSON'dan migratsiya (eski versiyadan, idempotent)
    migrated = await db.migrate_from_json()
    if migrated.get("files"):
        log(
            f"📦 JSON dan import: {migrated['users']} user, "
            f"{migrated['chats']} chat, {migrated['posts']} post "
            f"({len(migrated['files'])} fayl: {', '.join(migrated['files'])})"
        )

    # 3. Super admin bazada borligini ta'minlash (eng yuqori tarif — 3, cheksiz muddat)
    await db.upsert_user(SUPER_ADMIN, is_admin=1, tariff=3, tariff_expires_at=None)

    # 4. Client pool
    # MUHIM: pool hajmi worker limitiga TENG — har faol worker o'z clientini
    # ola olishi kafolatlanadi (pool<worker nomuvofiqligi bartaraf etildi).
    client_pool = ClientPool(API_ID, API_HASH, max_clients=MAX_CONCURRENT_WORKERS)
    await client_pool.start()

    # 5. Worker manager
    worker_manager = WorkerManager()
    worker_manager.set_worker_factory(posting_loop)
    worker_manager.setup_signals()

    # 6. Health server
    health_server = HealthServer()
    health_server.set_stats_providers(
        worker_stats_fn=lambda: worker_manager.stats(),
        pool_stats_fn=lambda: client_pool.stats(),
    )
    try:
        await health_server.start()
        from health import HEALTH_HOST, HEALTH_PORT
        log(f"🌐 Health server: http://{HEALTH_HOST}:{HEALTH_PORT}/health")
    except Exception as e:
        log(f"⚠️ Health server xato: {e}", "warning")

    # 7. Telegram bot
    app = Application.builder().token(BOT_TOKEN).build()
    application = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND, on_message
        )
    )
    app.add_error_handler(on_error)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log("✅ Polling boshlandi")

    # 8. Avval ishlagan workerlarni tiklash
    await restore_running_workers()

    # 8b. Stale login janitor — har daqiqada tashlangan loginlarni tozalaydi
    janitor_stop = asyncio.Event()
    janitor_task = asyncio.create_task(
        login_janitor_loop(janitor_stop), name="login-janitor"
    )

    # 8c. Tarif muddati janitor — har soatda expired userlarni to'xtatadi
    tariff_stop = asyncio.Event()
    tariff_task = asyncio.create_task(
        tariff_expiry_loop(tariff_stop), name="tariff-expiry"
    )
    suspension_stop = asyncio.Event()
    suspension_task = asyncio.create_task(
        suspension_expiry_loop(suspension_stop), name="suspension-expiry"
    )
    daily_message_stop = asyncio.Event()
    daily_message_task = asyncio.create_task(
        daily_message_loop(daily_message_stop), name="daily-message-scheduler"
    )

    # 9. Cheksiz turish (yoki shutdown signali)
    try:
        await worker_manager.wait_shutdown()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        log("🛑 To'xtatilmoqda...")
        # Janitorlarni avval to'xtatamiz
        janitor_stop.set()
        tariff_stop.set()
        suspension_stop.set()
        daily_message_stop.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(janitor_task, timeout=5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(tariff_task, timeout=5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(suspension_task, timeout=5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(daily_message_task, timeout=5)
        with contextlib.suppress(Exception):
            await worker_manager.stop_all()
        with contextlib.suppress(Exception):
            await client_pool.stop()
        with contextlib.suppress(Exception):
            await health_server.stop()
        with contextlib.suppress(Exception):
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        with contextlib.suppress(Exception):
            await db.close_db()
        log("👋 To'xtatildi")


if __name__ == "__main__":
    asyncio.run(main())
