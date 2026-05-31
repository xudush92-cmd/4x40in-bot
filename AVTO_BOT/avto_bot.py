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
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBotCommand,
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
MAX_CHAT_FAILS = 3          # chat ketma-ket shuncha xato bersa — avto-o'chiriladi
TARIFF_DURATION_DAYS = 30   # default tarif muddati (kun)
TARIFF_WARN_DAYS = 3        # muddat tugashidan necha kun oldin ogohlantirish

ADMIN_CONTACT_PHONE = "+998938670592"

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
    return ReplyKeyboardMarkup([[KeyboardButton("🔑 Login")]], resize_keyboard=True)


def kb_pending() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏳ Tasdiq kutilmoqda...")]], resize_keyboard=True
    )


def kb_main(interval: int, running: bool, super_admin: bool) -> ReplyKeyboardMarkup:
    on = "🟢 ON" if running else "🔴 OFF"
    rows = [
        [KeyboardButton("▶️ Start"), KeyboardButton("⛔ Stop")],
        [KeyboardButton(f"📊 Status ({on})"), KeyboardButton("💬 Chatlar")],
        [KeyboardButton("➕ Chat qo'sh"), KeyboardButton("➖ Chat o'chir")],
        [KeyboardButton("📝 Post qo'sh"), KeyboardButton("✏️ Post tahrir")],
        [KeyboardButton("🗑 Post o'chir"), KeyboardButton("📋 Postlar")],
        [KeyboardButton("🧹 Tozalash"), KeyboardButton(f"⏱ Interval: {interval} daq")],
        [KeyboardButton("🚪 Logout")],
    ]
    if super_admin:
        rows.append([KeyboardButton("👥 Adminlar"), KeyboardButton("🖥 Tizim")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


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
    session = (user.get("session") if user else None)

    if not approved:
        if pending:
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
        "📋 RO'YXATDAN O'TISH (3/4)\n\n"
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
        if ctx.resend_count > 3:
            await cleanup_login(uid)
            await application.bot.send_message(
                uid,
                "⏰ 3 marta kod muddati tugadi.\n\n"
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
                    f"⏰ Eski kod yaroqsiz — YANGI kod yuborildi! ({ctx.resend_count}/3)\n"
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

    await db.set_pending(uid, sess_str)
    log(f"⏳ Tasdiq kutilmoqda: {uid}")
    await notify_super_for_approval(uid)
    await application.bot.send_message(
        uid,
        "✅ Login muvaffaqiyatli!\n\n"
        "📋 RO'YXATDAN O'TISH (4/4)\n\n"
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
        f"📎 {username}\n"
        f"🆔 ID: {uid}\n\n"
        "Tarif tanlab tasdiqlang (chat/post limiti):\n"
        "• 🟢 1-Start → 5 chat / 10 post\n"
        "• 🔵 2-Biznes → 10 chat / 25 post\n"
        "• 🟡 3-Pro → 20 chat / 50 post\n"
        "• 🔴 4-Premium → 50 chat / 100 post\n\n"
        "⛔ Rad etish — sessiyasi o'chiriladi."
    )
    with contextlib.suppress(Exception):
        await application.bot.send_message(SUPER_ADMIN, text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────
# POSTING WORKER
# ─────────────────────────────────────────────────────────────────────────
async def _resolve_chat(client: TelegramClient, chat: str):
    s = chat.strip()
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

    # ── O'ZGARISH 3: SPAM HIMOYA ───────────────────────────────────────
    # Har chat uchun ketma-ket xato hisoblagichi. MAX_CHAT_FAILS ga yetsa —
    # chat avto-o'chiriladi va foydalanuvchi ogohlantiriladi.
    chat_fails: dict[str, int] = {}

    try:
        while not stop.is_set():
            sess = await db.get_session(uid)
            if not sess:
                log(f"❌ Worker:{uid} sessiya yo'q — to'xtaydi", "warning")
                break

            chats = await db.get_chats(uid)
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
                # Bu turda muvaffaqiyatsiz/muvaffaqiyatli bo'lgan chatlar
                removed_chats: list[str] = []
                for chat in chats:
                    if stop.is_set():
                        break
                    try:
                        await asyncio.wait_for(
                            _send_post(client, chat, post), timeout=20
                        )
                        ok += 1
                        chat_fails[chat] = 0   # muvaffaqiyat — hisoblagich nollanadi
                        log(f"✅ {uid} → {chat}")
                    except FloodWaitError as e:
                        # FloodWait — Telegram "sekin" deydi. Bu chat AYBI emas,
                        # shuning uchun fail hisoblanmaydi (chat o'chirilmaydi).
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
                        # O'ZGARISH 3: chat xatosi — ketma-ket hisoblaymiz
                        chat_fails[chat] = chat_fails.get(chat, 0) + 1
                        log(
                            f"❌ {uid} → {chat}: {type(e).__name__} "
                            f"({chat_fails[chat]}/{MAX_CHAT_FAILS})",
                            "warning",
                        )
                        if chat_fails[chat] >= MAX_CHAT_FAILS:
                            removed_chats.append(chat)
                    except asyncio.TimeoutError:
                        fail += 1
                        # Timeout — vaqtinchalik bo'lishi mumkin, lekin baribir
                        # ketma-ket hisoblaymiz (cheksiz osilib qolmasin)
                        chat_fails[chat] = chat_fails.get(chat, 0) + 1
                        log(
                            f"⏱ {uid} → {chat} timeout "
                            f"({chat_fails[chat]}/{MAX_CHAT_FAILS})",
                            "warning",
                        )
                        if chat_fails[chat] >= MAX_CHAT_FAILS:
                            removed_chats.append(chat)
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
                        log(f"❌ {uid} → {chat}: {type(e).__name__}: {e}", "error")
                    if not stop.is_set():
                        await _sleep_or_stop(stop, SEND_DELAY_S)

                # O'ZGARISH 3: ko'p marta xato bergan chatlarni o'chirib,
                # foydalanuvchini ogohlantiramiz (spam-bandan himoya)
                for bad in removed_chats:
                    await db.remove_chat_by_value(uid, bad)
                    chat_fails.pop(bad, None)
                    log(f"🗑 {uid} chat avto-o'chirildi (spam himoya): {bad}")
                    with contextlib.suppress(Exception):
                        await application.bot.send_message(
                            uid,
                            f"⚠️ Diqqat! Quyidagi chatga {MAX_CHAT_FAILS} marta "
                            f"xabar yuborib bo'lmadi:\n\n"
                            f"📛 {bad}\n\n"
                            "Sabab: bot o'sha chatdan chiqarilgan, yozish taqiqlangan "
                            "yoki chat mavjud emas.\n"
                            "Behuda urinishlarni to'xtatish uchun u ro'yxatdan "
                            "AVTOMATIK o'chirildi. Tekshirib, qayta qo'shing.",
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

    if await db.get_pending(uid) and not await is_approved(uid):
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
        posts_n = await db.count_posts(uid)
        interval = await db.get_interval(uid)
        active = worker_manager.is_running(uid) if worker_manager else False
        status = "🟢 ON" if active else "🔴 OFF"
        await update.message.reply_text(
            "🤖 AVTO BOT\n\n"
            f"👤 {name}\n"
            f"🎫 {tariff_label(tariff)}\n"
            f"{exp_line}\n\n"
            f"📊 Holat: {status}\n"
            f"💬 Chatlar: {chats_n}/{max_chats}\n"
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
        "4️⃣ Telegramdan kelgan kodni RAQAMLI TUGMALAR orqali kiriting\n"
        "5️⃣ 2FA bo'lsa — parolni kiriting\n"
        "6️⃣ Tasdiqlash va tarif uchun admin bilan bog'laning\n\n"
        f"📱 Admin: {ADMIN_CONTACT_PHONE}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🛡 XAVFSIZLIK\n\n"
        "✅ Kod va parol HECH QAYERDA saqlanmaydi\n"
        "✅ Faqat session token saqlanadi (Logout — o'chadi)\n"
        "✅ Ma'lumotlaringiz boshqalarga ko'rinmaydi\n"
        "✅ Istalgan vaqt '🚪 Logout' orqali chiqishingiz mumkin\n\n"
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
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

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
            if not sess:
                await q.edit_message_text(f"⚠️ {target} pending sessiyasi topilmadi.")
                return
            tariff = int(action[1])  # t1->1 ... t4->4
            await db.set_session(target, sess)
            await db.del_pending(target)
            await db.add_admin(target)
            await db.set_tariff(target, tariff)
            await db.set_tariff_expires(target, calc_expiry())
            log(f"✅ Tasdiqlandi: {target} ({tariff_label(tariff)}, {TARIFF_DURATION_DAYS} kun)")
            await q.edit_message_text(
                f"✅ Tasdiqlandi: {target}\n🎫 {tariff_label(tariff)}"
            )
            with contextlib.suppress(Exception):
                info = await db.get_user_info(target)
                name = info.get("name", "Foydalanuvchi")
                tmc, tmp = tariff_limits(tariff)
                await application.bot.send_message(
                    target,
                    f"✅ {name}, hisobingiz tasdiqlandi!\n\n"
                    f"🎫 Sizning tarifingiz: {tariff_label(tariff)}\n"
                    f"📅 Muddat: {TARIFF_DURATION_DAYS} kun\n\n"
                    "Endi:\n"
                    f"1️⃣ ➕ Chat qo'shing (max {tmc})\n"
                    f"2️⃣ 📝 Post qo'shing (max {tmp})\n"
                    "3️⃣ ⏱ Interval sozlang\n"
                    "4️⃣ ▶️ Start bosing",
                    reply_markup=await menu_for(target),
                )
        else:  # off — rad etish
            # Pending bekor qilinadi. session bu yerda yo'q (faqat pending),
            # shu sababli del_session chaqirilmaydi.
            await db.del_pending(target)
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

    if data.startswith("rmadm:"):
        if not is_super(uid):
            return
        target = int(data.split(":")[1])
        if worker_manager:
            await worker_manager.stop_worker(target)
        await client_pool.remove(target)
        await db.delete_user(target)
        _wipe_user_media(target)
        log(f"🗑 Admin o'chirildi: {target}")
        await q.edit_message_text(f"🗑 O'chirildi: {target}")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                target,
                "❌ Sizning huquqingiz bekor qilindi va ma'lumotlaringiz tozalandi.",
            )
        return

    if data == "rmadm:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
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
        if worker_manager and worker_manager.is_running(uid):
            await q.edit_message_text("⚠️ Allaqachon ishlamoqda.")
            return
        chats = await db.get_chats(uid)
        posts = await db.get_posts(uid)
        if not chats or not posts:
            await q.edit_message_text("❌ Chat yoki post yo'q. Avval qo'shing.")
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
    if data == "delp:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
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
    if data == "delc:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    if data == "adm:list":
        if not is_super(uid):
            return
        await q.edit_message_text(await format_admin_list(), reply_markup=admin_panel_kb())
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

    # Tarif o'zgartirish: foydalanuvchini tanlash
    if data == "adm:tariff":
        if not is_super(uid):
            return
        admins = await db.get_admins()
        admins = [a for a in admins if a != SUPER_ADMIN]
        if not admins:
            await q.edit_message_text("❌ Tarif o'zgartirish uchun foydalanuvchi yo'q.")
            return
        rows = []
        for a in admins:
            info = await db.get_user_info(a)
            name = info.get("name", str(a))
            t = await db.get_tariff(a)
            rows.append([InlineKeyboardButton(f"🎫 {name} ({t}-tarif)", callback_data=f"tariff:{a}")])
        rows.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="tariff:cancel")])
        await q.edit_message_text(
            "🎫 Tarifni o'zgartirish uchun foydalanuvchini tanlang:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data == "tariff:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Tanlangan foydalanuvchi uchun tarif variantlari
    if data.startswith("tariff:"):
        if not is_super(uid):
            return
        target = int(data.split(":")[1])
        info = await db.get_user_info(target)
        name = info.get("name", str(target))
        cur_t = await db.get_tariff(target)
        rows = [
            [
                InlineKeyboardButton("🟢 1-Start (5/10)", callback_data=f"settar:{target}:1"),
                InlineKeyboardButton("🔵 2-Biznes (10/25)", callback_data=f"settar:{target}:2"),
            ],
            [
                InlineKeyboardButton("🟡 3-Pro (20/50)", callback_data=f"settar:{target}:3"),
                InlineKeyboardButton("🔴 4-Premium (50/100)", callback_data=f"settar:{target}:4"),
            ],
            [InlineKeyboardButton("❌ Bekor", callback_data="tariff:cancel")],
        ]
        await q.edit_message_text(
            f"🎫 {name} — hozirgi: {cur_t}-tarif\nYangi tarifni tanlang:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # Tarifni o'rnatish + foydalanuvchiga bildirishnoma
    if data.startswith("settar:"):
        if not is_super(uid):
            return
        parts = data.split(":")
        target = int(parts[1])
        new_t = int(parts[2])
        await db.set_tariff(target, new_t)
        await db.set_tariff_expires(target, calc_expiry())
        log(f"🎫 Tarif o'zgartirildi: {target} → {new_t} (+{TARIFF_DURATION_DAYS} kun)")
        await q.edit_message_text(
            f"✅ {target} → {tariff_label(new_t)}\n📅 +{TARIFF_DURATION_DAYS} kun"
        )
        with contextlib.suppress(Exception):
            tmc, tmp = tariff_limits(new_t)
            await application.bot.send_message(
                target,
                f"🎫 Tarifingiz yangilandi: {tariff_label(new_t)}\n"
                f"📅 Muddat: {TARIFF_DURATION_DAYS} kun\n"
                f"Endi {tmc} ta chat va {tmp} ta post qo'sha olasiz.",
                reply_markup=await menu_for(target),
            )
        return


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Yangilash", callback_data="adm:list"),
                InlineKeyboardButton("🎫 Tarif o'zgartir", callback_data="adm:tariff"),
            ],
            [
                InlineKeyboardButton("➖ Admin o'chir", callback_data="adm:remove"),
            ],
        ]
    )


async def format_admin_list() -> str:
    admins = await db.get_admins()
    non_super = [a for a in admins if a != SUPER_ADMIN]
    lines = [
        f"👥 ADMINLAR ({len(admins)} ta — 1 super + {len(non_super)} oddiy):",
        "",
        f"• 👑 Super admin ({SUPER_ADMIN})",
    ]
    for a in non_super:
        info = await db.get_user_info(a)
        name = info.get("name", "Noma'lum")
        username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
        s = "✅" if await db.get_session(a) else "❌"
        ac = "🟢" if (worker_manager and worker_manager.is_running(a)) else "🔴"
        interval = await db.get_interval(a)
        tariff = await db.get_tariff(a)
        expires = await db.get_tariff_expires(a)
        exp_str = expires[:10] if expires else "cheksiz"
        chats_n = await db.count_chats(a)
        posts_n = await db.count_posts(a)
        lines.append("")
        lines.append(f"👤 {name}")
        lines.append(f"   {username} | {a}")
        lines.append(f"   Sessiya: {s} | Holat: {ac}")
        lines.append(f"   🎫 {tariff_label(tariff)}")
        lines.append(f"   📅 Muddat: {exp_str}")
        lines.append(
            f"   💬 {chats_n} | 📝 {posts_n} | ⏱ {interval} daq"
        )
    return "\n".join(lines)


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

    # LOGIN BOSQICHLARI
    if step in ("name", "phone", "code", "password"):
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
        if step == "code":
            await _handle_code(update, text)
            return
        if step == "password":
            await _handle_password(update, text)
            return

    # PENDING
    if not await is_approved(uid):
        if await db.get_pending(uid):
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

    # FSM
    if step == "add_chat":
        await _handle_add_chat(update, text)
        return
    if step == "add_post":
        await _handle_add_post(update)
        return
    if step == "edit_post":
        await _handle_edit_post(update)
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

    if text == "🚪 Logout":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="out:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="out:no"),
                ]
            ]
        )
        await msg.reply_text(
            "🚪 Tizimdan chiqasizmi?\n\nPosting to'xtaydi va sessiya o'chadi.",
            reply_markup=kb,
        )
        return

    if text == "▶️ Start":
        if worker_manager and worker_manager.is_running(uid):
            await msg.reply_text("⚠️ Allaqachon ishlamoqda.", reply_markup=await menu_for(uid))
            return
        chats = await db.get_chats(uid)
        posts = await db.get_posts(uid)
        if not chats:
            await msg.reply_text("❌ Avval ➕ Chat qo'shing.", reply_markup=await menu_for(uid))
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
        posts = await db.get_posts(uid)
        interval = await db.get_interval(uid)
        tariff = await db.get_tariff(uid)
        max_chats, max_posts = tariff_limits(tariff)
        expires = await db.get_tariff_expires(uid)
        active = worker_manager.is_running(uid) if worker_manager else False
        status = "🟢 ON" if active else "🔴 OFF"
        exp_line = f"📅 Muddat: {expires[:10]}" if expires else "📅 Muddat: cheksiz"
        await msg.reply_text(
            "📊 STATUS\n\n"
            f"Holat: {status}\n"
            f"Sessiya: ✅\n"
            f"Tarif: {tariff_label(tariff)}\n"
            f"{exp_line}\n"
            f"Chatlar: {len(chats)}/{max_chats}\n"
            f"Postlar: {len(posts)}/{max_posts}\n"
            f"Interval: {interval} daqiqa",
            reply_markup=await menu_for(uid),
        )
        return

    if text == "💬 Chatlar":
        chats = await db.get_chats(uid)
        if not chats:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        max_chats, _ = await user_limits(uid)
        lines = [f"💬 CHATLAR ({len(chats)}/{max_chats}):", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(chats, 1)]
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    if text == "➕ Chat qo'sh":
        if not rate_limiter.is_allowed(uid, "modify"):
            wait = rate_limiter.get_wait_time(uid, "modify")
            await msg.reply_text(f"⏳ {wait} soniya kuting.")
            return
        chats = await db.get_chats(uid)
        max_chats, _ = await user_limits(uid)
        if len(chats) >= max_chats:
            await msg.reply_text(
                f"❌ Maksimal {max_chats} ta chat (sizning tarifingiz). Avval birini o'chiring.",
                reply_markup=await menu_for(uid),
            )
            return
        user_states[uid] = {"step": "add_chat", "ts": time.time()}
        await msg.reply_text(
            "➕ Chat @username, https://t.me/... yoki ID yuboring.\n\n"
            f"Hozir: {len(chats)}/{max_chats}"
        )
        return

    if text == "➖ Chat o'chir":
        chats = await db.get_chats(uid)
        if not chats:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        rows = [
            [InlineKeyboardButton(f"🗑 {i+1}. {c[:40]}", callback_data=f"delc:{i}")]
            for i, c in enumerate(chats)
        ]
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="delc:cancel")])
        await msg.reply_text(
            f"➖ O'chirish uchun chatni tanlang ({len(chats)} ta):",
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

    if text == "✏️ Post tahrir":
        if not rate_limiter.is_allowed(uid, "modify"):
            wait = rate_limiter.get_wait_time(uid, "modify")
            await msg.reply_text(f"⏳ {wait} soniya kuting.")
            return
        posts = await db.get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Tahrirlash uchun post yo'q.", reply_markup=await menu_for(uid))
            return
        rows = []
        for i, p in enumerate(posts):
            icon = "🖼" if p.get("photo") else "📝"
            preview = (p.get("text") or "(rasm)")[:25]
            rows.append([InlineKeyboardButton(f"✏️ {i+1}. {icon} {preview}", callback_data=f"editp:{i}")])
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="editp:cancel")])
        await msg.reply_text(
            f"✏️ Tahrirlash uchun postni tanlang ({len(posts)} ta):",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text == "📋 Postlar":
        posts = await db.get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        lines = [f"📋 POSTLAR ({len(posts)} ta):", ""]
        for i, p in enumerate(posts, 1):
            icon = "🖼" if p.get("photo") else "📝"
            t = (p.get("text") or "(faqat rasm)")[:80]
            lines.append(f"{i}. {icon} {t}")
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    if text == "🧹 Tozalash":
        posts = await db.get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="clr:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="clr:no"),
                ]
            ]
        )
        await msg.reply_text(f"🧹 Barcha {len(posts)} ta post o'chirilsinmi?", reply_markup=kb)
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
        await msg.reply_text(await format_admin_list(), reply_markup=admin_panel_kb())
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
    user_states[uid] = {"step": "name", "ts": time.time()}
    await update.message.reply_text(
        "📋 RO'YXATDAN O'TISH (1/4)\n\n"
        "👤 To'liq ismingizni kiriting:\n\n"
        "Bu ism sizning profilingizda ko'rinadi va\n"
        "admin sizni tasdiqlashi uchun kerak.\n\n"
        "Masalan: Akmal Karimov\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 Keyingi qadamlar:\n"
        "2️⃣ Telefon raqam\n"
        "3️⃣ Tasdiqlash kodi\n"
        "4️⃣ Admin tasdiqlashi\n\n"
        f"❓ Yordam: {ADMIN_CONTACT_PHONE}"
    )


async def _handle_name(update: Update, text: str) -> None:
    uid = update.effective_user.id
    name = text.strip()
    if len(name) < 2:
        await update.message.reply_text(
            "❌ Ism juda qisqa. To'liq ismingizni yozing (kamida 2 harf):"
        )
        return
    name = name[:64]  # juda uzun bo'lmasin
    username = update.effective_user.username or ""
    # Ismni darhol saqlaymiz — admin tasdiq xabarida ko'rinadi
    await db.set_user_info(uid, name, username)
    user_states[uid] = {"step": "phone", "ts": time.time()}
    await update.message.reply_text(
        f"✅ Rahmat, {name}!\n\n"
        "📋 RO'YXATDAN O'TISH (2/4)\n\n"
        "📱 Telefon raqamingizni yuboring:\n\n"
        "Format: +998XXXXXXXXX\n\n"
        "⚠️ Telegram ilovangiz ochiq ekanligini tekshiring!\n"
        "Kod SMS emas, Telegram ilovasidagi \"Telegram\" rasmiy chatiga keladi.\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 Keyingi qadamlar:\n"
        "3️⃣ Tasdiqlash kodi\n"
        "4️⃣ Admin tasdiqlashi\n\n"
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
                "Telegram ilovangizdan kodni KO'RING (lekin kopiyalamasdan!) "
                "va pastdagi tugmalar orqali kiriting."
            ),
        )
    except PhoneNumberInvalidError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            "❌ Noto'g'ri raqam. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
    except PhoneNumberBannedError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            "🚫 Bu raqam bloklangan.", reply_markup=await menu_for(uid)
        )
    except FloodWaitError as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            f"⏳ Juda ko'p urinish. {e.seconds} soniya kuting.",
            reply_markup=await menu_for(uid),
        )
    except Exception as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        log(f"❌ phone {uid}: {type(e).__name__}: {e}", "error")
        await update.message.reply_text(
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


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
async def _handle_add_chat(update: Update, text: str) -> None:
    uid = update.effective_user.id
    user_states.pop(uid, None)
    chat = text.strip()
    if not chat:
        await update.message.reply_text("❌ Bo'sh.", reply_markup=await menu_for(uid))
        return

    max_chats, _ = await user_limits(uid)
    # Atomic check + insert (race-safe)
    ok, reason = await db.add_chat(uid, chat, max_chats=max_chats)
    if not ok:
        if reason == "limit":
            await update.message.reply_text(
                f"❌ Maksimal {max_chats} ta chat (sizning tarifingiz). Avval birini o'chiring.",
                reply_markup=await menu_for(uid),
            )
        elif reason == "duplicate":
            await update.message.reply_text(
                "⚠️ Allaqachon mavjud.", reply_markup=await menu_for(uid)
            )
        else:
            await update.message.reply_text(
                "❌ Qo'shib bo'lmadi.", reply_markup=await menu_for(uid)
            )
        return

    log(f"💬 Chat qo'shildi: {uid} → {chat}")
    new_count = await db.count_chats(uid)
    await update.message.reply_text(
        f"✅ Qo'shildi: {chat}\n💬 Jami: {new_count}/{max_chats}",
        reply_markup=await menu_for(uid),
    )


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

        # Foydalanuvchiga xabar
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                "⏰ Tarifingiz muddati tugadi!\n\n"
                "⛔ Posting avtomatik to'xtatildi.\n\n"
                "📞 Muddatni uzaytirish uchun admin bilan bog'laning:\n"
                f"📱 {ADMIN_CONTACT_PHONE}",
                reply_markup=await menu_for(uid),
            )

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
    """Muddati {TARIFF_WARN_DAYS} kun ichida tugaydigan foydalanuvchilarga ogohlantirish."""
    conn = await db._get_conn()
    async with db._op_lock:
        async with conn.execute(
            "SELECT uid FROM users WHERE tariff_expires_at IS NOT NULL "
            "AND tariff_expires_at > datetime('now') "
            "AND tariff_expires_at <= datetime('now', ?) "
            "AND running = 1 AND is_admin = 1",
            (f"+{TARIFF_WARN_DAYS} days",)
        ) as cur:
            rows = await cur.fetchall()
            warn_uids = [r[0] for r in rows]

    for uid in warn_uids:
        expires = await db.get_tariff_expires(uid)
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                f"⚠️ Diqqat! Tarifingiz muddati tugamoqda.\n\n"
                f"📅 Tugash vaqti: {expires}\n\n"
                "Uzaytirish uchun admin bilan bog'laning:\n"
                f"📱 {ADMIN_CONTACT_PHONE}",
            )


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


# ─────────────────────────────────────────────────────────────────────────
# RESTART-DAN KEYIN AVTO-TIKLASH
# ─────────────────────────────────────────────────────────────────────────
async def restore_running_workers() -> None:
    running_uids = await db.get_all_running()
    restored = 0
    for uid in running_uids:
        chats = await db.get_chats(uid)
        posts = await db.get_posts(uid)
        if not chats or not posts:
            await db.set_running(uid, False)
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
        with contextlib.suppress(Exception):
            await asyncio.wait_for(janitor_task, timeout=5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(tariff_task, timeout=5)
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
